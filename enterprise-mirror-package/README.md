# Enterprise Mirror: starter package for Claude Code

Everything produced during design, ready to place at the root of a new repository.

## Contents

| Path | What it is |
| --- | --- |
| `CLAUDE.md` | Orientation and working rules. Keep it at the repository root |
| `docs/build-spec.md` | What to build, in what order, with acceptance criteria. The authority |
| `docs/product-spec.md` | Why: the product, its principles, risks and roadmap |
| `docs/decisions/` | Architecture decision records, starting with platform support (0001 to 0006) |
| `docs/platforms.md` | Supported hosts, prerequisites, measured footprint and the verification log |
| `docs/platforms/windows-verification.md` | What must pass on a real Windows machine before Windows leaves experimental |
| `docs/open-source/go-public.md` | Everything that must be done before the repository becomes public |
| `docs/tells.md` | Every way found for an agent to tell it is in a test, and how each was closed |
| `docs/architecture.png` | Architecture diagram from the product spec (two box labels have since been renamed: "Capture and redaction" is now "Discovery crawler", and the twin factory "builds locally from specs") |
| `design/` | Source of the 17 command-line and portal artboards, with a guide |
| `catalog/apps.csv` | 500 candidate enterprise apps: tier, name, category. Unverified |
| `catalog/backlog.csv` | About 290 further candidates |

## How to start

1. Create an empty repository and copy this folder's contents into it.
2. Open it with Claude Code and give it the kickoff message below.
3. Answer the open decisions it raises (listed at the end of the build spec) before it starts M1.

### Kickoff message

> Read CLAUDE.md, then docs/build-spec.md in full, then skim docs/product-spec.md and design/README.md. Before writing code: (1) list the open decisions at the end of the build spec that you need answered, (2) list anything in the specs that is contradictory or underspecified for milestone M0, and (3) propose a short plan for M0. Wait for my answers. Then build M0 only and show each acceptance criterion passing.

## Milestones

| # | Name | Result |
| --- | --- | --- |
| M0 | Scaffold | Package, CLI skeleton, schemas, CI on macOS, Windows and Linux, open-source readiness |
| M0.5 | Engine | The mirror-managed Linux VM on every host, hardened, with gVisor |
| M1 | Sealed network | DNS, gateway, certificates, three networks, egress and inside-out suites |
| M2 | Twins | Gitea and Mattermost behind adapters, with profiles and rules |
| M3 | World and reset | Seeded company, world definition and creation, snapshot, catalog index |
| M4 | Agent access | Hosted and browser modes, onboarding, model routes |
| M5 | Runner and evaluator | Ten scenarios, checks, coverage, touch ledger |
| M6 | Timeline and report | Trace, HTML report, documentation |
| M7 | Portal | Seven screens, live view, wizards |
| M8 | World import | Common draft, review, two importers |
| M9 | Devices | Sites, four device types, REST platform and broker |

The prototype exit gate follows M6. M7 to M9 extend it.

## Where the specs disagree, and which wins

The specs grew over many rounds. Later sections refined earlier ones without every earlier passage being rewritten. When two passages conflict, the rule is: **the build spec wins over the product spec, and within the build spec the more specific, later-written section wins.** Known cases:

- **Networks.** "Sealed network" opens with the corrected three-network design, and "Complete coverage and hidden machinery" has the full table. Any remaining mention of a single internal network is superseded.
- **Model endpoints.** The `models:` block in "How an agent enters the world" replaces the flat `model_endpoints` list. The example in "File formats" has been updated; treat `models:` as canonical everywhere.
- **Twin adapter.** The protocol in "Twins and world seed" predates three methods added later: `locate`, `describe` and `exposed`. They are required, and are generated from the system profile described in "Systems: preconfigured inputs and outputs".
- **Manifest shape.** "File formats" shows the early manifest. "World definition and creation" adds `industry`, `tidiness`, `kind`, `links` and `data`; "Systems" adds `settings`, `data` and `rules` per app; "Physical objects" adds `sites` and `devices`. The full schema is the union.
- **Project states.** "Service layer and project states" lists five states; "World definition and creation" lists six world states that extend them. Implement one state model covering both.
- **Commands.** `mirror init`, `plan`, `build` and `up` remain, wrapped by `mirror world new` and `mirror world create`. The "Command line" table predates `world`, `system`, `catalog`, `watch`, `touched` and `agent new/check`; the complete command set is the union of all command tables.
- **Scope statement.** "Purpose and scope" describes the prototype through M6. The portal, import and devices were added afterward as M7 to M9.
- **Exit codes.** `mirror run` exit code 4 also covers `coverage: incomplete`, as stated in "Complete coverage".
- **Import start.** The "Three ways to start" table and the "World import" section agree that import is M8; the wizard artboard shows it as available.
- **Platforms.** The section "Platforms and the engine" and `docs/decisions/0001` to `0006` replace every earlier statement that the prototype runs on one Linux machine or that macOS and Windows are development-only at reduced isolation. Wherever the spec says "the host" for running containers, read "the engine".
- **Product spec terms.** The product spec says "library twin" in places where the decision is now "catalog specification built locally". It also describes the discovery crawler, drift detection, SSO and remote agents, none of which are in the build spec's milestones.

Ask before resolving any conflict not listed here.

## Things to verify before relying on them

- Tool behavior named in the build spec (mitmproxy modes, gVisor runtime monitoring, CoreDNS, Docker internal networks, host access to an internal bridge) was not checked against current documentation.
- Engine assumptions, each listed under "To verify" in its decision record: Lima's settings for no mounts and socket-only forwarding, Rosetta for amd64 images, gVisor under WSL2 (undocumented), Docker API streaming across the VM boundary within the two-second event budget. Results go in `docs/platforms.md`.
- Logging blocked connection attempts on a network with no route out is an open design problem; the spec suggests a sinkhole.
- Gitea and Mattermost licenses for this use.
- Provider hostnames and authentication for model routes.
- Every row of the app catalog.
- The design artboards were never viewed rendered by their author.

## Decisions still open

See "Open decisions for the owner" at the end of the build spec: stack confirmation, first twins, project and command name, license, default model hosts, reviewers, a Windows machine for verification, and disk for the engine. Also: DCO or CLA, the project's commit email, and whether to keep history at publication. Supported platforms were decided on 2026-11-22.
