# Changelog

All notable changes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Agents run as hardened ordinary containers in the engine VM; gVisor is opt-in (decision 0010).

### Added

- M2, part 2: profiles for Gitea (39 surfaces) and Mattermost (18), from which `locate`, `describe` and `exposed` are generated; a behaviour engine shared by the gateway and the host that implements every rule action (require, forbid, set and rename fields; body size limits; delays; failure rates; rate limits; field edits; planted text; page size; fixed responses) with deterministic randomness and the products' own error pages; `mirror system list|show|rules|try`, `mirror set rule`, `mirror unset rule`; rules checked by `mirror validate`.
- M2, part 1: Gitea 28.4 and Mattermost Team Edition 12.1 replace the stub servers, each with its own PostgreSQL, configured like a long-lived corporate install with no first-run screens. A control relay on the system network carries administration over Docker exec; the system network has its own resolver; per-install secrets are kept owner-only. Identities are issued with grants and production-style credentials. State dumps are deterministic. WebSocket frames are captured; Git runs over HTTPS only. Doctor now checks that a twin's own URL-fetching feature cannot get out.
- `mirror engine setup --microvm`: an optional Firecracker microVM runtime for agents (Kata Containers 4.4 with Firecracker 1.17, devmapper thin pool) on hosts that can nest: Apple M3 or later with macOS 15+, or Linux with nested KVM. Refuses on other hosts, naming why (decision 0012).
- M1 sealed network: `mirror up`, `mirror down`, `mirror doctor`. Three networks; a CoreDNS resolver that never forwards; a mitmproxy gateway that routes by hostname, refuses unknown names without a certificate, captures each exchange with redaction, and presents ordinary nginx error pages; per-hostname certificates minted on the host; the engine firewall as the sinkhole, with drops turned into `egress.blocked` events.

- M0.5 engine: `mirror engine setup|start|stop|status|destroy|check|shell`. A Lima driver for macOS and Linux (pinned and checksum-verified, private `LIMA_HOME`, no host shares, only the Docker socket forwarded), an opt-in host driver for Linux, and an experimental Windows driver (configuration only). The guest is Ubuntu 26.04 with Docker Engine, gVisor and an edge firewall that blocks container traffic to the host and all egress except allow-listed pairs.
- Keep-awake during long operations, and sleep detection.

- M0 scaffold: the `mirrordimensions` package and the `mirror` command (`init`, `validate`, `schema`, `status`).
- Typed file formats for the manifest, agent files, scenarios, run events and results, with JSON Schema.
- `mirror init`: a starter project with a generated company and a per-install root CA.
- Host portability helpers: UTF-8 with `\n` line endings, owner-only files on POSIX and Windows, a portable project lock.
- Plug-in points loaded as entry points.
- CI on Linux, macOS and Windows; secret scanning, licence, SPDX, import-boundary and DCO checks.
- Repository files: licence, notice, security policy, contributing guide, code of conduct, governance, trademark policy.
