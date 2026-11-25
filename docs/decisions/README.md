# Decision records

Some numbers are not published here: they record business decisions kept outside the repository.

Each file records one architecture or design decision: the context, what was decided, what it costs, and what must be verified before relying on it. Number them in order; never renumber. A decision that is replaced keeps its file and is marked `Superseded by NNNN`.

**Status values**

- `Accepted (owner)`: decided by the project owner.
- `Accepted`: follows directly from an owner decision.
- `Proposed`: a design choice made while writing the spec. Open to review; becomes `Accepted` when its milestone is accepted.

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-platform-support.md) | macOS, Windows and Linux are supported with equal guarantees | Accepted (owner) |
| [0002](0002-managed-engine-vm.md) | All containers run in a mirror-managed Linux VM, the engine | Accepted (owner) |
| [0003](0003-control-plane-on-host.md) | The control plane runs natively on the host; everything crosses into the engine through the Docker API | Accepted (owner), details Proposed |
| [0004](0004-engine-hardening.md) | The engine shares nothing with the host and cannot reach it | Proposed |
| [0005](0005-cpu-architecture.md) | arm64 engines on Apple Silicon; emulation allowed for twins, not for agents | Proposed |
| [0006](0006-testing-on-available-hardware.md) | How each platform is tested with only a Mac available | Accepted (owner), details Proposed |
| [0007](0007-open-source-practices.md) | Built private, ready to publish: open-source practices from M0 | Proposed, adopted into M0 by the owner; licence Accepted (owner) |
| [0009](0009-mcp-servers.md) | Two MCP servers: one inside the world for agents, one outside it for operators | Accepted (owner) for both; details Proposed |
| [0010](0010-agent-runtime.md) | Agents run as hardened containers in the dedicated engine VM; gVisor becomes opt-in | Accepted (owner) |
| [0011](0011-sealed-network-mechanisms.md) | How the sealed network is built: mechanisms that differ from the spec | Proposed |
| [0012](0012-firecracker-microvm-option.md) | Firecracker microVMs for agents on hosts that can nest (Apple M3+, nested KVM) | Accepted (owner) for building; details Proposed |
| [0013](0013-model-gateway.md) | The model gateway: one pinned upstream per route, real credential added at the gateway | Proposed |
| [0014](0014-managed-browser.md) | The managed browser: an observer that shares the browser's network namespace | Proposed |
| [0015](0015-runner.md) | How a run works: mechanisms that differ from the spec | Proposed |
| [0016](0016-coverage-tracer.md) | Coverage inside the agent's container: Tetragon in the engine, connections instead of byte counts | Proposed |
| [0017](0017-portal.md) | The portal: a local server on the service layer, a React front end shipped inside the package, a token kept in a cookie | Accepted (owner) |
| [0018](0018-live-view.md) | The live view: locations recorded by the gateway at capture, steps sent as they open and again as they change | Proposed |
| [0020](0020-exact-grants.md) | Grants are exact: for a run, the person has only what the agent file grants; a run checks it can reach its work | Accepted (owner) |
| [0019](0019-engine-updates.md) | The engine installs updates only when asked (`mirror engine update`); doctor notes when they are over 14 days old | Accepted (owner) |

Template:

```markdown
# NNNN. Title

Status: Proposed · Date: YYYY-MM-DD · Milestone: Mn

## Context
## Decision
## Consequences
## Alternatives considered
## To verify
```
