# Security policy

MirrorDimensions is a containment product: its job is to keep an AI agent inside a sealed world and to record everything it does. A failure of that job is a security vulnerability, even if no data was lost.

## What to report privately

- **Sandbox escape:** code or an agent inside a world reaching the engine, the host, or another world.
- **Egress bypass:** any packet leaving a world other than to a configured model route, including through DNS, a twin's URL-fetching features, or a model provider's hosted tools.
- **Capture gap:** anything an agent can do that is not recorded, or a run marked `coverage: complete` that missed something.
- **Hidden machinery exposed:** any path from a world to the control plane, the portal, the operator MCP server, project files, scenarios, canaries or the root CA key.
- **Credential exposure:** a real credential reaching a world, a capture or a report.

Report these through **GitHub private vulnerability reporting**: on the repository, open *Security → Report a vulnerability*. Do not open a public issue, pull request or discussion, and do not include details in a commit message.

## What to report publicly

**Tells:** ways an agent could notice it is in a test (a revealing hostname, header, error page, timing or data pattern). They are not vulnerabilities. Open a public issue with the *Tell* template; each one is recorded in [docs/tells.md](docs/tells.md).

## What happens next

- We acknowledge a report within **3 working days**.
- We aim to fix or mitigate within **90 days**, and agree a disclosure date with you.
- We credit reporters in the release notes unless you ask us not to.

## Supported versions

Pre-alpha: only the latest commit on `main` is supported.

## Acceptable use

Injection and permission scenarios target synthetic companies only. Do not use this project to attack systems you do not own or are not authorized to test. Contributions must not contain working malware, exploit code or real credentials.
