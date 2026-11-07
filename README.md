# graylog-claude-kit

Search Graylog from your terminal, and let [Claude Code](https://code.claude.com) investigate
production logs for you.

[Graylog](https://graylog.org) is an open-source platform that collects logs from your services
in one place and lets you search them. If your team uses it, this kit gives you a faster way in.

The kit has three parts that work together:

| Part | What it is | Path |
| --- | --- | --- |
| **`graylog-search` CLI** | A command-line Graylog client. Python 3.9+ standard library only; no `pip install` | `bin/graylog-search` → `skill/graylog/scripts/graylog_search.py` |
| **`graylog` skill** | Teaches Claude Code how to query your Graylog well: time-boxing, query patterns, counting and tracing, auth troubleshooting | `skill/graylog/SKILL.md` |
| **`graylog-investigator` agent** | A read-only Claude Code subagent that runs a multi-query investigation in its own context and returns a short report (conclusion, timeline, evidence, queries used) | `agent/graylog-investigator.md` |

You can use the CLI on its own. The skill and agent need the CLI.

## What the CLI adds over the Graylog UI

The output below is illustrative (made-up services and data), but shows the real format.

**Relative time windows**: no timestamps to compute.

```console
$ graylog-search --since 2h 'application:"order-service" AND level:<=4'
# 3 hits, showing 3 (times are UTC)
2026-11-05T13:12:40.118Z  [InventoryClient] Slow response from inventory-service: 2140ms
2026-11-05T13:58:02.731Z  [PaymentClient] Retrying payment request (attempt 2 of 3)
2026-11-05T14:02:11.482Z  [OrderController] Order creation failed: payment declined by provider
```

**Counts over all hits**, computed by Graylog, so you see where the problems are before reading
a single line:

```console
$ graylog-search --since 1d --group-by application --top 5 'level:<=3'
# 1874 hits, grouped by application (top 5 values; 96 hits elsewhere or without the field)
1022  payment-service
 431  order-service
 187  notification-service
  92  inventory-service
  46  api-gateway
```

**One request across every service**, oldest first, with the service on each line:

```console
$ graylog-search --since 6h --trace 6f1c2a9e0b7d4c3a
# 6 hits, showing 6 (times are UTC)
2026-11-05T14:02:10.903Z  api-gateway  [RequestLogger] POST /api/orders received
2026-11-05T14:02:10.951Z  order-service  [OrderController] Creating order for cart c-1042
2026-11-05T14:02:11.204Z  inventory-service  [StockService] Reserved 2 items for cart c-1042
2026-11-05T14:02:11.377Z  payment-service  [ProviderClient] Provider answered 402: insufficient funds
2026-11-05T14:02:11.482Z  order-service  [OrderController] Order creation failed: payment declined by provider
2026-11-05T14:02:11.530Z  inventory-service  [StockService] Released reservation for cart c-1042
```

Add `--group-by application` to a trace to see only which services it touched.

It also handles token and password auth (including the session-login fallback some LDAP setups
need), mints API tokens for you, and has a `--diagnose` mode that reports which auth path works
without printing secrets.

## Requirements

- Python 3.9 or newer (`python3 --version`)
- A Graylog 4.x or newer server you can log in to. Developed against Graylog 4.2.
  `--group-by` uses the Views search API (`/api/views/search/sync`); if your account cannot use
  it, the CLI falls back to counting the fetched messages and says so.
- For the skill and agent: Claude Code.

## Install

```bash
git clone <this-repo-url> graylog-claude-kit && cd graylog-claude-kit

# 1. The skill (includes the Python script)
mkdir -p ~/.claude/skills
cp -R skill/graylog ~/.claude/skills/graylog

# 2. The agent (optional)
mkdir -p ~/.claude/agents
cp agent/graylog-investigator.md ~/.claude/agents/

# 3. The CLI on your PATH
mkdir -p ~/.local/bin
cp bin/graylog-search ~/.local/bin/graylog-search
chmod +x ~/.local/bin/graylog-search ~/.claude/skills/graylog/scripts/graylog_search.py
```

Make sure `~/.local/bin` is on your `PATH`. The `bin/graylog-search` wrapper runs the script
from the installed skill, so the CLI and Claude always use the same code. Running
`bin/graylog-search` directly from the cloned repo also works.

Start a new Claude Code session (or run `/reload-plugins`) to pick up the skill and agent.

## Configure

**1. Point it at your Graylog**, for example in `~/.zshrc` or `~/.bashrc`:

```bash
export GRAYLOG_HOST=graylog.example.com
export GRAYLOG_STREAM=0123456789abcdef01234567   # optional: default stream; unset = all streams you can read
```

Find stream ids in the Graylog UI (Streams page, or `streams=` in a search URL).

**2. Add credentials.** Any one of these, checked in this order:

```bash
# a) An API token in the environment
export GRAYLOG_TOKEN=...

# b) An API token file
mkdir -p ~/.config/graylog-search && umask 077
printf '%s' 'YOUR_TOKEN' > ~/.config/graylog-search/token-graylog_example_com

# c) Username and password (the file name is the host with dots replaced by underscores)
cat > ~/.config/graylog-search/credentials-graylog_example_com.properties <<'EOF'
user=YOUR_GRAYLOG_LOGIN
password=YOUR_PASSWORD
EOF
```

With a password file in place, you can switch to a token and then delete the password file:

```bash
graylog-search --create-token        # saves the token next to the password file
```

**3. Check it works:**

```bash
graylog-search --diagnose
graylog-search --since 15m --group-by application '*'
```

### All settings

| Environment variable | Flag | Default | Purpose |
| --- | --- | --- | --- |
| `GRAYLOG_HOST` | `-H`, `--host` | (required) | Graylog host name |
| `GRAYLOG_STREAM` | `-s`, `--stream` | all readable streams | Stream to search |
| `GRAYLOG_TOKEN` | | | API token (highest priority credential) |
| `GRAYLOG_CONFIG_DIR` | | `~/.config/graylog-search` | Where token and credential files live |
| `GRAYLOG_TRACE_FIELDS` | | `traceId,trace_id,X-B3-TraceId,spanId` | Fields `--trace` searches |

## Using the CLI

```text
graylog-search [options] '<lucene query>'

time window (default: last 24 hours)
  --since 30m|2h|3d|1w        relative window ending now
  -f, --from TS / -t, --to TS absolute ISO-8601 UTC, e.g. 2026-09-01T00:00:00.000Z

where
  -H, --host HOST             Graylog host
  -s, --stream ID             stream id

output
  -l, --limit N               max messages (default 500)
  -r, --raw                   raw JSON (pipe to jq)
  -F ''                       full key=value dump of each message
  --group-by FIELD [--top N]  count hits per field value, server-side
  --trace ID                  follow one id across services; a query narrows it

account
  --whoami, --diagnose, --create-token [NAME], --list-tokens
```

Examples:

```bash
# What went wrong in one service in the last hour?
graylog-search --since 1h --group-by SourceSimpleClassName 'application:"payment-service" AND level:<=4'

# Everything about one id, in the structured field or in the message text
graylog-search --since 1d '("3f2b8c1e-0000-4000-8000-000000000001" OR userId:"3f2b8c1e-0000-4000-8000-000000000001")'

# Which services did this request touch, and did any of them log a problem?
graylog-search --since 6h --trace 6f1c2a9e0b7d4c3a --group-by application
graylog-search --since 6h --trace 6f1c2a9e0b7d4c3a 'level:<=4'

# A non-production instance
graylog-search -H graylog-dev.example.com -s 89abcdef0123456701234567 --since 1h 'application:"order-service"'

# Raw JSON for your own analysis
graylog-search --since 1h -r -l 1000 'application:"order-service"' | jq -r '.messages[].message.message'
```

All times in output are UTC.

## Using it with Claude Code

### The `graylog` skill

Use it for quick lookups and for debugging together with Claude, where you want to see the log
lines in your conversation. Once the skill is installed, ask in plain language:

```text
Check the logs: did order-service log errors in the last two hours?
What happened to user 3f2b8c1e-… around 14:00 UTC yesterday?
```

Claude loads the `graylog` skill and runs `graylog-search`. You can also call the skill
explicitly with `/graylog <question>`.

### The `graylog-investigator` agent

Use it for investigations that need many queries. It works in its own context, keeps the raw
log output out of your conversation, and returns only the report.

The agent builds on the skill: its first step is to load the `graylog` skill and follow it for
everything about querying. So the agent needs the skill installed, and anything you add to
`SKILL.md` (streams, field names, known noise) improves the agent too.

```text
Use graylog-investigator: checkout failed for user 3f2b8c1e-… on 2026-11-05 around 14:00 UTC.
Find out what went wrong.
```

The agent does not see your conversation, so include the identifiers, the time window and what
you already know in the request.

## Customise the skill for your team

`skill/graylog/SKILL.md` ships with generic examples. Search it for `CUSTOMISE` and fill in:

- **Streams**: your stream ids and names, so Claude picks the right one.
- **Useful fields**: your field names (run `graylog-search -F '' -l 1 '*'` once to see them).
- **Known noise**: services that log routine output at warning level, and how to exclude it.
- A pointer to your team's own Graylog docs, if you have any.

The more of your setup the skill describes, the fewer exploratory queries Claude needs.

## Security notes

- Credential files should be readable only by you (`chmod 600`); the instructions above use
  `umask 077`, and `--create-token` writes the token with mode 600.
- The CLI only reads: it searches, reads your user record, and can create or list API tokens on
  your own account. The agent is restricted to `Bash`, `Read` and `Skill` and is instructed never
  to change anything.
- Production logs can contain personal data. When you use the skill or agent, log lines go into
  your Claude session. Make sure that is allowed by your organisation's AI and data policies
  before you point it at production.

## Layout

```text
bin/graylog-search                         CLI wrapper (POSIX sh)
skill/graylog/SKILL.md                     Claude Code skill
skill/graylog/scripts/graylog_search.py    the implementation
agent/graylog-investigator.md              Claude Code subagent
CLAUDE.md                                  notes for contributors working on this repo with Claude Code
LICENSE                                    MIT
```

## License

graylog-claude-kit is developed under the [MIT License](LICENSE).

Görkem Taşçı, 2026

LinkedIn: https://www.linkedin.com/in/tascigorkem/
