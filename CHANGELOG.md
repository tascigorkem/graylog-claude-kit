# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). Versions before 1.0.0 may still change the
command-line interface between minor versions.

## [Unreleased]

## [0.1.0] - 2026-11-09

First public release.

### Added

- `graylog-search` CLI: a standard-library Python (3.9+) client for Graylog 4.x and newer.
  - Relative time windows with `--since 30m|2h|3d|1w`, or absolute `-f`/`-t` timestamps.
  - Server-side counts over all hits with `--group-by FIELD [--top N]`, through the Views
    search API, with a fallback to counting fetched messages.
  - Cross-service request tracing with `--trace ID`.
  - Token and password authentication, including the session-login fallback, `--create-token`,
    `--list-tokens`, `--whoami`, `--diagnose` and `--version`.
  - Configuration through flags and `GRAYLOG_HOST`, `GRAYLOG_STREAM`, `GRAYLOG_TOKEN`,
    `GRAYLOG_CONFIG_DIR` and `GRAYLOG_TRACE_FIELDS`.
- `graylog` Claude Code skill that teaches Claude how to query Graylog well.
- `graylog-investigator` Claude Code subagent for read-only, multi-query investigations that
  return a short report.
- Packaging as the `graylog-search` plugin in the `tascigorkem` marketplace.

[Unreleased]: https://github.com/tascigorkem/graylog-claude-kit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/tascigorkem/graylog-claude-kit/releases/tag/v0.1.0
