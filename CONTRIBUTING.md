# Contributing

Thanks for helping. The most useful contributions right now are, in order:

1. **Parser templates** for log sources you run
2. **Bug reports** with a way to reproduce them
3. **Docs fixes**, especially install steps that did not work for you

For security problems, do not open an issue: see [SECURITY.md](SECURITY.md).

## Before you start

- Read [CLAUDE.md](CLAUDE.md). It holds the build rules every change follows, including the architecture rules that are not up for negotiation in a single PR (deterministic core, one gate for model calls, read-only query engine).
- For anything bigger than a bug fix or a template, open an issue first so we can agree on the approach. Design decisions are recorded in [docs/SPEC.md](docs/SPEC.md) and [docs/adr/](docs/adr/).

## Adding a parser template

A template is one YAML file in `templates/starter/` plus a fixture folder.

1. Copy the closest existing template (for example `templates/starter/linux_sshd.yaml` for syslog text, `unifi.yaml` for key=value, `paloalto_traffic.yaml` for CSV).
2. Map fields to the OCSF columns listed in `backend/app/core/schema.py`. Do not invent new columns.
3. Add `backend/tests/fixtures/logs/<template_id>/` with:
   - `sample.log`: at least 50 real-shaped lines with **synthetic values only**
   - `expected.jsonl`: the parsed output for the first 10 lines
   - `pathological.log`: long lines, garbage, multiline fragments
   - `README.md`: the source product, version, and collector used to shape it
4. Run `uv run pytest -m templates` from `backend/`. The template must parse at least 95% of `sample.log` and raise nothing on `pathological.log`.

Not sure how to write one? Open a **Parser template request** issue with a few sanitized sample lines.

## Synthetic data only

Nothing in this repository may come from a real environment. Use:

- Domains: `example.com`, `example.org`, `example.net`, `*.example`, `*.test`
- IPv4: `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, or RFC 1918 ranges for internal examples
- IPv6: `2001:db8::/32`
- People: fictional names such as alice, bob, carol, or j.doe

No real company names, people, hostnames, public addresses, tokens, or keys, in code, fixtures, docs, screenshots, issues, or commit messages. Product names Remnant integrates with (Palo Alto, Microsoft 365, and so on) are fine.

## Running the tests

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22 with pnpm.

```bash
make ci                                  # everything CI runs: architecture checks, lint, types, tests, build
cd backend && uv run pytest              # backend only
cd frontend && pnpm test                 # frontend only
```

More in [docs/development.md](docs/development.md).

## Pull requests

- Keep PRs small: one feature or fix, under about 400 lines of non-fixture changes.
- Use conventional commit messages: `feat(ingest): ...`, `fix(engine): ...`, `docs: ...`, `test(templates): ...`.
- Write the test first for parsers, the SQL guard, and the model gate.
- No em dashes in code comments, docs, or UI text (house style).
- `make ci` must pass.

By contributing, you agree that your contribution is licensed under the Apache License 2.0.
