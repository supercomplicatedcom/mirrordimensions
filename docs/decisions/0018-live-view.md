# 0018. The live view: locations recorded at capture, steps sent as they open

Status: Proposed · Date: 2026-11-24 · Milestone: M7

## Context

The build spec's live view puts a marker on the resource the agent is acting on, within two seconds of the event that caused it, and replays a finished run with the same screen. It asks for two adapter methods, `locate(exchange)` and `describe(exchange)`, generated from each system's profile, and for steps: consecutive requests to the same resource within two seconds become one step, and a model call is its own step.

Three things the spec leaves open decide whether the view is right:

- **Some requests name a resource only by id or in their body.** A Mattermost post names its channel as `channel_id` in the request body, and reading a channel names it by id in the path. The host does not see bodies until the run ends (they are copied out of the gateway then), so a location worked out on the host during a run would say "Posts a message" live and "Posts in #incidents" in replay.
- **A step that is still growing.** If a step were sent only once it closed, a live view would wait two seconds after every step's last request before showing it.
- **A change hidden inside reads.** Under the spec's rule, reading `#incidents` and then posting in it a moment later is one step, "Opens #incidents". The post, the request that matters, would not have a step of its own, and a broken rule would mark a read.

## Decision

1. **The gateway records where each exchange acted.**
   - Every `http.exchange` to a system with a profile carries `where`: the surface, its kind, the resource, the access and the sentence.
   - The gateway computes it from the same profile code the host uses (`behavior.py`, already shared for rules). It reads the request body for `{body.field}` in a surface's resource, and learns names from responses.
   - A surface's `exposes` may name an `alias`: `channel.by_name` exposes `channel:{name}` with the alias `channel:{id}`, so a later `channel_id` is located by its name.
   - Live view and replay therefore read the same location.
   - Runs recorded before this have no `where`. For those, the host works it out the same way from the bodies stored in the run's folder.
   - The adapters' `locate(exchange)` and `describe(exchange)` wrap the same code, with the request body and the names learned so far as optional fields of the exchange.
2. **Steps** (`trace/steps.py`):
   - Requests to the same resource within two seconds merge into one step, as the spec says, with one refinement: a change is never merged into the reads before it. Consecutive identical changes still merge.
   - A page's own loads merge into the step that opened it: styles, scripts, pictures and its live connection (surfaces of kind `asset` and `background`).
   - A model call is its own step (`think`). Refused requests, failed lookups and blocked connections are `blocked`, and identical ones within two seconds merge.
   - When a forbidden check fails, the step holding the event it names becomes a `violation`, and the evidence is added to its detail.
3. **Steps are sent as they open, and again as they change.**
   - `GET /runs/{id}/steps/stream` and `mirror watch` send a step as soon as its first event is written. They send it again, with the same index, each time it grows or turns out to have broken a rule. The page replaces it by index.
   - `run.start` now names the addresses the agent's requests come from (`clients`), so steps are read without loading the agent file.
4. **The map** is drawn from the agent's grants: systems with their repositories and channels, plus the model API and the outside, which are always drawn. A resource the agent reaches without a grant is added as it is reached, marked "not granted".

## Consequences

- `http.exchange` gains one optional field, `where`, and `run.start` gains `clients`. Older runs still read; their steps are worked out on the host.
- Profiles gained `unnamed` (the sentence while a resource is still only an id), `alias` in `exposes`, and `{body.field}` in resources. Gitea's profile gained the pages a browser loads (home, dashboard, assets, avatars, the live connection, issue history, the comment form).
- A step's index is stable while a run is live, so a page following the stream needs no reordering.
- Measured on an Apple Silicon Mac: an event reaches `events.jsonl` 0.07 s after the gateway records it, and its step reaches the portal 0.07 to 0.23 s after that. That is about 0.3 s in all, against a 2 s budget (`docs/platforms.md`).

## Alternatives considered

- **Locate on the host only.** Simpler, but live steps would differ from replayed ones until the run ends, or bodies would have to be copied out of the gateway during the run.
- **Send a step only once it closes.** Each step would arrive up to two seconds late, and the last step of a burst would wait for the next event.
- **Merge every request to one resource, as written.** It hides changes inside reads, and a broken rule would be drawn on a read.

## To verify

- A browser agent and a real model agent in the live view during a run. Recorded runs of both replay correctly, but neither has been watched live yet.
- The portal following a run of 10,000 events live on a slower laptop.
