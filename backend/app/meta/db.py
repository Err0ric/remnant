"""Metadata database (SQLite): sources, checkpoints, and later users and audit.

Migrations are an ordered list of SQL scripts, applied once each and recorded
in `schema_migrations`. Additive only: never edit or reorder an applied script.
"""

import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path


def _rebuild_kinds(
    old: tuple[str, ...], new: tuple[str, ...]
) -> Callable[[sqlite3.Connection], None]:
    """A migration that widens the sources.kind CHECK. The CHECK was added as a column
    constraint (migration 23), which SQLite cannot change in place, so the table is rebuilt
    from its own current definition: same columns, rows, indexes, and triggers."""

    def _quoted(kinds: tuple[str, ...]) -> str:
        return "CHECK (kind IN (" + ", ".join(f"'{k}'" for k in kinds) + "))"

    def migrate(con: sqlite3.Connection) -> None:
        (table_sql,) = con.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'sources'"
        ).fetchone()
        if table_sql.count(_quoted(old)) != 1:
            raise sqlite3.DatabaseError("sources.kind constraint not found where expected")
        extras = [
            r[0]
            for r in con.execute(
                "SELECT sql FROM sqlite_master WHERE tbl_name = 'sources'"
                " AND type IN ('index', 'trigger') AND sql IS NOT NULL"
            )
        ]
        head = table_sql.index("(")
        new_sql = "CREATE TABLE sources_new " + table_sql[head:].replace(_quoted(old), _quoted(new))
        con.execute(new_sql)
        con.execute("INSERT INTO sources_new SELECT * FROM sources")
        con.execute("DROP TABLE sources")
        con.execute("ALTER TABLE sources_new RENAME TO sources")
        for sql in extras:
            con.execute(sql)

    return migrate


# Migration 28: allow kind 'otlp' (ADR-0015).
_widen_source_kinds = _rebuild_kinds(("file", "loki"), ("file", "loki", "otlp"))


Migration = str | Callable[[sqlite3.Connection], None]

