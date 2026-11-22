# CLAUDE.md

Enterprise Mirror: an open-source, self-hosted test range where AI agents work inside a synthetic company and its systems, sealed from the real world, with everything they touch recorded and scored.

## Read first

1. `docs/build-spec.md` is the authority on what to build and in what order. Start at "Purpose and scope", then "Milestones".
2. `docs/product-spec.md` explains why. Read it for intent.
3. `design/` holds the intended command-line output and portal screens.
4. `catalog/apps.csv` is the seed for the app catalog.
5. `README.md` lists where the two specs disagree and which wins.

Work one milestone at a time, M0 first. Do not start a milestone until the one before it is accepted.

## Three guarantees that outrank convenience

- **Isolation.** Nothing leaves the sandbox except calls to the configured model endpoint.
- **Complete coverage.** Every way the agent can touch something is captured or does not exist.
- **The agent must not know.** Nothing it can see reveals a test, and nothing that builds, runs or scores the world is reachable from inside it.

## Working rules

**Safety**

- Never point any code at a real organization's systems. All development and tests run against the local sandbox only. The discovery crawler is out of scope; do not start it.
- Never weaken isolation to make something work. If a twin or tool needs the internet at runtime, stop and raise it. Image pulls and package installs happen at build time on the host, never from inside the sandbox.
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

**Engineering**

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
