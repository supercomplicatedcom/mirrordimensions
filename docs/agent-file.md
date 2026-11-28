# The agent file

An agent file tells the mirror how to run your agent and what it may touch. `mirror agent new` writes one by asking six questions; `mirror agent add <file>` registers one you wrote; `mirror agent check <name>` runs every preflight check and names the fix for each failure. `mirror schema agent` prints the exact format.

This is `examples/agents/llm-example/agent.yaml`, an agent that reads its issues and calls a model:

```yaml
name: llm-example
mode: hosted
image: issue-assist:0.9
build: .
model: primary
acts_as:
  role: engineer
wake:
  type: command
  command: ["python", "/opt/assist/agent.py"]
env:
  GITEA_URL: "${code.url}"
  GITEA_TOKEN: "${code.token}"
grants:
  code:
    repos: { billing-service: write, platform-docs: read }
  chat:
    channels: [platform-team, incidents, engineering, releases]
```

## Fields

| Field                | What it is                                                                                                                                                                                                                                                                                             |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `name`               | The agent's name in this project: lowercase letters, digits and hyphens. You run it with `mirror run <scenario> --agent <name>`                                                                                                                                                                        |
| `mode`               | `hosted`: your image runs in a container on the office network. `browser`: the same, with a managed browser beside it that the agent drives. `remote`: the agent runs on its vendor's platform and reaches the world through an exposed MCP server (see [your-company.md](your-company.md))            |
| `image`              | The container image, as your company deploys it. The mirror runs it unchanged                                                                                                                                                                                                                          |
| `build`              | Optional. A folder with a Dockerfile, relative to the agent file; the mirror builds it into `image` inside the engine before each run. Without it, the mirror pulls `image` from its registry the first time. Give each agent its own image name: two agents built under one name overwrite each other |
| `production_arch`    | Optional: `amd64` or `arm64`, the architecture you deploy on. The image itself must match the engine's architecture (`arm64` on Apple Silicon); `mirror run --allow-emulated` runs a foreign one at reduced isolation                                                                                  |
| `model`              | Optional. The name of a model route in `mirror.yaml` (`models:`). Leave it out for an agent that calls no model                                                                                                                                                                                        |
| `acts_as`            | Who the agent works as: `role:` (any person with that role: `engineer`, `manager`, `support`, `product`, `admin`, `contractor`) or `person:` (one username from `mirror world show people`). The agent signs in as that person; colleagues see that person's name                                      |
| `wake`               | How the agent learns that work has arrived. `type: command` with `command:` runs that command in the container once the work is delivered, as a job runner would. `type: poll` starts the image's own command, and the agent finds the work itself by watching its issues or chat                      |
| `env`                | Optional. The variables the agent is deployed with. Values can refer to what the mirror issues it (below). Leave `env` out to get each granted system's usual variables                                                                                                                                |
| `grants`             | What the agent may reach, system by system (below). A system that is not granted does not answer the agent                                                                                                                                                                                             |
| `reduced_guarantees` | Remote agents only: `accepted`, once you have accepted that leaks are detected rather than blocked                                                                                                                                                                                                     |

## What the agent receives

**Variables.** With no `env`, the agent gets each granted system's variables in the form a deployment would have:

| System                 | Variables                                             |
| ---------------------- | ----------------------------------------------------- |
| Code hosting (Gitea)   | `GITEA_URL`, `GITEA_TOKEN`                            |
| Team chat (Mattermost) | `MATTERMOST_URL`, `MATTERMOST_TOKEN`                  |
| Device platform        | `<ID>_URL`, `<ID>_TOKEN`, named after the system's id |

With `env`, the agent gets exactly the variables you list. Values can contain `${<system id>.url}`, `${<system id>.token}`, `${<system id>.username}` or `${<system id>.password}`, filled from the credentials issued for that system. The system ids are the `id:` fields in `mirror.yaml`. A world from the template, or from `--systems`, calls code hosting `code` and team chat `chat`.

**A model key.** For each model route, the variable it names (`credential: {from_env: ANTHROPIC_API_KEY}`) holds a placeholder key in the provider's format. The agent calls the provider's usual hostname (`api.anthropic.com`). The world's resolver sends that hostname to the gateway, which swaps in your real key on the way out and records the exchange. Your key never enters the container.

**The company's certificates.** The world's root certificate is added to the image's system trust store before it starts, as the company's image build would. Most clients pick it up from there. Python's `requests` and some others read their own bundle; point them at the system one with `SSL_CERT_FILE` or `REQUESTS_CA_BUNDLE` set to `/etc/ssl/certs/ca-certificates.crt`.

**An ordinary workstation.** A host name in the company's own convention, such as `ws-7119` or `lt-04817`, an address on the office network, the company's resolver, no capabilities, and nothing that names the mirror.

## Grants

Grants are exact: the person the agent acts as has, for the run, only what is listed here.

Each world names its core repositories and channels its own way (`billing-service` may be `invoicing`), and `mirror world show projects` lists them. Grants can use the world's names or the usual ones; the usual ones are translated at each run.

| System                          | Grant                                                                                     | Example                                                        |
| ------------------------------- | ----------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Code hosting                    | `repos`: each repository with `read` or `write`                                           | `code: {repos: {billing-service: write, platform-docs: read}}` |
| Team chat                       | `channels`: the channels it is a member of. Direct messages to the person always reach it | `chat: {channels: [platform-team, incidents]}`                 |
| The world's MCP server          | `{}` for every tool, or `tools:` for some                                                 | `tools: {tools: [search_issues, post_message]}`                |
| Device platform, message broker | `sites`: each site with a level                                                           | `building: {sites: {hq: operator}}`                            |

A scenario delivers its work somewhere, such as an issue in a repository or a message in a channel. If the agent is not granted that place, the run says so before it starts. Grant what the agent would have at work, not everything: a scenario that tempts the agent outside its job only means something if the agent can be refused.

`mirror set grant <agent> <system>/<name> <grant>` changes one grant from the command line, and the portal's Permissions screen does the same. A change takes effect at the next run.

## Checking it

```sh
mirror agent check my-agent
```

The check covers each of the following, and names the fix for anything that fails:

- the file is complete;
- the world is running;
- the image is built for the engine;
- credentials are issued;
- the production hostnames resolve to the world;
- the image starts with the company's root trusted;
- nothing given to the agent names a test;
- the agent does not refer to the operator's own tools;
- the model is reachable through its route;
- every coverage channel reports captured.

`mirror agent creds my-agent` shows the identity and credentials the agent would be issued, for debugging.
