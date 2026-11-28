# 0030. A seed folder the user chooses shapes and fills the world

Status: Proposed. Replaces the "Discovery from the user's computer" section of decision 0028.

## Context

Decision 0028 proposed discovery: with permission, the mirror would look through folders on the user's computer to learn the company's shape. That needed nine security rules, because the mirror would be choosing what to read on a computer full of the employer's data.

The owner reframed it (2026-11-28). The user, or the admin of the computer, chooses **one folder** and puts in it whatever data the world should be built from. That is preferably test or sample data: sample tickets, sample documents, a test repository, an anonymised chat export, a list of fictional staff. What goes in is the user's decision, and the mirror encourages test data. The mirror reads that folder and nothing else, and builds the company the agent will work in from it.

The owner chose, the same day:

- **Content and shape.** Files are used directly where they fit, and names and conventions are learned from them. The generator fills in the rest.
- **Warn and ask.** Secrets are always dropped. Personal data is listed with where it was found, and the user confirms before the world is built.
- **The first formats:** tickets, documents, git repositories, chat exports and people.

## Decision

1. **One folder, named by the user.**
   - `mirror world new <world> --seed-folder <path>` builds a new world from it.
   - `mirror world seed <path>` adds a seed folder to a world that exists, or reads its folder again.
   - The portal's world wizard offers "Start from a seed folder" beside a template, named systems and an import.
   - The mirror reads the files under that folder only. It never searches elsewhere, never uses the network, never runs a program, script or hook it finds, and never follows a link out of the folder.
2. **What it reads, in the first version.**

   | In the folder                                                                                                                       | Becomes                                                                                                                                                                         |
   | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
   | Tickets: CSV or JSON, either a hand-made sheet or an export from Jira, GitHub, GitLab or Linear (detected from the columns or keys) | Gitea issues with their comments, labels, states and assignees, in the repository the ticket names or the one the user maps it to                                               |
   | Documents: Markdown and plain text                                                                                                  | Pages of the handbook repository (the `docs` role), with the folder's layout, and the pages issues and chat can link to                                                         |
   | Git repositories (a folder with `.git`)                                                                                             | Repositories in the world, with their files and history. History is read with a pure-Python git reader, never the `git` program, whose configuration and hooks can run commands |
   | Chat exports: a Slack or Mattermost export (JSON)                                                                                   | Channels and their history, threads included                                                                                                                                    |
   | People: a CSV with names and, optionally, titles, departments, teams and managers                                                   | The staff list. Email addresses are rewritten to the world's domain                                                                                                             |

   Anything else in the folder is listed as not read.

3. **Content, and shape from it.** What the folder holds is used as it is. From it, the mirror also learns names and conventions: repository and channel names, labels, branch and commit styles, ticket vocabulary. The generator then fills what the folder does not hold, in that style, from the world's industry profile. A folder with only tickets still gets a full company, with the tickets inside it.
4. **Review before anything is built.**
   - `mirror world seed show` and the portal list what was found, what each item becomes and where, and what was dropped.
   - The user can leave out a file or an item, and can map things to the world's roles: which repository is the billing service, which channel is incidents.
   - An optional `seed.yaml` in the folder records the same mapping, so a folder builds the same way every time.
5. **Real data: warn and ask.**
   - **Secrets are always dropped**, using the importers' detectors (decision 0025): keys, tokens, passwords, private keys and connection strings with credentials. They are counted, never shown.
   - **Personal data is listed with where it was found** (file and line), before the world is built: email addresses outside the company's own domain, phone numbers, card numbers that pass a Luhn check, national identity numbers, street addresses. The user confirms to go on (`--accept-personal-data` without a terminal), or removes it from the folder and reads it again.
   - Both the review and the documentation say plainly that whatever goes into the world reaches the agent and its model provider, and appears in recordings and reports. They encourage test data.
6. **The agent cannot learn of it.**
   - The seed folder's path, the review, `seed.yaml` and the list of what was dropped stay on the host with the rest of the control plane.
   - What the world uses is copied into the project's owner-only `.mirror/` folder when the world is built, and becomes ordinary world content.
   - Seeded content carries no marker of where it came from.
7. **Built-in scenarios keep working.** The six core repositories and their roles stay. A seeded repository is added beside them, unless the user maps it to a core role. In that case the run warns that built-in scenarios written for that role may not fit it, and suggests writing a scenario from the seeded content.
8. **Determinism.** The world records a digest of the files it used. The same folder contents, `seed.yaml` and seed build the same world. A change in the folder shows as a pending change, and `world create` rebuilds what it affects.
9. **The public-text check counts only what the mirror generated.** Seeded text is the user's own and is not in the public repository, so it is left out of the share and reported separately.

## Consequences

- A company can test an agent on its own scenarios with its own kind of data, prepared by people who know what is safe to put in, without the mirror ever choosing what to read.
- The promise "real data never goes in" becomes: **the mirror never collects data; what goes in is what the user puts in the folder.** Secrets are always dropped, personal data is shown before use, and test data is encouraged. `docs/your-company.md` says this plainly.
- A seeded world's project folder is as sensitive as the seed folder. The documentation says to keep both private.
- The pure-Python git reader is a new dependency. Dulwich is the candidate (Apache-2.0 or GPL-2.0, at the user's choice), recorded with the build PR.
- The decision 0028 discovery section is replaced. Its rules that still apply are carried here: parse, never run; no links out; no network; no model on the folder's files while building; nothing reaches the sandbox.

## Alternatives considered

- **Discovery across the computer (decision 0028).** More automatic, but the mirror would choose what to read on a computer full of the employer's data.
- **Shape only.** Safer against real content, but it throws away exactly what a user prepares the folder for: their own sample tickets and documents.
- **Refuse personal data.** Simple, but some test data looks personal (fictional customers with phone numbers), and the owner wants the decision left to the user.

## To verify

- A folder holding only a ticket CSV, one holding only a Slack export, and one holding all five kinds each build a world that passes `mirror doctor` and the built-in scenarios.
- Planted secrets in every supported format are dropped and counted. Planted personal data is listed with its file and line.
- A hostile folder is refused or read safely: links out, a repository with hooks and a `core.fsmonitor` setting, huge files, deep nesting, malformed JSON.
- Nothing from the seed folder's path or review appears in anything the agent can read.

## Open questions for the owner

1. Should a seeded world still use an industry profile for what the folder lacks (the default), or only the folder's own style?
2. Should seeded issues and messages keep their own dates, or be moved onto the world's timeline (the default: the latest item lands a day or two before the world starts, and the rest keep their spacing)?
