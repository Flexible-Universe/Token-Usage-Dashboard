# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning according to [SemVer](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-09-14

### Added

- AGPL-3.0 license, including license headers and a source code offer in the
  user interface.
- Sample data generator (`tools/make-sample-data.py`), for a demonstration
  without usage data of your own.
- Smoke test across the whole read path, and a schema comparison against real
  files.
- Export chain in the repository under `export/`, with launchd templates.
- `CONTRIBUTING.md`, `SECURITY.md`, and a GitLab CI test pipeline that mirrors
  successful changes from `develop` to GitHub.
- `install.sh` sets up the data directory, the export scripts and, on request,
  the four launchd runs (`--with-launchagents`, `--dry-run`, `--force`).

### Changed

- Chart.js ships with the repository instead of being loaded from a CDN; the
  application runs offline.
- The default data directory is `~/Library/Application Support/Claude-Code-Usage`.
- `config.toml` is no longer under version control; `config.example.toml`
  takes its place.
- The reference tests read their data directory from
  `TOKEN_DASHBOARD_REAL_DATA` and skip themselves without that variable.
- README and documentation are in English; the user interface supports German
  and English with a persistent language switcher.

[Unreleased]: https://github.com/Flexible-Universe/Token-Usage-Dashboard/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Flexible-Universe/Token-Usage-Dashboard/releases/tag/v1.0.0
