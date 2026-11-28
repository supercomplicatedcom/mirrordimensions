# CLAUDE.md

MirrorDimensions: an open-source, self-hosted test range where AI agents work inside a synthetic company and its systems, sealed from the real world, with everything they touch recorded and scored.

## Read first

The specs are kept outside this repository, in the owner's local folder `enterprise-mirror-package/` (git ignores it). If it is present:

1. `enterprise-mirror-package/docs/build-spec.md` is the authority on what to build and in what order. Start at "Purpose and scope", then "Milestones".
2. `enterprise-mirror-package/docs/product-spec.md` explains why. Read it for intent.
3. `enterprise-mirror-package/design/` holds the intended command-line output and portal screens; `catalog/apps.csv` there seeds the app catalog.
4. `enterprise-mirror-package/README.md` lists where the two specs disagree and which wins.

In the repository:

5. `docs/decisions/` holds the architecture decisions; `docs/platforms.md` holds what has been measured and verified on each host; `docs/tells.md` lists every tell found.
6. `CONTRIBUTING.md` has the commands to run before pushing.

Never copy material from `enterprise-mirror-package/` into the repository without the owner's say-so: parts of it are private.

The mirror runs on macOS (Apple Silicon), Windows 11 x64 and Linux x64 with the same design and the same checks. All containers run in a mirror-managed Linux VM, the engine; the control plane runs natively on the host. See `docs/decisions/0001` to `0006`.

Work one milestone at a time, in the order M0, M0.5, M1 to M7, M7.5, M8, M9. Do not start a milestone until the one before it is accepted.

## Three design goals that outrank convenience

- **Isolation.** Nothing leaves the sandbox except calls to the configured model endpoint.
- **Complete coverage.** Every way the agent can touch something is captured or does not exist.
- **The agent must not know.** Nothing it can see reveals a test, and nothing that builds, runs or scores the world is reachable from inside it.

## Working rules

**Safety**

- Never point any code at a real organization's systems. All development and tests run against the local sandbox only. The discovery crawler is out of scope; do not start it.
- Never weaken isolation to make something work. If a twin or tool needs the internet at runtime, stop and raise it. Image pulls and package installs happen at setup or build time, on the host or in the engine's own network namespace, never from inside the sandbox.
- Never commit secrets, the root CA key, `.mirror/` directories or real data. Generated worlds are synthetic; keep them that way.
- Do not copy vendor logos, trademarks or proprietary assets into the repository. The two twins run their upstream open-source software unmodified apart from configuration.
- Attack content in scenarios targets only the synthetic company. Write realistic injected text, but no working malware, exploit code or real credentials.

**The agent must not know**

- Before merging anything the agent can observe, ask: would this exist in a real company's environment? If not, remove or disguise it.
- No forbidden strings in agent-visible names (see Sealed network). The naming lint is the enforcement; extend its list when a new tell is found.
- No placeholder content: no "lorem ipsum", "foo", "test user", "example" in generated data.
- Record each tell found during development in `docs/tells.md` with how it was closed.

* Never place code, configuration or data from this repository or a mirror project inside a container the agent can reach, and never give such a container a network path to the control plane.
* A new way for the agent to touch something is not done until it is captured, appears in the coverage section, and has a reconciliation test.

**Platforms**

- Every host gets the same protections. Never add a code path that is weaker on one OS without reporting it in the result's `platform` block and in `docs/platforms.md`.
- OS-specific code lives only in `src/mirrordimensions/hostos/` and `src/mirrordimensions/engine/`. Nothing else checks which OS it runs on.
- Never share a host folder with the engine, publish a twin port to the host, or give any container a route to the host. Everything crosses through the Docker API.
- Never use or change the user's own Docker context, Lima instances or global WSL settings.
- Write generated text as UTF-8 with `\n`, keep names unique ignoring case, and use the portable helpers for permissions and locks.
- Record every measurement and every verified or failed platform assumption in `docs/platforms.md`.

**Open source**

- Cloud-service code never goes in this repository, and open code never imports it. A feature belongs here if a single team self-hosting needs it for a trustworthy result (see GOVERNANCE.md).
- Everything committed must be publishable: no secrets, real data, personal details or links only the owner can open. The repository will become public with its history (decision 0007, `docs/open-source/go-public.md`).
- Sign off every commit (DCO). Every new source file gets an SPDX licence header.
- Do not add a dependency whose licence is not compatible with Apache-2.0 without a decision record.
- A sandbox escape, egress bypass or capture gap is a vulnerability: do not describe it in a public issue, commit message or pull request title. Tells are public and go in `docs/tells.md`.

**Engineering**

- Before pushing, run the checks in `CONTRIBUTING.md`: ruff, pyright strict, pytest, and the import, SPDX and licence scripts.

- Work milestone by milestone. At the start of each, write a short plan in the pull request description; at the end, show each acceptance criterion passing.
- Verify tools against their current documentation before relying on an API or flag. Where this spec names a mechanism that turns out not to work as described, write a brief design note in `docs/decisions/` with the alternative and proceed with the option that best preserves isolation and undetectability.
- Prefer small modules with typed interfaces. All product-specific code lives under `twins/<product>/`; nothing outside it may import a product by name.
- Determinism: no wall-clock time or unseeded randomness in the world generator, state dumps or evaluator.
- Add a dependency only when it removes real work; record the reason in the pull request.
- Errors must be actionable. No bare exceptions reaching the user.
- Keep `README.md` and `docs/` accurate in the same pull request as the change.

**When to stop and ask**

- A decision in the Decisions table needs to change
- An acceptance criterion cannot be met as written
- Anything would require outbound network access from the sandbox beyond the model gateway
- A licensing question about bundling or configuring a twin's software
