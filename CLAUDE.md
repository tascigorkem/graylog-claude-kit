# graylog-claude-kit

Notes for working on this repository. User documentation is in `README.md`.

## What is what

- The repository root is a Claude Code plugin marketplace (`.claude-plugin/marketplace.json`)
  with one plugin, `graylog-search`, in `plugins/graylog-search/`.
- Everything under `plugins/graylog-search/` (skill, agent, CLI) is the product that users
  install. None of it is an active skill or agent for working on this repo.
- `plugins/graylog-search/skills/graylog/scripts/graylog_search.py` is the whole implementation.
  `plugins/graylog-search/bin/graylog-search` is only a POSIX `sh` wrapper that finds and runs it.
- The plugin name must not contain "claude" (Claude Code rejects names that read as
  Anthropic's own); the repository name may.

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
  - `skills/graylog/SKILL.md`, when it changes how Claude should query,
  - the `--help` examples in `graylog_search.py`.
- A change users should receive bumps `version` in `plugins/graylog-search/.claude-plugin/plugin.json`.
- `LICENSE` and `NOTICE` exist twice: at the repository root (for GitHub) and in
  `plugins/graylog-search/` (shipped with every installed copy). Keep each pair identical.
- The project is Apache-2.0. New source files start with `# SPDX-License-Identifier: Apache-2.0`.
- Error messages say what went wrong and how to fix it, and never print secrets.

## Checks before committing

```bash
python3 -m py_compile plugins/graylog-search/skills/graylog/scripts/graylog_search.py
python3 -c 'import ast; ast.parse(open("plugins/graylog-search/skills/graylog/scripts/graylog_search.py").read(), feature_version=(3, 9))'
plugins/graylog-search/bin/graylog-search --help
claude plugin validate . && claude plugin validate plugins/graylog-search
cmp LICENSE plugins/graylog-search/LICENSE && cmp NOTICE plugins/graylog-search/NOTICE
```

If you have access to a Graylog server, also run `graylog-search --diagnose` and one search with
`--group-by` and `--trace`.
