# 0022. The portal's wizards: new worlds in a folder of your choice, then switch

Status: Accepted (owner), point 1 · Date: 2026-11-25 · Milestone: M7

## Context

M7's fourth part adds the portal's two wizards. Each must write the same file as its command-line counterpart (`mirror world new`, `mirror agent new`), and drafts must resume from either interface. Three things needed deciding:

- **Which world the portal serves.** The portal serves one world, the project it was started in, but the world wizard defines a new one. Every world shares the one engine, and every sandbox uses the same container names, so creating a world stops whichever world's sandbox is running.
- **When the world's definition is written.** The spec says steps 1 to 5 write `mirror.yaml` with `status: draft`. The command line kept its answers in `.mirror/draft.json` and wrote `mirror.yaml` only at the end.
- **Answers the command line could not give.** The portal design asks for tidiness, links between systems and data counts, which `mirror world new` had no flags for.

## Decision

1. **New worlds go in a folder the owner chooses, then the portal switches to them** (the owner's choice, 2026-11-25, over a wizard only in an empty folder, or a new folder with no switching).
   - The wizard asks for a folder: a plain name means beside the current world, or a full path.
   - It refuses a folder that already holds a world, unless that world is a draft.
   - It warns that creating a world stops the running world's sandbox.
   - It creates the world with each stage shown as it finishes, then serves it.
   - A Worlds page lists the worlds beside the current one (any folder with a `mirror.yaml`). It switches between them and continues drafts.
   - Switching is refused while a run or an apply is under way. The marker `mirror doctor` reads for the portal's port moves with the switch.
2. **Every answer is written at once.**
   - Both interfaces save their answers to `.mirror/draft.json` and rewrite `mirror.yaml` with `status: draft` as soon as there is a company. The file validates at every step.
   - Finishing writes it without the status, plus the world's own files: the root CA, the `agents` folder and `.gitignore`.
   - Both interfaces render through one function, `render_world`, so the same answers give the same bytes. The portal shows the equivalent `mirror world new` command, and a test runs that command and compares the files.
3. **The command line gained the portal's questions:** `--company`, `--domain`, `--industry`, `--tidiness`, `--repositories`, `--issues`, `--messages`, `--canaries`, `--no-announce` and `--no-incidents`.
4. **Onboarding in the portal** calls the same service as `mirror agent new` for each of its six steps.
   - A draft starts as a valid agent file (`mode: hosted` until step 1 says otherwise), so the Agents page lists it as "Finish setup: step N of 6" and the wizard resumes it.
   - The Access step starts from the role's usual access and lists every repository and channel of the world.
   - The Check step runs the preflight, then offers a first job and opens its live view.
5. **A model route added during onboarding** reaches the gateway and the firewall when the sandbox starts, so it shows as a pending change at the restart level (decision 0021).

## Consequences

- Several worlds can live side by side and be switched in the portal, but only one sandbox runs at a time. Commands in a world whose sandbox is not the running one say so (decision 0021).
- An interrupted wizard leaves a valid `mirror.yaml` marked `draft`, which `mirror world create` refuses until it is finished.

## Alternatives considered

- **A wizard only in an empty folder.** Simplest, but a second world could not be started from the portal.
- **A new folder without switching.** The portal would create the world, then send the owner to the command line to open it.

## To verify

- Both wizards on Windows: folder paths and the switch.
