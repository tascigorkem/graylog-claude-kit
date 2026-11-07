#!/usr/bin/env python3
"""Query a Graylog server from the command line.

Built for humans and for AI coding agents (Claude Code), with additions that make log
investigations cheaper than paging through raw messages:

  --since 2h            relative time window instead of absolute -f/-t timestamps
  --group-by FIELD      count hits per value of a field, server-side, over ALL hits
  --trace ID            follow one trace id (or any id) across every service, in time order

Standard library only (Python 3.9+): no pip install needed.

Configuration (flags win over environment variables):
  GRAYLOG_HOST          Graylog host name, e.g. graylog.example.com          (or -H/--host)
  GRAYLOG_STREAM        default stream id; unset = all streams you can read  (or -s/--stream)
  GRAYLOG_CONFIG_DIR    where credentials live (default ~/.config/graylog-search)
  GRAYLOG_TRACE_FIELDS  comma-separated fields that hold trace ids
                        (default traceId,trace_id,X-B3-TraceId,spanId)

Credentials are resolved in this order:
  1. $GRAYLOG_TOKEN
  2. <config dir>/token-<host_with_underscores>
  3. <config dir>/credentials-<host_with_underscores>.properties   (user=... / password=...)
An API token is sent as the basic-auth username with the literal password "token".
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_LIMIT = 500
DEFAULT_FIELDS = "timestamp,source,application,message"
DEFAULT_TOKEN_NAME = "graylog-search-cli"
TIMEOUT_SECONDS = 120

CONFIG_DIR = Path(os.environ.get("GRAYLOG_CONFIG_DIR", Path.home() / ".config" / "graylog-search")).expanduser()

# Fields that may carry a trace or correlation id; --trace searches all of them.
TRACE_FIELDS = tuple(
    field.strip()
    for field in os.environ.get("GRAYLOG_TRACE_FIELDS", "traceId,trace_id,X-B3-TraceId,spanId").split(",")
    if field.strip()
)

# Fields tried, in order, for the "service" and "logger" columns of a message line.
SERVICE_FIELDS = ("application", "service", "app", "source")
LOGGER_FIELDS = ("SourceSimpleClassName", "logger_name", "LoggerName", "source")


class GraylogError(Exception):
    """A failure the user can act on; printed without a traceback."""


# --------------------------------------------------------------------------------------------
# Time handling
# --------------------------------------------------------------------------------------------

def iso_utc(moment: datetime) -> str:
    """Format a datetime the way Graylog's absolute search expects it."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def parse_since(value: str) -> timedelta:
    """Turn '30m', '2h', '3d' or '1w' into a timedelta."""
    match = re.fullmatch(r"\s*(\d+)\s*([mhdw])\s*", value)
    if not match:
        raise GraylogError(f"--since expects a number and a unit (m, h, d, w), e.g. 30m or 2h; got '{value}'")
    amount, unit = int(match.group(1)), match.group(2)
    return {"m": timedelta(minutes=amount), "h": timedelta(hours=amount),
            "d": timedelta(days=amount), "w": timedelta(weeks=amount)}[unit]


def resolve_window(args: argparse.Namespace) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    if args.since and (args.from_ts or args.to_ts):
        raise GraylogError("use either --since or -f/-t, not both")
    if args.since:
        return iso_utc(now - parse_since(args.since)), iso_utc(now)
    return args.from_ts or iso_utc(now - timedelta(hours=24)), args.to_ts or iso_utc(now)


# --------------------------------------------------------------------------------------------
# Credentials and HTTP
# --------------------------------------------------------------------------------------------

