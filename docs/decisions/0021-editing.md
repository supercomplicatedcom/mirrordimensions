# 0021. Editing: what takes effect at the next run, at a restart, or after a rebuild

Status: Proposed · Date: 2026-11-25 · Milestone: M7

## Context

M7's third part lets the portal and the command line edit a world: a system's visibility, an agent's grants, and a system's rules. The build spec says that edits are written to `mirror.yaml` and the agent files, that they "appear as pending changes until the admin chooses to rebuild", and that rule changes "take effect on the next run with no rebuild".

Building it turned up four things:

1. **Rules did not take effect at the next run.** The gateway read its routes, with each system's rules and visibility, only when `mirror up` created it. A rule saved while the sandbox was up waited for the next `mirror up`, although the README said "from the next `mirror up` or run".
2. **Rules scoped to one agent never fired in a real run.** The rule engine supports `when: {agent: …}`, but the gateway never told it who sent a request.
3. **Visibility was hashed with the systems.** Changing a system from granted to denied marked the world stale and re-ran creation from stage 2, re-seeding everything, for a change the gateway alone carries out. Making a system absent only needs the sandbox restarted, since its data stays in the snapshot.
4. **The spec gives visibility an agent** (`set_visibility(project, app_id, agent, state)`, `mirror set visibility <app> <state> --agent <name>`), but `mirror.yaml` holds one visibility per system, and the prototype runs one agent.

## Decision

1. **When an edit takes effect.**

   | Edit | Takes effect |
   | --- | --- |
   | A rule, added, changed or removed | At the next run |
   | Visibility between granted, denied and present | At the next run |
   | An agent's grant | At that agent's next run (its identity is issued from its file) |
   | Visibility to or from absent | When the sandbox restarts: what runs and what DNS answers change. Runs refuse until it is applied |
   | Bringing back a system the world was built without | After a rebuild: it has never been seeded |
   | A system's settings, or a system added or removed | After a rebuild |
   | The company or its data | After a rebuild |

2. **Each run hands the gateway the current rules and visibility.**
   - Before restoring the world, a run rewrites the gateway's `routes.json`. Only each system's route is replaced; model routes and redaction stay as `mirror up` resolved them.
   - The gateway reloads the file when it changes. It checks the file's change time and size before each connection and request, because a copied-in file's modification time has whole-second resolution.
   - Each run's rules therefore also start from a fresh state, so a failure rate replays the same way in every run.
   - The run also names the agent's addresses (`identities`), so rules scoped to one agent fire for that agent only.
3. **Pending changes** are edits saved but not yet in effect. Two records decide this:
   - `.mirror/built.json`: the definition the world was last built from, written when the snapshot is saved.
   - `.mirror/applied.json`: the rules, visibility and grants the gateway and the last run used, written by `mirror up`, each run, and `mirror apply`.

   - A world built before these records existed compares against its creation record, so it can still say that its definition changed. Its `built.json` is written the first time its definition is unchanged since the build.
   - A rebuild that stopped part-way stays pending, with the stage and the reason.
4. **Visibility is per system, for every agent.** `mirror set visibility <app> <state>` takes no `--agent`, and the portal's control says "for every agent". The data model is unchanged, so per-agent visibility can be added when there are runs with several agents. The `systems` hash no longer covers visibility. The definition record lists which systems are absent, so only bringing back a system that was never built calls for a rebuild.
5. **Applying.** `mirror apply` and the portal's "Apply now" or "Rebuild changes" (`POST /build`, progress at `GET /build/stream`) put pending changes into effect now.
   - If any change needs a rebuild, creation re-runs from stage 2 (stage 1 if the company changed), with each system's volumes made anew and seeded again. Setting up a system that is already seeded leaves traces the trace check rejects (Mattermost's audit entries), and runs leave their own changes in the systems until the next restore. `mirror world create` now does the same whenever it starts from stage 2.
   - If a change needs a restart, the sandbox goes down and comes back up.
   - Then, if the sandbox is up, the gateway gets the current rules and visibility. With no run going, no agent is named.
6. **Editing commands and screens.**
   - Commands: `mirror set visibility`, `mirror set grant <agent> <system>/<name> <grant>` (exact grants: `none` takes a grant away), `mirror changes` and `mirror apply`. Each prints the change and when it takes effect.
   - Edits keep the files' comments and key order.
   - Each twin declares its grant vocabulary (`grant_key`, `grant_levels`): repositories at read, write or admin; channels by membership. MCP servers grant tools.
   - Portal: visibility in the Environment detail panel; grants in Permissions, for every repository and channel in the world; and a System screen. It lists every portal and endpoint with what it takes in and gives back (derived from the profile), and has a rule form (body limit, added delay, a share that fails, who it applies to) and a dry run of a request.
7. **Found and fixed along the way.**
   - **The user's own Docker setup.** docker-py read the user's `~/.docker/config.json`. It sent the user's registry credentials and credential helpers to the engine's daemon with every build, and a helper with an expired login stopped runs. It would also have added the user's Docker proxy settings to every container it created. The engine's client now uses none of that file.
   - **Credentials followed grants, not visibility.** An agent granted a system now gets no account there when the system is absent (its containers are not running) or present (the spec: running, but not in the agent's tools, so no credentials are issued).
   - **Another world's sandbox.** Every world's sandbox uses the same container names, so a command in one project could act on another project's running sandbox. Refreshing routes and the dry run now check the gateway's world label, and a run in one project errors if another world's sandbox is up.

## Consequences

- "Next run" means the next run: nothing needs `mirror up` again for a rule or visibility edit, and the README's sentence is now true.
- A rule changed during a run does not reach that run. Runs take the project lock, and `mirror apply` takes it too.
- Pending changes list grants changed since an agent's last run. An agent that has never run has nothing pending.

## Alternatives considered

- **Restart the gateway before each run.** Simpler, but slower, and it drops connections and the names learned for the live view.
- **Keep visibility in the `systems` hash.** Every visibility change would re-seed the world.
- **Per-agent visibility now.** It needs a second place for visibility (the agent file or a per-agent map in `mirror.yaml`), and the runner takes one agent.

## To verify

- The portal's Rebuild button through a full rebuild on a slower laptop, with its progress.
