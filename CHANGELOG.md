# Changelog

All notable changes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- M0 scaffold: the `mirrordimensions` package and the `mirror` command (`init`, `validate`, `schema`, `status`).
- Typed file formats for the manifest, agent files, scenarios, run events and results, with JSON Schema.
- `mirror init`: a starter project with a generated company and a per-install root CA.
- Host portability helpers: UTF-8 with `\n` line endings, owner-only files on POSIX and Windows, a portable project lock.
- Plug-in points loaded as entry points.
- CI on Linux, macOS and Windows; secret scanning, licence, SPDX, import-boundary and DCO checks.
- Repository files: licence, notice, security policy, contributing guide, code of conduct, governance, trademark policy.
