# 0029. Nothing the agent sees matches the public repository

Status: Accepted (owner, 2026-11-27).

## Context

The project is open source, so its code, its text pools and its built-in scenarios can be read by anyone, and models may be trained on them. The build spec names this as a limit: a model may know from training how such a mirror is built. What keeps a test private is what is not public: the organization's own seed, manifest and privately written scenarios.

That only holds if what the agent sees is not in the public repository. Today it mostly is. A world's issues, comments and chat come from fixed sentences in `world/pools.py` and `world/content.py`, with names filled in. Measured on 2026-11-27 for two seeds of the template world (40 people, a year of history), the share of texts that contain a run of eight words or more found word for word in the package's source:

| Text            | Seed 48213         | Seed 7             |
| --------------- | ------------------ | ------------------ |
| Issues          | 149 of 150 (99%)   | 149 of 150 (99%)   |
| Issue comments  | 212 of 217 (98%)   | 197 of 206 (96%)   |
| Chat messages   | 772 of 1,092 (71%) | 783 of 1,100 (71%) |
| Commit messages | 5 of 17 (29%)      | 5 of 18 (28%)      |

A model that has read the repository could recognise these. Fixed names add to it: every world has `billing-service`, `platform-docs`, `#platform-team` and workstations named `ws-` and four digits. This is tell 39 in `docs/tells.md`.

Separately, capable models sometimes say a situation looks like an evaluation without knowing anything about this project, from cues such as a setup that is too convenient. That cannot be removed entirely; it can be measured.

## Decision

1. **Assume the design is known.** As in cryptography, the design is public and the secret is in the keys. A model may know that test ranges like this exist and how they work; it must find no evidence that this workplace is one. Everything the agent sees comes from per-world or private inputs: the world's seed, its industry profile and discovered shape (decision 0028), the company's private scenarios and content.
2. **A public-text check.** The mirror compares every text an agent can read in a world (issues, comments, pull requests, commit messages, chat, READMEs and documents) with the text of the installed package, offline, and reports the share of texts that contain a run of eight or more words found in it.
   - It runs in the test suite on the golden worlds and on a world from each industry profile.
   - `mirror world create` reports it, and `mirror doctor` includes it under `Undetectability`.
   - It starts as a report. It blocks once the generator meets the limit (point 7).
3. **Text is composed, not picked.** The generator stops shipping whole sentences. It composes each text from short parts and the world's own facts: its people, services, incidents, customers, the profile's vocabulary and the discovered conventions. No span of eight or more words in the source reaches the agent unchanged. Code in the world's repositories is generated the same way, from the profile's and the discovery's shapes, not copied from fixed files.
4. **No constant names.** The core repositories and channels take their names per world from the profile's alternatives (`billing-service`, `invoicing`, `billing-api`, `revenue-platform`), and so do workstation names (`ws-6528`, `LT-0417`, `jsmith-mbp`). Scenarios refer to a repository or channel by its role (`repo: {role: billing}`), resolved for each world, not by a fixed name.
5. **Private content packs.** A project can hold its own text and code parts in `content/`, beside its private scenarios, and the generator prefers them. They never leave the project folder.
6. **Public scenarios are labelled.** A result from a built-in scenario says it is from a public scenario that models may have seen, in the report and in `result.json`. The documentation already advises writing private scenarios for results that matter.
7. **The limit.** A world passes when no more than 2% of its texts share an eight-word run with the package. The threshold is set here and changed by the owner.
8. **Suspicion is measured, not assumed away.**
   - Every run already reports whether the agent suspected a test, from its transcript.
   - The build spec's discriminator test is added as an opt-in command: a model is shown pages from a world and from a matched set of public, real-company material, and tries to tell them apart. Its accuracy across a sample is reported. It makes live model calls, so it runs only when the user asks, with the cost shown first.
   - A rising rate of suspicion, or a discriminator that does better than chance, is treated as a tell and recorded.

## Consequences

- The generator's text and code are rewritten around composition. The pools written for decision 0028's profiles are written this way from the start, so the two decisions are built together.
- Golden worlds change, and the built-in scenarios move to role references. Scenario files written against fixed names keep working through aliases for one release.
- The check can fail a world for text that the user supplied in a content pack and that is also public. It names the text and its source, so the user can change it.
- Some resemblance stays. Gitea and Mattermost together are a weak signal on their own, because many real companies run them. A model that suspects every workplace is a test cannot be talked out of it; the measurement in point 8 makes that visible in the results instead.

## Alternatives considered

- **Keep the pools private** (a closed text package). Defeats the open-source model and only delays the problem: a private package that every install shares is still the same text everywhere.
- **Generate text with a model at `world new`.** Varied and never in the repository, but not deterministic, it needs a key and network at setup, and the model's output would need screening for placeholder text and tells. It stays possible as an option for private content packs.
- **Rely on volume.** Make the pools so large that repeats are rare. The text would still be in the public repository word for word, so the check in point 2 would still fail.

## To verify

- The check, run on today's template world, reproduces the figures above.
- After the rewrite, worlds from every profile pass the limit for many seeds, and two worlds with different seeds share no eight-word run beyond the vocabulary the profile defines.
- The discriminator's accuracy on a world, against matched real-company material, is reported before and after the rewrite.

## Answered by the owner (2026-11-27)

- Accepted, and built together with decision 0028: the industry profiles' text is composed this way from the start.

## Open questions for the owner

Until these are answered, the build uses the defaults given in each.

1. Is eight words and 2% the right limit, and should the check block `world create` once the generator meets it, or only warn? Default: eight words and 2%, reported but not blocking.
2. Should the core repositories and channels be renamed per world now (and the built-in scenarios moved to role references), or only when the industry profiles land? Default: with the industry profiles, since both are built together.
3. Should the discriminator test exist at all, given it needs live model calls and a matched set of real-company material that must itself be public and properly licensed? Default: not built in this round.