MIGRATIONS: tuple[Migration, ...] = (
    # 1: sources and file checkpoints
    """
    CREATE TABLE sources (
        source_id      TEXT PRIMARY KEY,
        format         TEXT NOT NULL,
        path           TEXT NOT NULL,
        glob           TEXT NOT NULL DEFAULT '*',
        timezone       TEXT NOT NULL DEFAULT 'UTC',
        classification TEXT NOT NULL DEFAULT 'local_only',
        retention_days INTEGER NOT NULL DEFAULT 30,
        enabled        INTEGER NOT NULL DEFAULT 1,
        owner_id       TEXT NOT NULL DEFAULT 'local',
        created_at     TEXT NOT NULL
    );
    CREATE TABLE checkpoints (
        source_id   TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
        path        TEXT NOT NULL,
        inode       INTEGER NOT NULL,
        offset      INTEGER NOT NULL,
        csv_header  TEXT,
        updated_at  TEXT NOT NULL,
        PRIMARY KEY (source_id, path)
    );
    """,
    # 2: accounts, sessions, append-only audit log (ADR-0001, CLAUDE.md security rule 10)
    """
    CREATE TABLE users (
        user_id       TEXT PRIMARY KEY,
        username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        role          TEXT NOT NULL CHECK (role IN ('admin', 'analyst', 'auditor')),
        disabled      INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT NOT NULL,
        last_login_at TEXT
    );
    CREATE TABLE sessions (
        token_hash   TEXT PRIMARY KEY,
        user_id      TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        csrf_token   TEXT NOT NULL,
        kind         TEXT NOT NULL CHECK (kind IN ('browser', 'cli')),
        created_at   TEXT NOT NULL,
        expires_at   TEXT NOT NULL
    );
    CREATE INDEX sessions_user ON sessions(user_id);
    CREATE TABLE audit_log (
        audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts       TEXT NOT NULL,
        user_id  TEXT,
        action   TEXT NOT NULL,
        outcome  TEXT NOT NULL CHECK (outcome IN ('success', 'failure', 'denied')),
        ip       TEXT,
        detail   TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
    BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
    CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
    BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
    """,
    # 3: a line longer than one read is emitted truncated; the rest of it is skipped
    """
    ALTER TABLE checkpoints ADD COLUMN skip_to_newline INTEGER NOT NULL DEFAULT 0;
    """,
    # 4: one-time invite and reset links (ADR-0004); only a SHA-256 of each token is stored
    """
    CREATE TABLE user_tokens (
        token_hash TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        purpose    TEXT NOT NULL CHECK (purpose IN ('invite', 'reset')),
        created_by TEXT,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
    CREATE INDEX user_tokens_user ON user_tokens(user_id);
    """,
    # 5: source groups, the per-user access boundary (SPEC 3.6, D17, ADR-0004)
    """
    CREATE TABLE source_groups (
        group_id    TEXT PRIMARY KEY,
        name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
        description TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL
    );
    CREATE TABLE group_sources (
        group_id  TEXT NOT NULL REFERENCES source_groups(group_id) ON DELETE CASCADE,
        source_id TEXT NOT NULL,
        PRIMARY KEY (group_id, source_id)
    );
    CREATE TABLE user_groups (
        user_id  TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        group_id TEXT NOT NULL REFERENCES source_groups(group_id) ON DELETE CASCADE,
        PRIMARY KEY (user_id, group_id)
    );
    CREATE INDEX user_groups_user ON user_groups(user_id);
    """,
    # 6: named, listable, revocable CLI and API tokens (sessions of kind 'cli')
    """
    ALTER TABLE sessions ADD COLUMN token_id TEXT;
    ALTER TABLE sessions ADD COLUMN label TEXT;
    ALTER TABLE sessions ADD COLUMN last_used_at TEXT;
    UPDATE sessions SET token_id = lower(hex(randomblob(16))) WHERE token_id IS NULL;
    CREATE UNIQUE INDEX sessions_token_id ON sessions(token_id);
    """,
    # 7: removing a source removes its grants, so a later source with the same id
    # starts ungranted (review finding, ADR-0004 deny by default)
    """
    DELETE FROM group_sources WHERE source_id NOT IN (SELECT source_id FROM sources);
    CREATE TRIGGER sources_delete_grants AFTER DELETE ON sources
    BEGIN DELETE FROM group_sources WHERE source_id = OLD.source_id; END;
    """,
    # 8: saved searches (SPEC 5.4)
    """
    CREATE TABLE saved_searches (
        search_id   TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        owner_id    TEXT NOT NULL,
        visibility  TEXT NOT NULL CHECK (visibility IN ('private', 'shared')),
        tags        TEXT NOT NULL DEFAULT '[]',
        sources     TEXT,
        mode        TEXT NOT NULL DEFAULT 'query' CHECK (mode IN ('query', 'ask')),
        sql         TEXT NOT NULL,
        params      TEXT NOT NULL DEFAULT '[]',
        origin      TEXT,
        verified    INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE INDEX saved_searches_owner ON saved_searches(owner_id);
    """,
    # 9: model providers (SPEC 6.1); API keys encrypted with data/.key. A fresh install
    # gets one disabled entry for the compose Ollama service.
    """
    CREATE TABLE llm_providers (
        provider_id TEXT PRIMARY KEY,
        name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
        kind        TEXT NOT NULL CHECK (kind IN ('openai_compat')),
        base_url    TEXT NOT NULL,
        model       TEXT NOT NULL DEFAULT '',
        api_key_enc TEXT,
        enabled     INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    INSERT INTO llm_providers (provider_id, name, kind, base_url, created_at, updated_at)
    VALUES (lower(hex(randomblob(16))), 'Local Ollama', 'openai_compat',
            'http://ollama:11434/v1', datetime('now'), datetime('now'));
    """,
    # 10: model-call audit (SPEC 6.4). Written ahead of the call, completed once, then
    # frozen: a row can never be deleted, and after finished_at is set never changed.
    """
    CREATE TABLE llm_calls (
        call_id               TEXT PRIMARY KEY,
        ts                    TEXT NOT NULL,
        owner_id              TEXT NOT NULL,
        provider_id           TEXT NOT NULL,
        model                 TEXT NOT NULL,
        locality              TEXT NOT NULL CHECK (locality IN ('local', 'cloud')),
        purpose               TEXT NOT NULL
                              CHECK (purpose IN ('ask', 'parser_draft', 'explain', 'report')),
        prompt_ref            TEXT NOT NULL,
        sources_in_scope      TEXT NOT NULL,
        classification_result TEXT NOT NULL CHECK (classification_result IN ('allowed', 'blocked')),
        redaction_applied     INTEGER NOT NULL DEFAULT 0,
        prompt_sha256         TEXT,
        prompt_body           TEXT,
        prompt_tokens         INTEGER,
        completion_tokens     INTEGER,
        latency_ms            INTEGER,
        response_sha256       TEXT,
        response_body         TEXT,
        cited_event_ids       TEXT,
        citation_check        TEXT CHECK (citation_check IN ('pass', 'fail')),
        error                 TEXT,
        finished_at           TEXT
    ) WITHOUT ROWID;
    CREATE INDEX llm_calls_ts ON llm_calls(ts);
    CREATE INDEX llm_calls_owner ON llm_calls(owner_id);
    CREATE TRIGGER llm_calls_no_delete BEFORE DELETE ON llm_calls
    BEGIN SELECT RAISE(ABORT, 'llm_calls is append-only'); END;
    CREATE TRIGGER llm_calls_no_replace BEFORE INSERT ON llm_calls
    WHEN EXISTS (SELECT 1 FROM llm_calls WHERE call_id = NEW.call_id)
    BEGIN SELECT RAISE(ABORT, 'llm_calls is append-only'); END;
    CREATE TRIGGER llm_calls_complete_once BEFORE UPDATE ON llm_calls
    WHEN OLD.finished_at IS NOT NULL
      OR NEW.finished_at IS NULL
      OR NEW.call_id IS NOT OLD.call_id
      OR NEW.ts IS NOT OLD.ts
      OR NEW.owner_id IS NOT OLD.owner_id
      OR NEW.provider_id IS NOT OLD.provider_id
      OR NEW.model IS NOT OLD.model
      OR NEW.locality IS NOT OLD.locality
      OR NEW.purpose IS NOT OLD.purpose
      OR NEW.prompt_ref IS NOT OLD.prompt_ref
      OR NEW.sources_in_scope IS NOT OLD.sources_in_scope
      OR NEW.classification_result IS NOT OLD.classification_result
      OR NEW.redaction_applied IS NOT OLD.redaction_applied
      OR NEW.prompt_sha256 IS NOT OLD.prompt_sha256
      OR NEW.prompt_body IS NOT OLD.prompt_body
    BEGIN SELECT RAISE(ABORT, 'llm_calls rows are completed once and then frozen'); END;
    """,
    # 11: INSERT OR REPLACE deletes the old row without firing DELETE triggers, so refuse
    # any insert that reuses an existing audit id (review finding on the gate PR)
    """
    CREATE TRIGGER audit_log_no_replace BEFORE INSERT ON audit_log
    WHEN NEW.audit_id IS NOT NULL
     AND EXISTS (SELECT 1 FROM audit_log WHERE audit_id = NEW.audit_id)
    BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
    """,
    # 12: a source can be parsed by a template (SPEC 4); NULL keeps the generic parser
    """
    ALTER TABLE sources ADD COLUMN template_id TEXT;
    """,
    # 13: .evtx checkpoints: signature of a fully read file, so an unchanged file is not
    # re-parsed
    """
    ALTER TABLE checkpoints ADD COLUMN file_signature TEXT;
    """,
    # 14: .evtx checkpoints: digest of the last record read, so a different log reusing the
    # same record ids (another host, or a cleared log) is read from the start
    """
    ALTER TABLE checkpoints ADD COLUMN content_digest TEXT;
    """,
    # 15: template drafts and approvals (ADR-0005). Draft YAML lives in
    # data/templates/drafts/<id>.yaml; these rows hold who, when, and the sample.
    """
    CREATE TABLE template_drafts (
        template_id  TEXT PRIMARY KEY,
        created_by   TEXT NOT NULL,
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL,
        sample_kind  TEXT NOT NULL CHECK (sample_kind IN ('file', 'pasted', 'none')),
        sample_path  TEXT,
        sample_glob  TEXT,
        sample_text  TEXT,
        llm_call_id  TEXT
    );
    CREATE TABLE template_approvals (
        approval_id  TEXT PRIMARY KEY,
        template_id  TEXT NOT NULL,
        version      TEXT NOT NULL,
        sha256       TEXT NOT NULL,
        approved_by  TEXT NOT NULL,
        approved_at  TEXT NOT NULL,
        llm_call_id  TEXT
    );
    CREATE TRIGGER template_approvals_no_update BEFORE UPDATE ON template_approvals
    BEGIN SELECT RAISE(ABORT, 'approvals are append-only'); END;
    CREATE TRIGGER template_approvals_no_delete BEFORE DELETE ON template_approvals
    BEGIN SELECT RAISE(ABORT, 'approvals are append-only'); END;
    """,
    # 16: was the approved YAML exactly what the model wrote, or edited afterwards?
    """
    ALTER TABLE template_drafts ADD COLUMN llm_yaml_sha256 TEXT;
    ALTER TABLE template_approvals ADD COLUMN llm_output_unchanged INTEGER;
    """,
    # 17: Sigma rules (ADR-0006). rule_versions are pinned snapshots of exact file content
    # and never change; rules points each rule id at the version an admin last imported.
    """
    CREATE TABLE rule_imports (
        import_id    TEXT PRIMARY KEY,
        path         TEXT NOT NULL,
        imported_by  TEXT NOT NULL,
        imported_at  TEXT NOT NULL,
        files        INTEGER NOT NULL,
        accepted     INTEGER NOT NULL,
        refused      INTEGER NOT NULL,
        new_rules    INTEGER NOT NULL,
        updated      INTEGER NOT NULL
    );
    CREATE TABLE rule_versions (
        sha256       TEXT PRIMARY KEY,
        rule_id      TEXT NOT NULL,
        title        TEXT NOT NULL,
        author       TEXT NOT NULL,
        level        TEXT NOT NULL,
        status       TEXT NOT NULL,
        product      TEXT,
        service      TEXT,
        category     TEXT,
        tags         TEXT NOT NULL,
        yaml         TEXT NOT NULL,
        import_id    TEXT NOT NULL REFERENCES rule_imports(import_id)
    );
    CREATE TRIGGER rule_versions_no_update BEFORE UPDATE ON rule_versions
    BEGIN SELECT RAISE(ABORT, 'rule versions are immutable'); END;
    CREATE TRIGGER rule_versions_no_delete BEFORE DELETE ON rule_versions
    BEGIN SELECT RAISE(ABORT, 'rule versions are immutable'); END;
    CREATE TABLE rules (
        rule_id      TEXT PRIMARY KEY,
        sha256       TEXT NOT NULL REFERENCES rule_versions(sha256),
        path         TEXT NOT NULL,
        enabled      INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
        import_id    TEXT NOT NULL REFERENCES rule_imports(import_id),
        updated_at   TEXT NOT NULL
    );
    CREATE TABLE rule_refusals (
        import_id    TEXT NOT NULL REFERENCES rule_imports(import_id),
        path         TEXT NOT NULL,
        reason       TEXT NOT NULL
    );
    CREATE INDEX rule_refusals_import ON rule_refusals (import_id);
    """,
    # 18: Sigma rule runs and their matches (ADR-0006 row 6). A run records the exact rule
    # version (sha256) and the sources it read; matches keep event ids. Rows are never
    # edited; old runs may be pruned later (scheduled runs keep the last 30), and the
    # audit log keeps every run regardless.
    """
    CREATE TABLE rule_runs (
        run_id           TEXT PRIMARY KEY,
        rule_id          TEXT NOT NULL,
        sha256           TEXT NOT NULL REFERENCES rule_versions(sha256),
        started_by       TEXT NOT NULL,
        started_at       TEXT NOT NULL,
        range_start      TEXT NOT NULL,
        range_end        TEXT NOT NULL,
        status           TEXT NOT NULL CHECK (status IN ('ok', 'no_data', 'failed')),
        match_count      INTEGER NOT NULL,
        matches_stored   INTEGER NOT NULL,
        elapsed_ms       INTEGER NOT NULL,
        sources_in_scope TEXT NOT NULL,
        error            TEXT
    );
    CREATE INDEX rule_runs_rule ON rule_runs (rule_id, started_at);
    CREATE TABLE rule_matches (
        run_id     TEXT NOT NULL REFERENCES rule_runs(run_id),
        event_id   TEXT NOT NULL,
        event_time TEXT,
        source_id  TEXT NOT NULL
    );
    CREATE INDEX rule_matches_run ON rule_matches (run_id);
    CREATE TRIGGER rule_runs_no_update BEFORE UPDATE ON rule_runs
    BEGIN SELECT RAISE(ABORT, 'rule runs are not edited'); END;
    CREATE TRIGGER rule_matches_no_update BEFORE UPDATE ON rule_matches
    BEGIN SELECT RAISE(ABORT, 'rule matches are not edited'); END;
    """,
    # 19: scheduled saved searches and rules (SPEC 5.5). A schedule runs as its owner with
    # permissions checked every run; runs keep a capped sample and the sources read.
    """
    CREATE TABLE schedules (
        schedule_id      TEXT PRIMARY KEY,
        kind             TEXT NOT NULL CHECK (kind IN ('search', 'rule')),
        target_id        TEXT NOT NULL,
        name             TEXT NOT NULL,
        owner_id         TEXT NOT NULL,
        shared           INTEGER NOT NULL DEFAULT 0 CHECK (shared IN (0, 1)),
        cron             TEXT NOT NULL,
        lookback_minutes INTEGER,
        params           TEXT NOT NULL DEFAULT '{}',
        target_sha256    TEXT NOT NULL,
        scope_sources    TEXT,
        threshold_kind   TEXT CHECK (threshold_kind IN ('above', 'below', 'change_pct')),
        threshold_value  REAL,
        paused           INTEGER NOT NULL DEFAULT 0 CHECK (paused IN (0, 1)),
        paused_reason    TEXT,
        next_run_at      TEXT,
        last_run_at      TEXT,
        created_at       TEXT NOT NULL,
        updated_at       TEXT NOT NULL
    );
    CREATE INDEX schedules_due ON schedules (paused, next_run_at);
    CREATE TABLE schedule_runs (
        run_id           TEXT PRIMARY KEY,
        schedule_id      TEXT NOT NULL REFERENCES schedules(schedule_id) ON DELETE CASCADE,
        started_at       TEXT NOT NULL,
        range_start      TEXT,
        range_end        TEXT,
        status           TEXT NOT NULL CHECK (status IN ('ok', 'failed', 'paused')),
        row_count        INTEGER,
        elapsed_ms       INTEGER,
        sources_in_scope TEXT NOT NULL,
        columns          TEXT,
        sample           TEXT,
        truncated        INTEGER NOT NULL DEFAULT 0,
        flagged          INTEGER NOT NULL DEFAULT 0,
        flag_reason      TEXT,
        error            TEXT,
        rule_run_id      TEXT
    );
    CREATE INDEX schedule_runs_schedule ON schedule_runs (schedule_id, started_at);
    """,
    # 20: alert routing (ADR-0007). Secrets (webhook URL, SMTP password, signing key) are
    # encrypted with the install key; deliveries keep status and errors, never the URL.
    """
    CREATE TABLE alert_targets (
        target_id            TEXT PRIMARY KEY,
        name                 TEXT NOT NULL UNIQUE,
        kind                 TEXT NOT NULL CHECK (kind IN ('email', 'slack', 'teams', 'webhook')),
        display              TEXT NOT NULL,
        settings             TEXT NOT NULL DEFAULT '{}',
        secret_enc           TEXT NOT NULL,
        created_by           TEXT NOT NULL,
        created_at           TEXT NOT NULL,
        updated_at           TEXT NOT NULL,
        consecutive_failures INTEGER NOT NULL DEFAULT 0,
        last_error           TEXT,
        last_sent_at         TEXT
    );
    CREATE TABLE schedule_alert_targets (
        schedule_id TEXT NOT NULL REFERENCES schedules(schedule_id) ON DELETE CASCADE,
        target_id   TEXT NOT NULL REFERENCES alert_targets(target_id) ON DELETE CASCADE,
        PRIMARY KEY (schedule_id, target_id)
    );
    CREATE TABLE alert_deliveries (
        delivery_id     TEXT PRIMARY KEY,
        target_id       TEXT NOT NULL,
        schedule_id     TEXT,
        run_id          TEXT,
        alert           TEXT NOT NULL,
        status          TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'failed')),
        attempts        INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TEXT,
        last_error      TEXT,
        created_at      TEXT NOT NULL,
        sent_at         TEXT
    );
    CREATE INDEX alert_deliveries_due ON alert_deliveries (status, next_attempt_at);
    CREATE INDEX alert_deliveries_schedule ON alert_deliveries (schedule_id, created_at);
    """,
    # 21: the audit log viewer (Slice 5) filters by time, action, and user.
    """
    CREATE INDEX audit_log_ts ON audit_log (ts);
    CREATE INDEX audit_log_action ON audit_log (action, audit_id);
    CREATE INDEX audit_log_user ON audit_log (user_id, audit_id);
    """,
    # 22: Anthropic provider kind (SPEC 6.1). SQLite cannot change a CHECK constraint in
    # place, so the table is rebuilt with the same columns and rows.
    """
    CREATE TABLE llm_providers_new (
        provider_id TEXT PRIMARY KEY,
        name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
        kind        TEXT NOT NULL CHECK (kind IN ('openai_compat', 'anthropic')),
        base_url    TEXT NOT NULL,
        model       TEXT NOT NULL DEFAULT '',
        api_key_enc TEXT,
        enabled     INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    INSERT INTO llm_providers_new (provider_id, name, kind, base_url, model, api_key_enc,
                                   enabled, created_at, updated_at)
    SELECT provider_id, name, kind, base_url, model, api_key_enc, enabled, created_at,
           updated_at FROM llm_providers;
    DROP TABLE llm_providers;
    ALTER TABLE llm_providers_new RENAME TO llm_providers;
    """,
    # 23: pull connectors, Loki first (ADR-0011). A Loki source keeps its settings as JSON
    # and its credential encrypted with the install key; its read position lives in
    # connector_checkpoints (newest timestamp read and the line hashes at it).
    """
    ALTER TABLE sources ADD COLUMN kind TEXT NOT NULL DEFAULT 'file'
        CHECK (kind IN ('file', 'loki'));
    ALTER TABLE sources ADD COLUMN connector TEXT;
    ALTER TABLE sources ADD COLUMN connector_secret_enc TEXT;
    CREATE TABLE connector_checkpoints (
        source_id  TEXT PRIMARY KEY,
        position   TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    # 24: opt-in redaction per provider (ADR-0010, D36), and what each call redacted
    # (counts per kind, never values).
    """
    ALTER TABLE llm_providers ADD COLUMN redact INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE llm_calls ADD COLUMN redaction_counts TEXT;
    """,
    # 25: per-provider thinking control, sent as reasoning_effort (NULL: model default).
    """
    ALTER TABLE llm_providers ADD COLUMN reasoning TEXT
        CHECK (reasoning IS NULL OR reasoning IN ('none', 'low', 'medium', 'high'));
    """,
    # 26: optional single sign-on (ADR-0013): the provider identity bound through an invite.
    """
    ALTER TABLE users ADD COLUMN sso_issuer TEXT;
    ALTER TABLE users ADD COLUMN sso_subject TEXT;
    CREATE UNIQUE INDEX users_sso_identity ON users (sso_issuer, sso_subject)
        WHERE sso_subject IS NOT NULL;
    """,
    # 27: alerts when a source goes quiet (ADR-0014).
    """
    CREATE TABLE source_watches (
        source_id     TEXT PRIMARY KEY,
        quiet_after_s INTEGER NOT NULL CHECK (quiet_after_s BETWEEN 300 AND 604800),
        target_ids    TEXT NOT NULL DEFAULT '[]',
        state         TEXT NOT NULL DEFAULT 'ok' CHECK (state IN ('ok', 'quiet')),
        quiet_since   TEXT,
        last_seen     TEXT,
        created_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL,
        updated_by    TEXT
    );
    ALTER TABLE alert_deliveries ADD COLUMN source_id TEXT;
    CREATE INDEX alert_deliveries_source ON alert_deliveries (source_id, created_at);
    """,
    # 28: OTLP sources (ADR-0015 row 3): kind 'otlp' (a table rebuild, see above).
    _widen_source_kinds,
    # 29: a hashed ingest token per OTLP source and the admin's choice to keep prompt and
    # tool content (ADR-0015 row 4; off by default).
    """
    ALTER TABLE sources ADD COLUMN otlp_token_hash TEXT;
    ALTER TABLE sources ADD COLUMN otlp_keep_content INTEGER NOT NULL DEFAULT 0;
    CREATE UNIQUE INDEX sources_otlp_token ON sources (otlp_token_hash)
        WHERE otlp_token_hash IS NOT NULL;
    """,
    # 30: AI usage visibility (ADR-0015 rows 1, 7, 9): review status of catalog services,
    # services an admin added, MCP server rules, first sightings, and the AI watch.
    """
    CREATE TABLE ai_service_status (
        service_id TEXT PRIMARY KEY,
        status     TEXT NOT NULL CHECK (status IN ('approved', 'not_approved')),
        note       TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        updated_by TEXT
    );
    CREATE TABLE ai_custom_services (
        service_id TEXT PRIMARY KEY,
        name       TEXT NOT NULL,
        vendor     TEXT NOT NULL DEFAULT '',
        kind       TEXT NOT NULL,
        domains    TEXT NOT NULL,
        created_at TEXT NOT NULL,
        created_by TEXT
    );
    CREATE TABLE ai_mcp_rules (
        pattern    TEXT PRIMARY KEY,
        status     TEXT NOT NULL CHECK (status IN ('approved', 'not_approved')),
        note       TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        updated_by TEXT
    );
    CREATE TABLE ai_sightings (
        kind       TEXT NOT NULL CHECK (kind IN ('service', 'mcp', 'sensitive')),
        name       TEXT NOT NULL,
        subject    TEXT NOT NULL,
        first_seen TEXT NOT NULL,
        PRIMARY KEY (kind, name, subject)
    );
    CREATE TABLE ai_watch (
        id                 INTEGER PRIMARY KEY CHECK (id = 1),
        enabled            INTEGER NOT NULL DEFAULT 0,
        include_unreviewed INTEGER NOT NULL DEFAULT 0,
        sensitive          INTEGER NOT NULL DEFAULT 1,
        target_ids         TEXT NOT NULL DEFAULT '[]',
        cursor             TEXT,
        updated_at         TEXT NOT NULL,
        updated_by         TEXT
    );
    """,
    # 31: Microsoft 365 and Anthropic API sources (ADR-0002, ADR-0015 row 10).
    _rebuild_kinds(("file", "loki", "otlp"), ("file", "loki", "otlp", "m365", "anthropic")),
    # 32: one person under several names (ADR-0018): organization domains and aliases.
    """
    CREATE TABLE identity_domains (
        domain   TEXT PRIMARY KEY,
        position INTEGER NOT NULL,
        added_by TEXT,
        added_at TEXT NOT NULL
    );
    CREATE TABLE identity_aliases (
        alias      TEXT PRIMARY KEY COLLATE NOCASE,
        person     TEXT NOT NULL,
        created_by TEXT,
        created_at TEXT NOT NULL
    );
    """,
)


def _statements(script: str) -> Iterator[str]:
    """Split a migration into complete statements (trigger bodies stay whole)."""
    buf = ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                yield buf
            buf = ""
    if buf.strip():
        yield buf  # an incomplete tail: let SQLite report the error


class MetaDB:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        # Re-entrant: a nested connect() in the same thread (a bug) then fails fast on
        # SQLite's busy timeout instead of deadlocking the server.
        self._lock = threading.RLock()
        self._migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """A short-lived connection; commits on success, rolls back on error."""
        with self._lock:
            con = sqlite3.connect(self._path, timeout=5)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys = ON")
            # REPLACE then fires DELETE triggers too (append-only tables stay append-only).
            con.execute("PRAGMA recursive_triggers = ON")
            try:
                yield con
                con.commit()
            except BaseException:
                con.rollback()
                raise
            finally:
                con.close()

    def _migrate(self) -> None:
        """Apply pending migrations in one write transaction.

        BEGIN IMMEDIATE takes SQLite's write lock before reading which versions are done,
        so a second process starting at the same moment waits and then finds nothing left
        to do. Statements run one by one inside the transaction (executescript would commit
        first), so a failure rolls everything back instead of leaving half a migration.
        """
        con = sqlite3.connect(self._path, timeout=60, isolation_level=None)
        try:
            # Off (the default) so a table rebuild cannot cascade; it cannot change inside
            # the transaction, so it is set first.
            con.execute("PRAGMA foreign_keys = OFF")
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"
            )
            done = {r[0] for r in con.execute("SELECT version FROM schema_migrations")}
            for version, script in enumerate(MIGRATIONS, start=1):
                if version in done:
                    continue
                if callable(script):
                    script(con)
                else:
                    for statement in _statements(script):
                        con.execute(statement)
                con.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
            con.execute("COMMIT")
        except BaseException:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        finally:
            con.close()
