# graylog-claude-kit

Notes for working on this repository. User documentation is in `README.md`.

## What is what

- `skill/` and `agent/` are the product: users copy them into their own `~/.claude/`. They are
  not active skills or agents for working on this repo.
- `skill/graylog/scripts/graylog_search.py` is the whole implementation. `bin/graylog-search` is
  only a POSIX `sh` wrapper that finds and runs it.

## Rules

- `graylog_search.py` stays standard-library only and runs on Python 3.9+: no third-party
  packages, no syntax newer than 3.9 (no `match`, no `X | Y` types at runtime; the
  `from __future__ import annotations` import keeps annotations safe).
- No built-in hosts, stream ids or field values from any real setup. Configuration comes from
  flags and `GRAYLOG_*` environment variables.
- Examples everywhere use generic names: `graylog.example.com`, `graylog-dev.example.com`,
  `order-service`, `payment-service`, placeholder ids. Never real hostnames, stream ids, service
  names, user ids or log lines.
- The CLI only reads from Graylog (plus creating or listing the user's own API tokens). Keep it
  that way.
- A new or changed flag or environment variable is updated in the same change in:
  - `README.md` (Configure / All settings and Using the CLI),
  - `skill/graylog/SKILL.md`, when it changes how Claude should query,
  - the `--help` examples in `graylog_search.py`.
- Error messages say what went wrong and how to fix it, and never print secrets.

## Checks before committing

```bash
python3 -m py_compile skill/graylog/scripts/graylog_search.py
python3 -c 'import ast; ast.parse(open("skill/graylog/scripts/graylog_search.py").read(), feature_version=(3, 9))'
bin/graylog-search --help
```

If you have access to a Graylog server, also run `graylog-search --diagnose` and one search with
`--group-by` and `--trace`.