class Credentials:
    def __init__(self, host: str):
        slug = host.replace(".", "_")
        self.token_file = CONFIG_DIR / f"token-{slug}"
        self.cred_file = CONFIG_DIR / f"credentials-{slug}.properties"
        self.user = ""
        self.password = ""
        self.login_user = ""      # set only for username/password auth
        self.login_password = ""
        self.kind = ""

        env_token = os.environ.get("GRAYLOG_TOKEN", "").strip()
        if env_token:
            self.user, self.password, self.kind = env_token, "token", "token (env)"
        elif self.token_file.is_file():
            self.user = "".join(self.token_file.read_text().split())
            self.password, self.kind = "token", f"token ({self.token_file})"
        elif self.cred_file.is_file():
            props = read_properties(self.cred_file)
            self.user, self.password = props.get("user", ""), props.get("password", "")
            self.login_user, self.login_password = self.user, self.password
            self.kind = f"password ({self.cred_file})"

        if not self.user or not self.password:
            raise GraylogError(missing_credentials_help(host, self))


def read_properties(path: Path) -> dict[str, str]:
    props: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            props[key.strip()] = value.strip()
    return props


def missing_credentials_help(host: str, creds: Credentials) -> str:
    return (
        f"No Graylog credentials for {host}. Create one of these:\n\n"
        f"  # username + password (your Graylog login name)\n"
        f"  mkdir -p {CONFIG_DIR} && umask 077 && cat > {creds.cred_file} <<'EOC'\n"
        f"user=YOUR_GRAYLOG_USERNAME\n"
        f"password=YOUR_GRAYLOG_PASSWORD\n"
        f"EOC\n\n"
        f"  # or an API token\n"
        f"  mkdir -p {CONFIG_DIR} && umask 077 && printf '%s' 'TOKEN' > {creds.token_file}\n\n"
        f"  # or export GRAYLOG_TOKEN for this shell\n"
    )


def resolve_host(flag_value: str | None) -> str:
    host = (flag_value or os.environ.get("GRAYLOG_HOST", "")).strip()
    host = re.sub(r"^https?://", "", host).rstrip("/")
    if not host:
        raise GraylogError("No Graylog host. Pass -H graylog.example.com or set GRAYLOG_HOST.")
    return host


class Response:
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body

    @property
    def ok(self) -> bool:
        return self.status in (200, 201)

    def json(self) -> dict:
        return json.loads(self.body) if self.body else {}


