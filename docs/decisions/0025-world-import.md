# 0025. World import: facts from files on the host, one draft, review, then apply

Status: Proposed

## Context

The build spec's World import section asks for importers that read files describing a company and turn them into facts in one common draft. The admin reviews the merged result, settling any disagreement, before anything reaches `mirror.yaml`. M8 requires two importers: agent tool configuration with OpenAPI, and Terraform state JSON. Real files hold credentials and people's details, and neither may ever reach a fact or the disk.

The formats were checked against their current documentation:

- **Terraform.** The `terraform show -json` state representation: `values.root_module`, `child_modules`, and each resource's `values` and `sensitive_values`.
- **MCP client configuration.** Claude Code's `.mcp.json`, and the portable `mcpServers` format other clients share: `type`, `url` and `headers` for remote servers; `command`, `args` and `env` for local ones. VS Code's `mcp.json` (`servers`) is read too.
- **OpenAPI 3.1.** `servers` with variables, `paths`, and operations.

## Decision

1. **Importers return facts and know nothing of each other.**
   - They live in `src/mirrordimensions/importers/`, one module each:
     - `mcp-config`: the agent's MCP client configuration;
     - `mcp-tools`: an exported `tools/list` with the server's `serverInfo`;
     - `openapi`;
     - `terraform`.
   - Plug-ins add more through the `mirrordimensions.importers` entry points.
   - A file's kind is detected from its content, or named with `--as`.
2. **The draft is `.mirror/import/draft.json`, owner-only.**
   - It holds the facts, the sources read (by file name only) and the admin's decisions.
   - The review is computed from it each time:
     - facts about one subject (a product's catalog slug, `mcp:<server>`, or `<category>:<name>` for infrastructure) are combined and list every source;
     - facts that disagree become a conflict.
   - Reading a file again replaces what it said before.
3. **Nothing secret, no one real.**
   - Each importer reads only the fields it needs.
   - Header values, secret-looking variables, attributes marked sensitive in `sensitive_values`, and values matching secret patterns are dropped and counted. Resources about people (users, memberships, collaborators) are skipped whole.
   - A last guard runs before any fact exists:
     - a string that looks like a credential is emptied;
     - a sentence holding an email address is removed, with the name that goes beside it.
4. **Defaults follow the spec's table.**
   - A system the agent has a tool or an endpoint for: `granted`.
   - A system with a twin known only from Terraform: `denied`.
   - A product with no twin, or an internal service: `build: unavailable`.
   - Infrastructure: recorded under `infrastructure:`, not built.
   - When the hostnames share one domain the world's company does not use, the company takes that domain and a matching name, so the invented people's addresses fit the systems. Its people stay invented.
5. **Tools map to twins through each twin's own library.**
   - `twins/<product>/mcp_tools.yaml` lists the MCP tools the twin can serve and what each calls (`app: self`).
   - An imported tool maps when a buildable system in the import offers a tool by its name, and every argument the mapping needs is in the tool's input schema.
   - On apply, the server's tool list is the export cut to the mapped tools, written beside its surfaces under `tools/`. Unmapped tools are listed in review as unavailable, with the reason.
6. **Apply refuses while a conflict is open**, or while an included system has no hostname.
   - Systems already in `mirror.yaml` are updated in place, matched by product; new ones are added; nothing else is removed.
   - `draft.json` records, for each entry written, the facts it came from (`mirror world import provenance`).

## Consequences

- An MCP server is served with fewer tools than in production when some of them map to no twin. The agent sees that difference; review lists each one.
- OpenAPI endpoints are read, counted and listed with their system. The spec's "surfaces in that system's profile overrides" is not built: profiles have no override mechanism yet. No M8 acceptance criterion depends on it.
- The secret patterns are deliberately eager: a value wrongly dropped costs a fact; a value wrongly kept could be a credential on disk.
- The import fixtures plant fake secrets on purpose, so `.gitleaks.toml` allowlists `tests/fixtures/import/`, as it does the golden world's canaries.

## Alternatives considered

- **Reading Terraform source instead of state.** Rejected by the spec: source holds unresolved variables and modules.
- **Matching tools by description, or with a model.** Not deterministic, and a wrong mapping would quietly change what a tool does.
- **Replacing the world's apps with the import's.** Simpler, but it would drop systems and links the admin defined by hand.
