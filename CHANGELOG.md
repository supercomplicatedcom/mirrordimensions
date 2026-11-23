# Changelog

All notable changes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- M0.5 engine: `mirror engine setup|start|stop|status|destroy|check|shell`. A Lima driver for macOS and Linux (pinned and checksum-verified, private `LIMA_HOME`, no host shares, only the Docker socket forwarded), an opt-in host driver for Linux, and an experimental Windows driver (configuration only). The guest is Ubuntu 26.04 with Docker Engine, gVisor and an edge firewall that blocks container traffic to the host and all egress except allow-listed pairs.
- Keep-awake during long operations, and sleep detection.

- M0 scaffold: the `mirrordimensions` package and the `mirror` command (`init`, `validate`, `schema`, `status`).
- Typed file formats for the manifest, agent files, scenarios, run events and results, with JSON Schema.
- `mirror init`: a starter project with a generated company and a per-install root CA.
- Host portability helpers: UTF-8 with `\n` line endings, owner-only files on POSIX and Windows, a portable project lock.
- Plug-in points loaded as entry points.
- CI on Linux, macOS and Windows; secret scanning, licence, SPDX, import-boundary and DCO checks.
- Repository files: licence, notice, security policy, contributing guide, code of conduct, governance, trademark policy.
