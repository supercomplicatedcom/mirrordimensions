# From clone to a first run on Windows 11 x64

**Experimental.** The Windows engine is written against WSL's documented commands and unit-tested, but it has not yet run on a Windows machine. It stays experimental until every item in [windows-verification.md](windows-verification.md) has passed on real hardware and been recorded in [../platforms.md](../platforms.md). If a step below fails, please report what you saw (see [CONTRIBUTING.md](../../CONTRIBUTING.md)); if it looks like a way out of the sandbox, report it privately (see [SECURITY.md](../../SECURITY.md)).

These are the steps of the README's "From clone to a first passing run", in PowerShell.

## What is different on Windows

- **The engine is a WSL2 distribution of its own**, `mirrordimensions-engine`, imported from Ubuntu 26.04's published WSL image (pinned by checksum) into `%LOCALAPPDATA%\mirrordimensions\wsl`. The mirror never changes your other distributions. It never reads or changes your `.wslconfig` either.
- **It shares a VM with your other distributions.** WSL runs every distribution in one lightweight VM with one kernel. So results on Windows record `boundary: shared-vm` (decision 0002), where macOS and Linux record `dedicated-vm`.
- **The engine uses whatever CPUs and memory WSL gives every distribution.** `--cpus`, `--memory` and `--disk` have no effect on Windows. To change those limits you would edit `.wslconfig` yourself; that changes them for all your distributions.
- **Nothing from Windows is shared with the engine:**
  - no drives under `/mnt/c`;
  - no Windows programs;
  - no Windows `PATH`;
  - no generated hosts file.
- **The control plane reaches Docker through WSL's localhost forwarding**, on `127.0.0.1:23760`, with mutual TLS. The client key lives in `%LOCALAPPDATA%\mirrordimensions\docker-tls`, readable only by you.
- **microVM agents (`--microvm`) are not available**, because WSL offers no nested virtualization.

## Prerequisites

- Windows 11 x64 with hardware virtualization turned on in the firmware.
- About 15 GB of free disk.
- A current WSL. In an administrator PowerShell, run the command below, then restart Windows. If WSL is already installed, `wsl --update` is enough.

  ```powershell
  wsl --install --no-distribution
  ```

- [uv](https://docs.astral.sh/uv/) and Git:

  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  winget install --id Git.Git -e
  ```

No API key is needed: the first run uses a scripted agent.

## 1. Install

```powershell
git clone https://github.com/supercomplicatedcom/mirrordimensions
cd mirrordimensions
uv sync
$clone = (Get-Location).Path
function mirror { uv run --project $clone mirror @args }   # use mirror from any folder in this window
```

## 2. Create the engine

```powershell
mirror engine setup --experimental
mirror engine check
```

`engine setup` does four things:

1. downloads Ubuntu's WSL image and checks it against the pinned SHA-256;
2. imports the image as `mirrordimensions-engine`;
3. writes the engine's `wsl.conf`, so nothing is shared with Windows;
4. installs Docker Engine and gVisor, and puts Docker behind mutual TLS.

`engine check` proves the engine's guarantees from the outside. It checks:

- gVisor;
- that the Docker endpoint refuses a connection without the client certificate;
- that no Windows folder is mounted;
- that containers cannot reach Windows;
- that only allow-listed traffic leaves the engine.

## 3. Create a world

Use a folder of its own, outside the clone:

```powershell
cd ~; mkdir mirror-worlds -Force; cd mirror-worlds
mirror world new northfield --template software-team
cd northfield
mirror world create
```

## 4. Start the sealed network and prove it is sealed

```powershell
mirror up
mirror doctor           # ends with Isolation: full (shared-vm), then Coverage and Undetectability
```

## 5. Add an agent and run a scenario

```powershell
mirror agent add $clone\examples\agents\scripted-good\agent.yaml
mirror run rotate-leaked-token --agent scripted-good
```

## 6. Read what happened

```powershell
mirror report latest --open
```

## The core suite with a real model (the exit gate)

`llm-example` calls Claude through the model gateway.

1. Add a model route to `mirror.yaml`:

   ```yaml
   models:
     - name: primary
       provider: anthropic
       host: api.anthropic.com
       credential: { from_env: ANTHROPIC_API_KEY }
   ```

2. Then:

   ```powershell
   $env:ANTHROPIC_API_KEY = "<your key>"     # the gateway takes it when the sandbox starts
   mirror agent add $clone\examples\agents\llm-example\agent.yaml
   mirror apply                              # restarts the sandbox with the route
   mirror run core --agent llm-example
   ```

Every scenario should reach a scored result with a report. The agent need not pass them.

## Stopping and removing the engine

```powershell
mirror engine stop       # ends the distribution; mirror engine start brings it back
mirror engine destroy    # unregisters it and deletes every file setup created
```

For a shell inside the engine (administration only): `wsl -d mirrordimensions-engine -u root`.
