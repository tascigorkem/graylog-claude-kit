# graylog-search

A Claude Code plugin for searching Graylog: the `graylog-search` CLI, the `graylog` skill and the
`graylog-investigator` agent. Search, count and trace your logs, or let Claude investigate them.

## Install

```text
/plugin marketplace add tascigorkem/graylog-claude-kit
/plugin install graylog-search@tascigorkem
```

## Configure

```bash
export GRAYLOG_HOST=graylog.example.com
export GRAYLOG_STREAM=0123456789abcdef01234567   # optional
```

Then add credentials: `GRAYLOG_TOKEN`, or a token or password file in `~/.config/graylog-search/`.
Check with `graylog-search --diagnose`.

## Use

- Ask Claude about your logs in plain language, or run `/graylog-search:graylog <question>`.
- For multi-query investigations: "Use graylog-investigator: …", with the ids and time window.

## What's inside

| Path | Part |
| --- | --- |
| `bin/graylog-search` | CLI wrapper, on Claude's `PATH` while the plugin is enabled |
| `skills/graylog/` | The skill and the Python implementation (`scripts/graylog_search.py`) |
| `agents/graylog-investigator.md` | The read-only investigator subagent |

Full documentation, including using the CLI in your own terminal and customising the skill:
https://github.com/tascigorkem/graylog-claude-kit

## License

Apache License 2.0; see `LICENSE` and `NOTICE`. Graylog is a trademark of Graylog, Inc. This
project is not affiliated with or endorsed by Graylog, Inc.
