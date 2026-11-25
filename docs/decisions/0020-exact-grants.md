# 0020. Grants are exact: for a run, the person has only what the agent file grants

Status: Accepted (owner) · Date: 2026-11-25 · Milestone: follow-up to M4

## Context

An agent acts as one person of the synthetic company. The world gives that person access of their own: engineers can write every repository through the organization's `engineering` team, everyone else can read them all through `staff`, and each person is in their usual channels. The agent file then lists grants.

Until now grants were added to the person's own access, and nothing was removed. Three things followed:

- The build spec says out-of-grant calls get the production server's error. They did not: an engineer agent granted only `billing-service` could still push to every repository.
- The access map scores each action against the grants alone. Anything the agent did with the person's own access showed up as "outside grants", although nothing had refused it.
- The adapter guide already said `issue_identity` sets up an account "with exactly the grants given". The code did not.

The owner chose exact grants, over the person's own access plus grants (realistic for a borrowed login, but no least-privilege testing) and over a per-agent option (two code paths, two ways to read a result).

## Decision

1. **Identities are exact.** When a run issues the agent's identity in a system, after the snapshot restore and before the work is delivered and the "before" state is taken:
   - **Gitea:** the person leaves every team of the organization and is removed as a collaborator from every repository the grants do not name. The grants are then applied as collaborator permissions. A repository outside the grants answers Gitea's own 404.
   - **Mattermost:** the person is in the granted channels and the team's default channel (`town-square`, which Mattermost lets nobody leave), and leaves the rest. Direct messages are the person's own and are not grantable.
   - The announcements Mattermost posts when someone is added to or removed from a channel are deleted, so the change leaves nothing another user would see. Gitea records nothing for team changes.
   - The next run's snapshot restore puts the person's own access back.
2. **A run checks that the agent can reach its work.** Each twin says what a delivery needs (`delivery_needs`): an assigned issue needs its repository, and a channel message needs its channel. Before restoring the world, a run whose work arrives somewhere the agent is not granted ends as errored with that reason, naming the grant to add. It does not score the agent on work it could not read.
3. **The example agents grant what the built-in scenarios use.** #engineering (`merge-duplicate-issues`) and #releases (`release-notes`) are added to the chat agents. A test checks that every built-in scenario's work is reachable by `scripted-good`.

## Consequences

- "Outside grants" in the access map now means the agent was refused, not that it used the person's own access.
- An agent file must list every repository and channel the agent's work needs. The onboarding wizard (M7, part 4) starts from the role's usual access, so this is not a blank page.
- The person looks as if their access has been trimmed for the run (`docs/tells.md`, row 23). The owner accepted this.
- `mirror agent creds` issues the identity too, so it trims the person's access in the running world until the next restore.
- Systems that are not granted at all are left alone. The agent has no credentials for them.

## Alternatives considered

- **The person's own access plus grants, reported in three tiers.** Closest to an employee lending a login, but grants would limit nothing.
- **Added by default, exact as an option per agent.** Both kinds of test, at the cost of two code paths and two ways to read a result.
- **Remove Mattermost memberships in the database.** No announcements to delete, but it bypasses the product's own bookkeeping and its caches.

## To verify

- The MCP agent (`mcp-good`), whose tool calls act as the person: out-of-grant calls should now fail through the tools too.
