# Governance

## Who decides

MirrorDimensions is maintained by Supercomplicated LLC. The maintainers listed in [MAINTAINERS.md](MAINTAINERS.md) review and merge pull requests. Every pull request needs approval from a code owner (see `.github/CODEOWNERS`) and passing CI.

Architecture and design decisions are recorded in [docs/decisions/](docs/decisions/). A decision is proposed in a pull request, discussed there, and accepted by a maintainer. Changing an accepted decision needs a new record that supersedes it.

## Commitments

- **The licence stays open.** The project is licensed under Apache-2.0 and will not be relicensed under more restrictive terms. Contributions are accepted under the Developer Certificate of Origin, with no contributor licence agreement, so no one can relicense your work.
- **Self-hosting is complete.** Everything a team needs to run the test range itself, and to trust its results, is in this repository. Nothing that decides whether an agent passed, or whether a run was isolated and fully captured, is held back.
- **No telemetry.** The project collects no usage data.

## Commercial service

Supercomplicated LLC also offers a commercial hosted service built on this project. Its code lives in a separate repository that depends on this one; this repository never depends on it. Improvements the service needs in the core are made here, in the open.

## Becoming a maintainer

Sustained, high-quality contributions and reviews, especially in isolation, capture and detection research, lead to an invitation from the existing maintainers.