class Graylog:
    def __init__(self, host: str, creds: Credentials):
        self.host = host
        self.creds = creds
        self.username = ""  # Graylog login name, once known

    def request(self, method: str, path: str, params: dict | None = None,
                body: dict | None = None, authenticate: bool = True) -> Response:
        url = f"https://{self.host}/api{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Accept": "application/json", "X-Requested-By": "cli"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if authenticate:
            pair = f"{self.creds.user}:{self.creds.password}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(pair).decode()
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                return Response(resp.status, resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as err:
            return Response(err.code, err.read().decode("utf-8", "replace"))
        except urllib.error.URLError as err:
            raise GraylogError(f"Could not reach https://{self.host}: {err.reason}. "
                               "Check the host name and your network or VPN.") from err

    def check(self, resp: Response, hint: str = "") -> Response:
        if resp.ok:
            return resp
        lines = [f"Graylog returned HTTP {resp.status}  [auth: {self.creds.kind}]"]
        lines += {
            401: ["  -> credentials rejected. Check the login name: with LDAP/SSO it may differ from "
                  "your email or the host's domain. Run --diagnose for details."],
            403: ["  -> authenticated, but your account lacks permission for this call or stream"],
            404: ["  -> no such resource (is the stream id right for this host?)"],
        }.get(resp.status, [])
        if hint:
            lines.append(f"  {hint}")
        if resp.body:
            lines.append(resp.body[:500])
        raise GraylogError("\n".join(lines))

    # Some setups (LDAP-backed or tightened config) refuse basic auth with a password and only
    # allow the session endpoint: trade the password for a session id and use that instead.
    def session_login(self) -> Response:
        resp = self.request("POST", "/system/sessions", authenticate=False, body={
            "username": self.creds.login_user, "password": self.creds.login_password, "host": self.host})
        if resp.status == 200:
            data = resp.json()
            if data.get("session_id"):
                self.creds.user, self.creds.password = data["session_id"], "session"
                self.creds.kind = "session (from password)"
                self.username = data.get("username", "")
        return resp

    def ensure_auth(self) -> None:
        """For password auth: try basic auth once, fall back to a session on 401."""
        if not self.creds.login_user:
            return
        resp = self.request("GET", f"/users/{quote(self.creds.login_user)}")
        if resp.status != 401:
            return  # 200, or a 403/404 that is about permissions or the name, not about auth
        if self.session_login().status != 200 or self.creds.password != "session":
            raise GraylogError(
                f"Both basic auth and session login were rejected for user '{self.creds.login_user}'.\n"
                "Check the username (your Graylog login name) and password.")

    def current_username(self) -> str:
        if self.username:
            return self.username
        if self.creds.login_user:
            self.username = self.creds.login_user
            return self.username
        # Graylog 4.x has no /users/self; the sessions endpoint reports the caller.
        resp = self.request("GET", "/system/sessions")
        if resp.status == 200:
            data = resp.json()
            self.username = data.get("username") or data.get("user_id") or ""
        if not self.username:
            raise GraylogError("Could not determine the current user.")
        return self.username

    def current_user_id(self) -> str:
        resp = self.check(self.request("GET", f"/users/{quote(self.current_username())}"))
        user_id = resp.json().get("id")
        if not user_id:
            raise GraylogError(f"No id in the user record for '{self.username}'.")
        return user_id

    def search(self, query: str, frm: str, to: str, stream: str | None, limit: int,
               fields: str | None, sort: str = "timestamp:asc") -> dict:
        params = {"query": query, "from": frm, "to": to, "limit": limit, "sort": sort}
        if stream:
            params["filter"] = f"streams:{stream}"
        if fields:
            params["fields"] = fields
        resp = self.request("GET", "/search/universal/absolute", params=params)
        hint = f"(stream {stream} may be outside your permissions)" if resp.status == 403 and stream else ""
        return self.check(resp, hint).json()

    def terms(self, field: str, query: str, frm: str, to: str, stream: str | None,
              size: int) -> tuple[list[tuple[str, int]], int] | None:
        """Server-side counts per field value over ALL hits, via the Views search API
        (Graylog 4+; the legacy /search/universal/.../terms endpoint is gone in 4.x).
        Returns (counts, total), or None if the API is unavailable to this account."""
        search_query = {
            "id": "q",
            "query": {"type": "elasticsearch", "query_string": query},
            "timerange": {"type": "absolute", "from": frm, "to": to},
            "search_types": [{
                "id": "counts", "type": "pivot", "rollup": True,
                "row_groups": [{"type": "values", "field": field, "limit": size}],
                "column_groups": [],
                "series": [{"type": "count", "id": "count()"}],
            }],
        }
        if stream:
            search_query["filter"] = {"type": "or", "filters": [{"type": "stream", "id": stream}]}
        resp = self.request("POST", "/views/search/sync", body={"queries": [search_query]})
        if resp.status in (403, 404, 405, 501):
            return None
        result = self.check(resp).json()["results"]["q"]
        if result.get("errors"):
            raise GraylogError("Graylog could not run the count: "
                               + "; ".join(str(e.get("description", e)) for e in result["errors"]))
        pivot = result["search_types"]["counts"]
        counts = [(row["key"][0], int(row["values"][0]["value"]))
                  for row in pivot.get("rows", []) if row.get("source") == "leaf" and row.get("key")]
        # Graylog reports messages without the field as "(Empty Value)", on top of the limit.
        counts = [(f"<no {field}>" if value == "(Empty Value)" else value, count) for value, count in counts]
        counts.sort(key=lambda kv: -kv[1])
        return counts[:size], int(pivot.get("total", 0))


def quote(segment: str) -> str:
    return urllib.parse.quote(segment, safe="")


# --------------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------------

def first_field(msg: dict, names: tuple[str, ...], default: str = "") -> str:
    for name in names:
        if msg.get(name):
            return str(msg[name])
    return default


def message_line(msg: dict, with_service: bool) -> str:
    when = msg.get("Time") or msg.get("timestamp", "")
    where = first_field(msg, LOGGER_FIELDS)
    text = msg.get("message", "")
    if with_service:
        return f"{when}  {first_field(msg, SERVICE_FIELDS, '?')}  [{where}] {text}"
    return f"{when}  [{where}] {text}"


def print_messages(result: dict, full: bool, with_service: bool) -> None:
    messages = [m["message"] for m in result.get("messages", [])]
    print(f"# {result.get('total_results', 0)} hits, showing {len(messages)} (times are UTC)")
    for msg in messages:
        if full:
            print("  ".join(f"{key}={value}" for key, value in msg.items()))
        else:
            print(message_line(msg, with_service))


def print_counts(counts: list[tuple[str, int]], total: int, field: str, note: str) -> None:
    print(f"# {total} hits, grouped by {field}{note}")
    width = max((len(str(count)) for _, count in counts), default=1)
    for value, count in counts:
        print(f"{count:>{width}}  {value}")


# --------------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------------

def cmd_search(gl: Graylog, args: argparse.Namespace) -> None:
    frm, to = resolve_window(args)

    if args.trace:
        trace = args.trace.replace('"', "")
        clauses = [f'"{trace}"'] + [f'{field}:"{trace}"' for field in TRACE_FIELDS]
        query = "(" + " OR ".join(clauses) + ")"
        if args.query:
            query += f" AND ({args.query})"
    elif args.query:
        query = args.query
    else:
        raise GraylogError("A query is required, e.g. graylog-search --since 2h 'application:\"order-service\"'")

    if args.group_by:
        server_counts = gl.terms(args.group_by, query, frm, to, args.stream, args.top)
        if server_counts is not None:
            counts, total = server_counts
            counted = sum(count for _, count in counts)
            note = f" (top {len(counts)} values; {total - counted} hits elsewhere or without the field)" \
                if counted < total else ""
            print_counts(counts, total, args.group_by, note)
            return
        # Older or restricted servers: count over the fetched messages instead.
        result = gl.search(query, frm, to, args.stream, args.limit, None)
        messages = [m["message"] for m in result.get("messages", [])]
        counter = Counter(str(m.get(args.group_by, f"<no {args.group_by}>")) for m in messages)
        note = f" (counted over the first {len(messages)} messages; raise --limit to count more)"
        print_counts(counter.most_common(args.top), result.get("total_results", 0), args.group_by, note)
        return

    fields = None if args.fields == "" else args.fields
    result = gl.search(query, frm, to, args.stream, args.limit, fields)
    if args.raw:
        print(json.dumps(result))
        return
    print_messages(result, full=args.fields == "", with_service=bool(args.trace))


def cmd_whoami(gl: Graylog, _args: argparse.Namespace) -> None:
    resp = gl.check(gl.request("GET", f"/users/{quote(gl.current_username())}"))
    user = resp.json()
    keys = ("id", "username", "full_name", "email", "roles", "read_only", "permissions")
    print(json.dumps({key: user.get(key) for key in keys}, indent=2))


def cmd_list_tokens(gl: Graylog, _args: argparse.Namespace) -> None:
    resp = gl.check(gl.request("GET", f"/users/{gl.current_user_id()}/tokens"))
    for token in resp.json().get("tokens", []):
        print(f"{token.get('name')}\t{token.get('last_access')}\t{token.get('id')}")


def cmd_create_token(gl: Graylog, args: argparse.Namespace) -> None:
    resp = gl.check(gl.request("POST", f"/users/{gl.current_user_id()}/tokens/{quote(args.create_token)}", body={}))
    token = resp.json().get("token")
    if not token:
        raise GraylogError(f"No token in the response: {resp.body[:300]}")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    token_file = gl.creds.token_file
    fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(token)
    os.chmod(token_file, 0o600)
    print(f"Token '{args.create_token}' created and saved to {token_file}")
    print(f"You can delete {gl.creds.cred_file} now if you prefer not to keep the password on disk.")


def cmd_diagnose(gl: Graylog, args: argparse.Namespace) -> None:
    creds = gl.creds
    print(f"host:      {gl.host}")
    print(f"auth file: {creds.kind}")
    print(f"username:  {creds.login_user or '<token>'}")
    resp = gl.request("GET", f"/users/{quote(creds.login_user or 'x')}")
    print(f"  basic auth  GET /users/<user>    -> HTTP {resp.status}")
    if creds.login_user:
        resp = gl.session_login()
        verdict = f"OK, user='{gl.username}'" if creds.password == "session" else "rejected"
        print(f"  session     POST /system/sessions -> HTTP {resp.status}  ({verdict})")
    if args.stream:
        resp = gl.request("GET", f"/streams/{args.stream}")
        print(f"  stream read GET /streams/{args.stream} -> HTTP {resp.status}")
    else:
        resp = gl.request("GET", "/streams")
        print(f"  streams     GET /streams           -> HTTP {resp.status}  (no default stream set)")


# --------------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------------

EXAMPLES = """\
examples (with GRAYLOG_HOST=graylog.example.com exported):
  graylog-search --since 2h 'application:"order-service" AND level:<=4'
  graylog-search -f 2026-09-01T00:00:00.000Z -t 2026-09-02T00:00:00.000Z -l 50 '"3f2b8c1e-0000-4000-8000-000000000001"'
  graylog-search --since 1d --group-by SourceSimpleClassName 'application:"payment-service" AND level:<=4'
  graylog-search --since 6h --trace 6f1c2a9e0b7d4c3a
  graylog-search -H graylog-dev.example.com -s 0123456789abcdef01234567 --since 1h 'application:"order-service"'
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graylog-search",
        description="Search Graylog from the command line.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", nargs="?", help="Lucene query, the same string as the Graylog search bar")

    window = parser.add_argument_group("time window (default: last 24 hours)")
    window.add_argument("-f", "--from", dest="from_ts", metavar="TS", help="ISO-8601 UTC start, e.g. 2026-09-01T00:00:00.000Z")
    window.add_argument("-t", "--to", dest="to_ts", metavar="TS", help="ISO-8601 UTC end (default: now)")
    window.add_argument("--since", metavar="AGE", help="relative window ending now: 30m, 2h, 3d, 1w")

    where = parser.add_argument_group("where to search")
    where.add_argument("-H", "--host", help="Graylog host (default: $GRAYLOG_HOST)")
    where.add_argument("-s", "--stream", default=os.environ.get("GRAYLOG_STREAM") or None,
                       help="stream id (default: $GRAYLOG_STREAM, or all streams you can read)")

    output = parser.add_argument_group("output")
    output.add_argument("-l", "--limit", type=int, default=DEFAULT_LIMIT, help=f"max messages (default {DEFAULT_LIMIT})")
    output.add_argument("-F", "--fields", default=DEFAULT_FIELDS,
                        help="with a value: 'time [logger] message' lines; with '' the full key=value dump")
    output.add_argument("-r", "--raw", action="store_true", help="print the raw JSON response")
    output.add_argument("--group-by", metavar="FIELD",
                        help="count hits per value of FIELD (e.g. application, SourceSimpleClassName, level)")
    output.add_argument("--top", type=int, default=25, help="with --group-by: how many values to show (default 25)")
    output.add_argument("--trace", metavar="ID",
                        help="follow one trace id (or any id) across all services; the query, if given, narrows it")

    account = parser.add_argument_group("account")
    account.add_argument("--create-token", nargs="?", const=DEFAULT_TOKEN_NAME, metavar="NAME",
                         help=f"mint an API token from your user/password (default name {DEFAULT_TOKEN_NAME})")
    account.add_argument("--list-tokens", action="store_true", help="show the tokens on your account")
    account.add_argument("--whoami", action="store_true", help="verify credentials and show your account")
    account.add_argument("--diagnose", action="store_true", help="test each auth path, report status codes only")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        host = resolve_host(args.host)
        gl = Graylog(host, Credentials(host))
        if args.diagnose:
            cmd_diagnose(gl, args)
            return 0
        gl.ensure_auth()
        if args.whoami:
            cmd_whoami(gl, args)
        elif args.list_tokens:
            cmd_list_tokens(gl, args)
        elif args.create_token:
            cmd_create_token(gl, args)
        else:
            cmd_search(gl, args)
        return 0
    except GraylogError as err:
        print(err, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
