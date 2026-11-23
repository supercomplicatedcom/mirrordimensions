# MirrorDimensions

A sealed, self-hosted test range for AI agents. An agent does real work inside a synthetic company and its systems (code hosting, chat, tickets) at production-style hostnames over valid TLS. It cannot reach the internet, everything it touches is recorded, and each run is scored. The agent must never be able to tell it is in a test.

> **Status: pre-alpha.** Milestone M0 (scaffold) is in progress. Nothing here runs an agent yet.

## Three guarantees

- **Isolation.** Nothing leaves the sandbox except calls to the configured model endpoint.
- **Complete coverage.** Every way the agent can touch something is captured, or it does not exist.
- **The agent must not know.** Nothing it can see reveals a test, and nothing that builds, runs or scores the world is reachable from inside it.

## Platforms

macOS on Apple Silicon, Windows 11 x64 and Linux x64, with the same guarantees on each. Every host runs the sandbox in a Linux VM the project manages (the engine), with gVisor inside it. Windows is **experimental** until it has been verified on real hardware. See [docs/platforms.md](docs/platforms.md) and the decision records in [docs/decisions/](docs/decisions/).

## Install (development)

Needs [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/supercomplicatedcom/mirrordimensions
cd mirrordimensions
uv sync
uv run mirror --help
```

## First steps

```sh
uv run mirror init northfield-ops     # a project with a generated company and its root CA
cd northfield-ops
uv run mirror validate                # check mirror.yaml, agents and scenarios
uv run mirror status                  # project state, host and plug-ins
uv run mirror schema manifest         # JSON Schema for any file format
```

Every command accepts `--json` and exits 0 on success, 1 when a check fails, and 2 on a usage or configuration error.

## Built-in scenarios are public

The scenarios that ship with this project exist to test MirrorDimensions itself. Because they are public, AI models may have seen them, and may recognize them. For results you will rely on, write your own scenarios and keep them private: a project's `scenarios/` folder is for exactly that, and it should never be published.

## Acceptable use

MirrorDimensions includes prompt-injection and permission scenarios. They target synthetic companies only. Do not use this project against systems you do not own or are not authorized to test, and do not contribute working malware, exploit code or real credentials. See [SECURITY.md](SECURITY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Every commit needs a DCO sign-off (`git commit -s`).

## Licence

Apache-2.0. Copyright Supercomplicated LLC. See [LICENSE](LICENSE) and [NOTICE](NOTICE). "MirrorDimensions" is a trademark of Supercomplicated LLC; see [TRADEMARKS.md](TRADEMARKS.md).
