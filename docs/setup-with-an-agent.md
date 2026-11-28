# Setting it up with a coding agent

You can ask a coding agent, such as Claude Code, to do the setup for you. That covers installing the tools, creating the engine, building a first world and running one scenario. Setup is a series of commands with long waits and errors to read, and an agent handles that well. Every `mirror` command accepts `--json`, and every error says what failed and what to do.

An agent left to work this out for itself can also do harm. To make a failing check pass, it might switch the check off, use your own Docker, or pass a flag that lowers the protections. The prompt below is written to prevent that. It lists what the agent may change, tells it to stop and ask when a check fails, and asks for a report that quotes the checks exactly as they printed. Use it as written rather than improvising your own.

If you prefer to run the commands yourself, the README's "From clone to a first passing run" and [your-company.md](your-company.md) have the same steps.

## Before you paste it

- **Take the prompt from a copy you trust.** Use your own clone of the repository or a tagged release, not a copy from a web page or a message. The prompt is reviewed like code, but a copy passed around can be changed on the way.
- **Don't test the agent that did the setup.** The setup agent has seen the repository, and possibly the built-in scenarios and how worlds are built. If that same session (or anything with its memory) is the agent you then test, it may know it is in a test. Test a fresh session with no memory of the setup, and for results you will rely on, use private scenarios it has never seen (see [writing-a-scenario.md](writing-a-scenario.md)).
- **Keep your model key to yourself.** The first run uses a scripted agent and needs no key. When you add a model later, set the key in your own shell. Don't paste it into the conversation.
- **Read what it proposes.** The prompt asks the agent to ask before anything that needs `sudo`, installs system software, or changes a setting outside the mirror. Answer those yourself.

Windows 11 is experimental. On Windows, the prompt tells the agent to follow [platforms/windows.md](platforms/windows.md) one step at a time and to ask before each step.

## The prompt

Copy everything inside the block into a new session of your coding agent, started in the folder where you want the clone to go (or inside an existing clone).

```text
Set up MirrorDimensions on this computer and take it as far as one passing
run of the built-in scripted agent. MirrorDimensions is a sealed test range
for AI agents: it runs a synthetic company inside a Linux VM that it manages
(the engine). It is designed so that nothing leaves the sandbox except calls
to a configured model endpoint. Your job is to install it and check that
those protections work on this machine, not to make it work at any cost.

The repository is https://github.com/mirrordimensions/mirrordimensions. If
the current folder is already a clone of it, use that clone. Otherwise clone
it here. The steps are in its README ("From clone to a first passing run")
and in docs/your-company.md ("Set up your laptop"). Follow those documents
and prefer them to what you remember.

Steps:
1. Find the operating system and architecture. Supported: macOS 13+ on Apple
   Silicon, Linux x64 with KVM. Windows 11 x64 is experimental: if this is
   Windows, follow docs/platforms/windows.md and ask me before each step.
   Anything else: stop and tell me.
2. Check the requirements: 16 GB of memory, about 15 GB of free disk, and on
   Linux a readable /dev/kvm. Report what you find. If one is short, stop and
   ask.
3. Install what is missing: git and uv; on macOS, Rosetta for Linux
   (softwareupdate --install-rosetta); on Linux, the packages
   docs/your-company.md lists. Ask me before each install, and before any
   command that uses sudo.
4. Install the mirror from the clone: uv tool install --editable .
5. mirror engine setup, then mirror engine check. Every line of engine check
   must start with "ok".
6. Create a world in ~/mirror-worlds, outside the clone:
   mirror world new northfield --template software-team, then
   mirror world create in its folder.
7. mirror up, then mirror doctor. It must end with three verdicts:
   "Isolation: full" (followed by the boundary in brackets),
   "Coverage: complete" and "Undetectability: full".
8. mirror agent add <clone>/examples/agents/scripted-good/agent.yaml, then
   mirror run rotate-leaked-token --agent scripted-good. It should pass.

Rules. These come before finishing the setup:
- engine check and doctor are the measure of success. If a line of
  engine check fails, or doctor gives any verdict other than the three
  above, stop. Show me the failing lines exactly as printed and what the
  message says to do, and wait for my answer. Do not retry with changed
  settings, and do not look for a way around the check.
- Never weaken the isolation to get past a failure. Do not disable,
  skip or edit a check; do not edit the mirror's code or its generated
  files; do not share a host folder with the engine, publish a port, or
  give a container a route to this computer.
- Do not pass these flags unless I ask for them by name:
  --driver host, --experimental, --allow-emulated, --accept-reduced-guarantees,
  --accept-personal-data, --no-check, --force.
- Never use, change or remove my own Docker contexts, Lima instances,
  virtual machines or WSL settings. The mirror creates its own engine; leave
  everything else as you found it.
- Change only what the steps need: the clone, ~/mirror-worlds, the uv tool
  install, and the packages I agree to. Ask before changing anything else,
  such as shell profiles, system settings or group membership.
- Do not print, store, copy or ask for an API key. None is needed for this
  run. If one is needed later, I will set it in my own shell.
- Do not read the scenarios or the test data: stay out of
  src/mirrordimensions/scenarios/, any scenarios/ folder, any .mirror/
  folder, and examples/agents/ apart from passing the agent file's path.
  Do not run mirror scenario show, mirror world show canaries,
  mirror trace or mirror report. I will read the run's report myself.
- Do not commit, push, or open issues or pull requests.
- If a step needs a judgement call (low disk, a missing package, a
  download that fails, an error you do not understand), stop and ask.

When you finish, or when you stop, report:
- the operating system, memory and free disk you found;
- what you installed and what you changed, including anything I approved;
- the output of mirror engine check and of mirror doctor, copied exactly;
- the run's summary line, and the command I can use to open its report
  (mirror report latest --open, in the world's folder);
- anything that failed or that you skipped, and why.
```

## Afterwards

- Check the report it gives you. Run `mirror doctor` in the world's folder yourself and compare it with what the agent copied.
- Open the run's report with `mirror report latest --open`, from the world's folder.
- Everything the agent installed can be removed. See "Stopping, removing and uninstalling" in [your-company.md](your-company.md).
- To test your own agent, carry on from step 3 of "Step by step" in [your-company.md](your-company.md), in a session that did not do the setup.
