# Design reference

These are the source files of the design canvas for the command line and the portal.

Live canvas (needs access): https://claude.ai/artifact/7x7UqcfLwVRAUFeuhu9qGd

## How to use these files

- Each `.dc.html` file is one artboard. They are written for the canvas viewer and load `support.js` from it, so they do not render on their own in a browser.
- Read them as markup: layout, wording, states, colors and component structure are all in the inline styles and text. Interactive artboards also carry their behavior in the script block at the end of the file.
- `canvas.json` lists every artboard with its title and position.
- All data shown is sample data for illustration.

## Artboards

| File | Shows |
| --- | --- |
| `CliSetup.dc.html` | Terminal: init, plan, build, agent add |
| `CliRun.dc.html` | Terminal: doctor, run a suite, trace |
| `CliOnboard.dc.html` | Terminal: onboard an agent, check it, browser and remote variants |
| `CliWorld.dc.html` | Terminal: define a world, create it, clone, resume |
| `Main.dc.html` | Portal: environment map |
| `PortalSystem.dc.html` | Portal: one system's inputs and outputs, with a rule editor |
| `PortalAgents.dc.html` | Portal: agents list |
| `PortalPermissions.dc.html` | Portal: an agent's grants against use, and a permission sweep |
| `PortalCompany.dc.html` | Portal: the synthetic company |
| `PortalScenarios.dc.html` | Portal: scenarios |
| `PortalRuns.dc.html` | Portal: runs list |
| `PortalRun.dc.html` | Portal: run detail |
| `PortalLive.dc.html` | Portal: live view of an agent at work (interactive) |
| `PortalHealth.dc.html` | Portal: health |
| `Onboarding.dc.html` | Portal: agent onboarding wizard (interactive) |
| `WorldNew.dc.html` | Portal: world definition and creation wizard (interactive) |
| `ImportReview.dc.html` | Portal: review an import |

## Design tokens used

- Type: Inter for interface text, JetBrains Mono for code and terminal. Bundle both; the portal must work offline.
- Ground `#F6F7F9`, surface `#FFFFFF`, border `#E2E5EA`, text `#111827`, secondary text `#4B5563`.
- Accent and positive states: blue `#1D4ED8` on tint `#EEF3FE`, text `#1E3A8A`.
- Failures, denials and warnings: `#7C2D12` on tint `#FFF4E8`, border `#9A3412`.
- Terminal: ground `#0B1220`, text `#D7DEE9`, dim `#9AA7B8`, ok `#7DD3FC`, fail `#FBBF24`.
- State is never shown by color alone: every state also has a word.
- Controls are at least 44 px tall.

## Not yet designed

The catalog picker in the world wizard, and sites and devices on the map and live view. The build spec describes both.

## The canvas shows more than the prototype builds

Follow the build spec where they differ. In particular: the "Production vs mirror" layer, drift status, the "Honesty" finding, the remote-gateway onboarding path, systems other than Gitea and Mattermost, and automatic permission-sweep grids are product direction, not prototype scope.
