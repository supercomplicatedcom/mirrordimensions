# Setting up a world for your company

This guide is for someone at a company who wants to test their own agent in a copy of their workplace. It covers the whole way: setting up your laptop, defining a world for your company, bringing your agent, and removing it all afterwards. The README's "From clone to a first passing run" is a shorter tour with a ready-made company, if you want to see it work first.

## What a world is, and what it is not

A world is a **synthetic** company. You choose:

- its name, domain, industry and size;
- how much history it has, and how tidy that history is;
- which systems it runs.

The mirror generates everything else: the people, the repositories with their commit history, the issues and the chat. Your agent sees production-style hostnames (`git.yourcompany.com`) over valid TLS, signed by the world's own root certificate, and none of it leaves your computer.

Your real data never goes in. There is no import of your repositories, tickets or messages. When you describe your systems from files (below), the mirror reads their shape, such as hostnames, tools and endpoints. It never keeps secrets or the people named in them.

## What a world can run today

| Kind of system              | Runs as                                                                            | In place of                          |
| --------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------ |
| Code hosting                | Gitea, the real software, unmodified                                               | GitHub, GitLab, Bitbucket and others |
| Team chat                   | Mattermost Team Edition, the real software, unmodified                             | Slack, Microsoft Teams and others    |
| A company MCP server        | The mirror's MCP server, serving your own tool list on top of Gitea and Mattermost | Your engineering tools server        |
| Building access and devices | The mirror's device platform (REST) and Eclipse Mosquitto (MQTT)                   | Door, thermostat and sensor systems  |

Every other system in the catalog (`mirror catalog search <name>`), including ticketing, CRM, HR and identity, has **no twin yet**. A world can name it, but it is not created.

So if your company uses GitHub and Slack, the world runs Gitea and Mattermost in their place, at the hostnames your company would use. `mirror world new` tells you when it does this:

```sh
mirror world new halden --systems github,slack,jira \
  --company "Halden Freight" --domain halden-freight.com --industry logistics
```

```
  chat: mattermost at chat.halden-freight.com (in place of slack)
  code: gitea at git.halden-freight.com (in place of github)
  ticketing: jira at tickets.halden-freight.com (unavailable: no twin yet)
note  Slack has no twin yet, so Mattermost runs in its place at chat.halden-freight.com. ...
note  Jira has no twin yet and nothing of its kind runs in its place, so the world leaves it out. ...
```

`--no-substitute` records GitHub and Slack as unavailable instead. If none of the systems you name can be built, `world new` stops and says which ones can.

## What this means for your agent

An agent is tested against what the world runs, so it must be able to talk to it. There are three ways, from most to least direct.

1. **Through the world's MCP server.** If your agent works through MCP tools (most general-purpose agents can), give the world an MCP server with your own tool list, and grant the agent `tools`. The agent calls tools such as `search_issues` or `post_message`; the mirror carries out each call against Gitea and Mattermost and records it. The agent does not need to know which product sits underneath. `examples/agents/mcp-good` is an agent that works only this way.
2. **Through Gitea's and Mattermost's own APIs.** An agent written for these APIs works unchanged. Gitea's REST API differs from GitHub's in places (paths start `/api/v1/`, tokens are sent as `token <value>`), and Mattermost's differs from Slack's. `examples/agents/scripted-good` and `llm-example` work this way.
3. **Through the web pages, as a person would.** A browser agent (`mode: browser`) drives a managed browser on the company network. `examples/agents/browser-basic` works this way.

An agent written only against GitHub's or Slack's own API cannot do its work in a world today. Use route 1, or adapt its client to route 2.

## Set up your laptop

Everything runs on your own computer. Nothing is installed on a server, and no account is needed.

**What it needs.**

|            |                                                                                                                                                                                                                         |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Computer   | A Mac with Apple Silicon (M1 or later) on macOS 13 or later, or a Linux x64 machine with hardware virtualization (KVM). Windows 11 is experimental: follow [platforms/windows.md](platforms/windows.md) for these steps |
| Memory     | 16 GB. The engine takes 6 GB while it runs                                                                                                                                                                              |
| Disk       | About 15 GB free: 7 GB for the engine, about 6.5 GB for a world, more for a bigger company                                                                                                                              |
| Network    | For setup only: about 3.5 GB of downloads the first time. A running world never uses your network, except your agent's calls to its model                                                                               |
| Not needed | Docker Desktop or any other Docker. The mirror runs its own Linux VM, the engine, and builds your agent's image inside it. It never uses or changes a Docker, Lima or virtual machine you already have                  |

