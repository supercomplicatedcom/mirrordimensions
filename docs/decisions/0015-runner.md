# 0015. How a run works: mechanisms that differ from the spec

Status: Proposed · Date: 2026-11-24 · Milestone: M5

## Context

The build spec describes the run lifecycle, the scenario vocabulary and the evaluator ("Agents, scenarios and evaluation"). Building them against the twins surfaced places where the spec's order or wording does not work as written, or leaves the mechanism open.

## Decision

1. **The starting state is taken after delivery.** The spec takes the pre-run dump at step 5 and delivers the work at step 7. The delivery is the runner's own change, and with the dump first it would have to be explained away in every side-effect comparison and reconciliation. The runner therefore delivers first, then dumps, then starts the agent. A command-woken agent is started only after both, so it cannot act before the dump. A polling agent finds the work already waiting, as one that was "already watching" would.
2. **Scenarios are package data.** The ten built-in scenarios live in `mirrordimensions/scenarios/core/`, not at the repository root, so an installed `mirror` finds them. A project still adds its own in `scenarios/*.yaml`, and they may replace a built-in one by id.
3. **Operations belong to twins.** Each twin adapter registers its scenario vocabulary: overlays, deliveries and checks (`Twin.operations()`). It also lists its state as individual objects with a scope (`Twin.state_objects()`), which `side_effects.allow` matches against: `- gitea: {repo: billing-service}`. The runner names no product.
4. **People act as themselves.**
   - Gitea overlays act through the administrator with `Sudo`, as seeding does, and backdate the activity feed as seeding does.
   - Mattermost overlays and deliveries sign in with the person's password and post through the API, so a delivered message raises the same notifications and live events a colleague's would. Bulk import, which seeding uses, does not.
5. **Assigned work comes from someone who can assign.** Gitea silently drops assignees set by someone without write access. A delivery picks the first person matching `from` who has write access. If none does (in the generated company, only collaborators do), the sender opens the issue mentioning the person by name, and the person's own account takes the issue. *Follow-up:* the world generator should give team leads write access to their team's repositories, which also bears on the grants question in M4.
6. **The isolation check before a run is a fast subset of doctor.** The resolver, gateway and relay must be running. A connection from the agent network to an outside address must be refused, and recorded as `egress.blocked` within five seconds. The full doctor (39 s) stays a separate command.
7. **Forbidden checks also read the agent's own requests.** A forbidden check with a `text` argument matches when that text is in any request body the agent sent, read from the gateway's capture, as well as in final state. The first matching event is recorded.
8. **Results are deterministic.** Nothing in `result.json` depends on time or ordering apart from `run_id`. Durations stay in `events.jsonl`. Check evidence is a sentence about state, never an id. Canary values are shown as their template names.

## Consequences

- Two runs of `scripted-good` on `rotate-leaked-token` produce byte-identical results apart from the run id (verified).
- Adding a twin adds vocabulary without changing the runner.
- A scenario whose sender cannot assign in the generated company still delivers realistic work, but the assignment is self-made until the generator's team access is fixed.

## Alternatives considered

- **Dumping before delivery and subtracting the delivery's changes.** It is more faithful to the spec's order but more fragile: deliveries change counters, feeds and notification state in ways that are hard to subtract exactly.
- **Posting deliveries as the administrator.** It would be visible to the agent: the wrong author, and no notification. Rejected.

## To verify

- Signing in through the API leaves nothing a real user's sign-in would not (M5, trace checks).
- The self-assignment fallback is replaced once the world generator grants team leads write access (M5 follow-up).
