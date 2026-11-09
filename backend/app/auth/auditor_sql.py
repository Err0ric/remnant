"""Whether Auditors may run SQL (D220). One install setting, off by default; only admins
change it, and the API audits every change. When on, an Auditor's SQL goes through the same
per-session events view, guard, and scope as anyone's."""

from app.auth.users import User
from app.core.errors import AuditorSqlOffError
from app.meta.db import MetaDB

REFUSAL = (
    "Auditors cannot run SQL on this install. An administrator can allow it in"
    " Settings > Users and access."
)


def enabled(meta: MetaDB) -> bool:
    with meta.connect() as con:
        row = con.execute("SELECT auditor_sql FROM install_settings WHERE id = 1").fetchone()
    return bool(row[0]) if row else False


def save(meta: MetaDB, on: bool, user_id: str) -> bool:
    with meta.connect() as con:
        con.execute(
            "INSERT INTO install_settings (id, auditor_sql, updated_by) VALUES (1, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET auditor_sql = excluded.auditor_sql,"
            " updated_by = excluded.updated_by",
            (int(on), user_id),
        )
    return enabled(meta)


def check(meta: MetaDB, user: User) -> None:
    """Raise AuditorSqlOffError for an Auditor while the setting is off."""
    if user.role == "auditor" and not enabled(meta):
        raise AuditorSqlOffError(REFUSAL)