**1. Install the tools it uses.** You need git and [uv](https://docs.astral.sh/uv/).

On a Mac:

```sh
xcode-select --install                       # git, if you do not have it
softwareupdate --install-rosetta             # Rosetta for Linux, which the engine uses
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Linux (Debian or Ubuntu shown; use your distribution's packages otherwise):

```sh
sudo apt-get install -y git qemu-system-x86 qemu-utils
sudo usermod -aG kvm "$USER"                 # then log out and in, so /dev/kvm is yours
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new terminal window afterwards, so `uv` is on your PATH.

**2. Install the mirror.**

```sh
git clone https://github.com/supercomplicatedcom/mirrordimensions
cd mirrordimensions
uv tool install --editable .                 # puts mirror on your PATH, in every window
```

If the shell then says `mirror: command not found`, run `uv tool update-shell` and open a new window. The command runs from the clone, so keep the folder.

**3. Create the engine** and check it. The first time takes a few minutes.

```sh
mirror engine setup
mirror engine check     # gVisor, Rosetta, a private Docker endpoint, no route to the host, egress rules
```

Every line of `engine check` should start with `ok`. A line that starts with `FAIL` says what to do.

**4. The portal (optional).** `mirror portal` opens the same steps in a browser. In a clone, its web pages must be built once, which needs [Node.js](https://nodejs.org/) 22:

```sh
npm --prefix src/mirrordimensions/portal/web ci
npm --prefix src/mirrordimensions/portal/web run build
```

Everything below also works from the command line alone.

## Step by step

**1. Define the world.** Use your company's name and domain, so the agent sees the hostnames it would see at work. Name your systems, or start from the template.

Keep worlds in a folder of their own, outside the clone.

```sh
mkdir -p ~/mirror-worlds && cd ~/mirror-worlds
mirror world new halden --systems github,slack --company "Halden Freight" \
  --domain halden-freight.com --industry logistics --people 40 --history 365
cd halden
```

**Start from your industry.** With `--industry` and no `--systems`, the mirror proposes the systems a company in that industry usually runs, and says which ones it can run:

```sh
mirror world new halden --industry software --company "Halden Software" --domain halden-software.com
```

```
A Software and SaaS company usually runs:
  GitHub: Gitea runs in its place
  Slack: Mattermost runs in its place
  Jira: no twin yet, recorded and left out
  ...
Use these systems? yes, no for the template, or type your own list [yes]:
```

`--yes` accepts the proposal without asking. `--add-systems jira,okta` adds to whichever list you start from. Today the general software profile is available; the other industry profiles are being written (decision 0028), and an industry without one gets the general company and the template's systems.

**Add a system later.** `mirror world add confluence` adds a system to the world's `mirror.yaml` and leaves the rest of the file as it is. Run `mirror world create` afterwards to build it.

`--tidiness messy` gives more stale tickets, duplicates and typos. `mirror world new` with no options asks each question in turn. The portal's world wizard (`mirror portal`) asks the same questions and writes the same `mirror.yaml`.

**2. Or describe it from your own files.** If you have your agent's MCP configuration, an exported tool list, OpenAPI specifications or Terraform state (`terraform show -json`), the mirror can read the systems from them. The files are read in place on your computer; secrets and people are dropped.

```sh
mirror world new halden --import mcp.json --import tools.json --import openapi.yaml \
  --company "Halden Freight" --domain halden-freight.com
```

If two files disagree, for example on a hostname, it stops and names the disagreement. Settle it and finish:

```sh
mirror world new halden --decide gitea.hostname=git.halden-freight.com
```

A tool list imported this way becomes the world's MCP server, serving each tool it can map to Gitea or Mattermost. A tool it cannot map is listed and left out.

**3. Add your model.** If your agent calls a model, add a route to `mirror.yaml`. It is the only way out of the sandbox:

```yaml
models:
  - name: primary
    provider: anthropic # or openai
    host: api.anthropic.com
    credential: { from_env: ANTHROPIC_API_KEY }
```

Set the key in your shell before `mirror up` (or before `mirror apply`, if the sandbox is already up). The agent itself gets a placeholder key in the provider's format; the gateway swaps in the real one on the way out, so your key never enters the sandbox or any recording.

**4. Create it, start it, and prove it is sealed.**

```sh
mirror world create        # about 3 minutes, more for a bigger company
mirror up
mirror doctor              # ends with: Isolation: full, Coverage: complete, Undetectability: full
```

**5. Bring your agent.** Your agent is a container image. Write its agent file (see [agent-file.md](agent-file.md)), or let the wizard write it:

```sh
mirror agent new my-agent          # six questions: image, model, who it acts as, access, how it wakes
mirror agent check my-agent        # every preflight check, each with its fix
```

**6. Run it.** Start with the built-in scenarios to see that everything works:

```sh
mirror run core --agent my-agent
mirror report latest --open
```

The built-in scenarios are public, and models may have seen them. For results you will rely on, write your own from your team's real work, such as "rotate the key someone pasted in #deploys" or "answer the on-call question from the runbook", and keep them private in the project's `scenarios/` folder. See [writing-a-scenario.md](writing-a-scenario.md).

## Stopping, removing and uninstalling

| To                                                                              | Run                                                                                  |
| ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Stop a world's network, keeping the world                                       | `mirror down` in the world's folder                                                  |
| Stop the engine and give back its memory                                        | `mirror engine stop`. `mirror engine start` starts it again                          |
| Remove one world's containers, volumes and snapshots, keeping its `mirror.yaml` | `mirror world destroy` in the world's folder                                         |
| Remove the engine and every world inside it, and get the disk back              | `mirror engine destroy`                                                              |
| Remove the `mirror` command                                                     | `uv tool uninstall mirrordimensions`, then delete the clone and your worlds' folders |

After a `git pull` in the clone, run `uv tool install --editable . --reinstall` to pick up new dependencies, and `mirror engine update` when `mirror doctor` or `mirror engine status` says the engine's packages are due an update. The engine never updates itself.

## Questions people ask

**Can I use my company's real name and domain?** Yes. The world's resolver answers for your domain inside the sandbox only, and nothing leaves it. Keep the project folder private, as you would any test of your own systems.

**Can it load our real repositories or Slack history?** No, by design: a test range must not hold real data. The mirror generates history that looks like a company of your size and kind.

**Our agent runs on its vendor's platform, not in a container.** Onboard it with `mirror agent new --mode remote`. It reaches the world through an MCP server that you expose with `mirror world expose`, behind your own reverse proxy. A remote agent gets reduced guarantees: leaks are detected, not blocked, and its model and platform are outside the record. `examples/remote/` has a reference platform and agent file.

**What does the agent see of the mirror?** Nothing, by design. Its host name, variables, certificates and network look like an ordinary workstation at the company. `docs/tells.md` lists every way a test was found to show itself, and how each was closed.
