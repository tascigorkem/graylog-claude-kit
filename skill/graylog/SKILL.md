---
name: graylog
description: Search application logs in Graylog via the graylog-search CLI. Use when the user asks to check or search logs, investigate what happened to a user, order or other entity in production, trace a request or error across services, diagnose a production bug from log evidence, or pastes a Graylog search URL. Also covers Graylog auth failures.
user-invocable: true
allowed-tools:
  - Read
  - Bash(graylog-search *)
  - Bash(python3 ~/.claude/skills/graylog/scripts/graylog_search.py *)
  - Bash(jq *)
---

# Graylog log search

Query Graylog from the CLI. The tool is `graylog-search` (on `PATH`), a thin wrapper around the
Python script bundled with this skill (standard library only, Python 3.9+):

```bash
graylog-search [options] '<query>'
# equivalent: python3 ~/.claude/skills/graylog/scripts/graylog_search.py [options] '<query>'
```

The host comes from `$GRAYLOG_HOST` (or `-H`), the default stream from `$GRAYLOG_STREAM` (or `-s`;
unset means every stream the account can read). `--help` lists every option.

Call it by name. Don't store the command in a shell variable (`G="python3 …"; $G …`): zsh does not
word-split variables, so that fails with "no such file or directory".

**All times are UTC**: the `-f`/`-t` arguments, Graylog's `timestamp`, and usually the app's own
`Time` field. Label times as UTC when reporting, or convert them to the user's timezone.

<!-- CUSTOMISE: add a pointer to your team's own Graylog docs here, if you have any. -->

## Before anything else

Time-box the search. One busy service over one day can be tens of thousands of messages, and a
bare `level:<=4` across all services can be millions. Always pass `--since` or `-f`/`-t`, and
narrow the query before raising `--limit`.

## Basic use

```bash
graylog-search -f 2026-07-01T00:00:00.000Z -t 2026-07-02T00:00:00.000Z -l 200 \
  'application:"order-service" AND userId:"<uuid>"'
```

Window: either absolute ISO-8601 UTC timestamps with `-f`/`-t`, or a relative window ending now
with `--since 30m|2h|3d|1w` (not both). Default is the last 24h.

## Prefer counting and tracing over reading lines

These save many query-and-`jq` rounds:

```bash
# Where is the activity? Counts over ALL hits (server-side), not just the fetched page
graylog-search --since 1d --group-by SourceSimpleClassName 'application:"payment-service" AND level:<=4'
graylog-search --since 2h --group-by application --top 10 '"<some-id>"'

# Follow one request across every service, oldest first, with the service on each line
graylog-search --since 6h --trace <traceId>
graylog-search --since 6h --trace <traceId> --group-by application   # which services it touched
graylog-search --since 6h --trace <traceId> 'level:<=4'               # only its problems
```

`--trace` matches the id as text and in the trace fields (default `traceId`, `trace_id`,
`X-B3-TraceId`, `spanId`; override with `$GRAYLOG_TRACE_FIELDS`). Get a trace id from any message
of the request (`-r ... | jq -r '.messages[].message.traceId'`). Pick the window so the whole
request falls inside it; results are sorted oldest first.

Default output is `time [logger] message`, one line per hit, prefixed by a total-hits header.
For analysis, use `-r` for raw JSON and pipe to `jq`:

```bash
graylog-search -r -l 1000 '<query>' | jq -r '.messages[].message | "\(.timestamp)  \(.message)"'
```

Full field dump for one message when you need to see what's available: `-F '' -l 1`.

## Query patterns that matter

Lucene syntax, same string as the Graylog search bar.

**Ids often appear both as structured fields and inside message text.** Cover both or you miss hits:

```
("<uuid>" OR userId:"<uuid>")
```

**Quote anything with dashes or spaces**, UUIDs especially, or Lucene tokenises them.

**Exclude chatty endpoints** when tracing a specific flow:

```
AND NOT ("health check" OR "list orders")
```

**`level` is syslog severity**: 3 error, 4 warning, 6 info. Range operators work (`level:<=4`).
Many services log almost everything at level 6, so **an empty `level:<=4` result often means the
service logged no problems, not that the query is wrong.** Verify by dropping the `application`
clause before concluding the syntax is broken.

### Known noise

Some services log routine output at warning level, which buries real problems under `level:<=4`.
Exclude these before reading warnings, and add to this table when you find one:

| Service | Noise | Exclude with |
| --- | --- | --- |
| <!-- CUSTOMISE --> `example-service` | timing lines like `[PERF] … took Nms` logged at level 4 | `AND NOT "[PERF]"` |

## Useful fields

Field names depend on how your services ship logs. Run `-F '' -l 1` once to see yours, then keep
this table up to date.

| Field | Use |
| --- | --- |
| `application` | Service name (some setups use `service` or `source`) |
| `message` | The log line |
| `timestamp` | Graylog's receive time; an app-side `Time` field, if present, is finer-grained |
| `SourceSimpleClassName` / `logger_name` | Logging class, the best grouping key |
| `level` | Severity (see above) |
| `traceId` / `spanId` | Request correlation |
| <!-- CUSTOMISE --> `userId`, `tenantId`, … | Your domain ids |

## Streams

<!-- CUSTOMISE: list your streams so the agent can pick the right one with -s. -->

| Id | Stream |
| --- | --- |
| `0123456789abcdef01234567` | Production (example) |
| `89abcdef0123456701234567` | Acceptance (example) |

If you run a separate Graylog instance for non-production environments, always pass both `-H` and
`-s` for it: a stream id from one instance does not exist on the other (HTTP 404).

## Converting a pasted UI URL

`?q=` → the positional query (URL-decode it), `&streams=` → `-s`, `&from=` → `-f`, `&to=` → `-t`,
and the URL's host → `-H`.

## When auth fails

Run `graylog-search --diagnose`. It reports status codes for basic auth, session login and stream
read without exposing secrets.

- **401 on everything** → usually the username. With LDAP or SSO the Graylog login name can differ
  from what you expect (for example an email on a different domain than the Graylog host).
  Credentials live in `~/.config/graylog-search/`.
- **403** → the account lacks permission for that stream or endpoint. Not a setup bug.
- Do not retry logins repeatedly to guess a password: report the failure and let the user fix it.

## Reporting findings

Lead with the narrative the logs support (what happened, in order, with timestamps), not a dump of
matched lines. Quote the specific lines that carry the conclusion. Where the logs are consistent
with more than one explanation, say so rather than picking one.

Production logs can contain personal data and real user ids. Include ids when they're needed to
follow the trace, but don't paste bulk output anywhere external, and don't write raw results into
repository files.
