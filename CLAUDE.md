# graylog-claude-kit

Notes for working on this repository. User documentation is in `README.md`.

## What is what

- The repository root is a Claude Code plugin marketplace (`.claude-plugin/marketplace.json`)
  with one plugin, `graylog-search`, in `plugins/graylog-search/`.
- Everything under `plugins/graylog-search/` (skill, agent, CLI) is the product that users
  install. None of it is an active skill or agent for working on this repo.
- `plugins/graylog-search/skills/graylog/scripts/graylog_search.py` is the whole implementation.
  `plugins/graylog-search/bin/graylog-search` is only a POSIX `sh` wrapper that finds and runs it.
- `tests/` holds the unit tests (standard-library `unittest`, no network). It sits outside the
  plugin folder on purpose, so it is not installed with the plugin.
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
- A change users should receive bumps `version` in `plugins/graylog-search/.claude-plugin/plugin.json`
  and `__version__` in `graylog_search.py` (they must match), and gets a `CHANGELOG.md` entry.

## Releasing

Semantic versioning: patch for fixes, minor for additions, major for breaking changes (while on
0.x, a minor version may also break the CLI). For version X.Y.Z:

1. Move the `[Unreleased]` entries in `CHANGELOG.md` under `## [X.Y.Z] - <date>` and update the
   links at the bottom.
2. Set the version in `plugin.json` and `__version__`; run the checks below.
3. `git commit -am "Release X.Y.Z"`, then `git tag -a vX.Y.Z -m "vX.Y.Z"` on that commit.
4. `git push && git push origin vX.Y.Z`, then create the GitHub Release from the tag with the
   changelog entry as its notes. Never move a pushed tag; release a new version instead.
- `LICENSE` and `NOTICE` exist twice: at the repository root (for GitHub) and in
  `plugins/graylog-search/` (shipped with every installed copy). Keep each pair identical.
- The project is Apache-2.0. New source files start with `# SPDX-License-Identifier: Apache-2.0`.
- Error messages say what went wrong and how to fix it, and never print secrets.
- Configuration from the environment is read when needed (`config_dir()`, `trace_fields()`),
  never in module-level constants, so tests and callers can change it.
- A change in behaviour comes with a test in `tests/test_graylog_search.py`. Tests never reach a
  real Graylog: replace `Graylog.request` (see `FakeGraylog`) instead.

## Checks before committing

Ruff (linter and formatter, settings in `ruff.toml`) is the only tool not built into Python. It is
a development tool, not a dependency of the CLI: install it with `brew install ruff` or
`pipx install ruff`. Use the version pinned in `.github/workflows/checks.yml` when you can, and
run `ruff format .` to fix formatting.

```bash
ruff check . && ruff format --check .
python3 -m unittest discover -s tests
python3 -m py_compile plugins/graylog-search/skills/graylog/scripts/graylog_search.py
python3 -c 'import ast; ast.parse(open("plugins/graylog-search/skills/graylog/scripts/graylog_search.py").read(), feature_version=(3, 9))'
plugins/graylog-search/bin/graylog-search --help
claude plugin validate . && claude plugin validate plugins/graylog-search
cmp LICENSE plugins/graylog-search/LICENSE && cmp NOTICE plugins/graylog-search/NOTICE
test "$(plugins/graylog-search/bin/graylog-search --version | cut -d' ' -f2)" = \
     "$(python3 -c 'import json; print(json.load(open("plugins/graylog-search/.claude-plugin/plugin.json"))["version"])')" \
  && echo "versions match"
```

If you have access to a Graylog server, also run `graylog-search --diagnose` and one search with
`--group-by` and `--trace`.

GitHub Actions (`.github/workflows/checks.yml`) runs the same checks on every push and pull
request, in two stages:

1. `repository`: Ruff lint and format, ShellCheck on the wrapper, the JSON manifests, the
   version match and the license copies.
2. `python`, only if stage 1 passed: Python 3.9 on `ubuntu-24.04` (the last Ubuntu with 3.9
   builds), and the newest stable Python (3.15) on Linux and on macOS.

Python 3.9 stays supported because it is macOS's built-in `python3`; when GitHub retires
`ubuntu-24.04`, revisit that run. When a new Python is released (each October), move the
"newest" runs to it. When a check is added or changed here, update the workflow in the same
change, and the other way round.
