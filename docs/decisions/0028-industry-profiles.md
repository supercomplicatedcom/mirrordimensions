# 0028. Industry profiles and the user's own computer shape the world

Status: Proposed.

## Context

`company.industry` in `mirror.yaml` is free text, and today it changes only two things: the suffix of a suggested company name and the two line items on the billing code's sample invoice. Every world is otherwise the same software company: the same repositories (`billing-service`, `platform-docs`, `data-pipeline`, `infra-config`, `customer-portal`, `ops-scripts`), the same kinds of issues and chat, the same roles.

So a world named "Halden Health" reads as a SaaS company with a hospital's name on it. A person setting up a world for their company has to describe it system by system, and an agent that knows what a hospital's engineering work looks like could notice that nothing here does. That mismatch is a tell.

The owner's proposal (2026-11-27): a user names their industry, and the mirror builds the environment a company in that industry would have. The user then adds their own specific tools.

A second proposal from the owner the same day: the person who installs the mirror can let it look at folders on their computer, with their permission, so that the simulation follows how their company actually works. The agent's inputs and outputs then do not differ from what it would get from the company's real software, and to the agent the world is the real company.

## Decision

1. **An industry profile is data.** Each profile is a YAML file shipped in the package (`src/mirrordimensions/world/industries/<slug>.yaml`) and validated by a schema (`mirror schema industry`). Profiles are reviewed like code. A profile holds:
   - `name`, `aliases` (such as `telco` and `telecom` for `telecommunications`) and a one-line description;
   - **organization**: departments with their share of headcount, and the job titles in each;
   - **sites**: the kinds of location the company has (hospitals and clinics; stores and distribution centres; a capital and regional offices), used for site names, time zones and devices;
   - **engineering**: the repositories this kind of company keeps beyond the common ones, each with its language, purpose, a README outline and the topics its history covers;
   - **work**: issue themes, incident themes, chat channels and chat topics, with the vocabulary the industry uses (HL7 and prior authorization; open-records requests; number porting);
   - **rules**: the regulations and policies that people refer to (HIPAA, PCI DSS, FedRAMP, SOX), as they come up in issues and docs;
   - **systems**: the systems such a company usually runs, as catalog slugs by kind (an EHR, ticketing, identity, email, a wiki), each marked `typical` or `common`;
   - **name suffixes** for suggested company names (replacing `INDUSTRIES` in `world/names.py`).
2. **Every world keeps a common core.** Every company has billing, internal documentation, data pipelines, infrastructure configuration and operational scripts, so the core repositories (`billing-service`, `platform-docs`, `infra-config` and the others the built-in scenarios use) and channels (`engineering`, `incidents`, `platform-team`, `releases`) stay in every world. The profile adds repositories and channels and supplies the vocabulary for the core ones. The built-in scenarios run unchanged in every industry. A profile can rename a core repository only through an alias that the scenarios resolve.
3. **Systems come from the profile, then from the user.** `mirror world new --industry healthcare` with no `--systems` or `--import` proposes the profile's typical systems. What has a twin is built, or stood in for by a twin of the same kind; what has none is listed as "no twin yet" and left out. This is what `--systems` already does. `--systems` and `--import` replace the profile's list, and `--add-systems` adds to it. The world wizard shows the proposed list with each system's state before anything is written.
4. **Adding a tool later.** `mirror world add <system>` adds a system to an existing world's `mirror.yaml`, with the same stand-in rules, and tells the user to run `mirror world create` again to build it. Until then, editing `mirror.yaml` by hand stays the way.
5. **Unknown industries are honest.** An industry that matches no profile or alias falls back to the general profile (today's world), and `world new` says so and lists the nearest profiles. Free text stays allowed in `mirror.yaml`.
6. **Determinism and quality hold.** The generator reads a profile as data, with the seed choosing among its entries; the same manifest still gives the same world. A profile must pass the naming lint and the placeholder lint. Each profile gets a golden world in the tests, and before it ships, a review of what an agent sees in a world built from it (the observer agent used for the exit gate's item 3).
7. **The user's own computer can shape the world**, with their permission, as set out in the next section. A profile is the starting point; what is found on the computer replaces the profile's guesses wherever the two differ.

## Discovery from the user's computer

The profile makes the world read like the industry. Discovery makes it read like this company: its hostnames, its repositories and their layout, its tools and their exact interfaces, its conventions. An agent tested in the world then sends and receives what it would at work.

This is not the build spec's discovery crawler, which crawls the company's production systems and stays out of scope. Discovery reads files that are already on the user's computer, and nothing else. It extends the importers of decision 0025, and keeps their rules.

**Requirements**

1. **Permission first, per source.**
   - `mirror world discover` lists the sources it can read, with each folder or file it would open, before it opens any. The user picks sources and folders.
   - The portal offers the same as a wizard step.
   - Nothing is read in the background, on a schedule or again later without being asked. Each run of discovery is a new permission.
2. **Only the computer, never the network.**
   - Discovery opens local files only. It never calls a company system, an API, a git remote or a model, even when it finds an address or a credential that would let it.
   - It never runs a found program, script or hook.
   - Nothing it reads leaves the computer.
3. **Shape, never content.** Discovery keeps the shape of the company and drops what is in it.

   | Kept, as facts for review                                                                                                                 | Dropped, always                                                                                         |
   | ----------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
   | Hostnames and URL layouts of internal systems                                                                                             | Secrets, tokens, keys and passwords, as in decision 0025                                                |
   | Which products the company uses (from git remotes, CI files, tool and MCP configurations)                                                 | Source code, documents, tickets, messages and email                                                     |
   | Repository names, languages, folder layout, build and CI conventions, branch naming                                                       | People: names, usernames, email addresses, photos                                                       |
   | Commit message and pull request conventions, as patterns (such as `feat(billing): ...`), never the messages themselves                    | Customer, patient, citizen or other personal data                                                       |
   | MCP tool lists and their input schemas; OpenAPI specifications; the environment variable names an agent is deployed with (values dropped) | Anything under a path the user excluded, and anything git ignores                                       |
   | Team and channel names, if the user includes them                                                                                         | Browser data, mail, chat applications' stores, keychains and password managers, which are never sources |

4. **Sources, in this order.** Each source is an importer with its own tests:
   - the agent's own deployment: its Dockerfile, Compose or Kubernetes manifests, `.env.example`, and MCP configuration;
   - clones of the company's repositories (remotes, layout, languages, CI, conventions, OpenAPI files);
   - developer tool configuration: `~/.gitconfig` (the company's domain), `~/.ssh/config` (host names only), MCP client configurations (decision 0025);
   - exported tool lists and infrastructure state (decision 0025).
5. **Review before anything is used.** Every fact goes into the import draft of decision 0025, with its source, and the user reviews it there. Names can be kept as found, generalised (`claims-intake` kept; `acme-patient-db-prod` turned into `patient-db`) or dropped, one by one or all at once. Nothing reaches `mirror.yaml` until the user applies the draft.
6. **The world follows the shape.**
   - The generator builds repositories with the found names, languages, layout and conventions.
   - It writes history in the found commit and pull request style.
   - It serves the found tool lists and API shapes from the world's twins and MCP server.
   - It uses the found hostnames and variable names.
   - All content is still generated: the code, issues, chat and people are synthetic.
7. **What was read is accounted for.**
   - The draft records which files were read, by path.
   - `mirror world discover report` shows what was kept and dropped and why, by count and kind, never the dropped values.
   - Discovery writes nothing outside the world's `.mirror/` folder, which stays owner-only.
8. **The agent cannot learn of it.**
   - Discovered facts become ordinary world content.
   - The draft, the report and the list of sources stay on the host with the rest of the control plane, and never enter the sandbox.

**Security requirements**

Discovery reads a computer that holds a company's data, with the user's access. These rules hold in every version:

1. **Kept names reach the model provider and the reports.** An agent sends what it reads to its model, so every name kept from discovery travels in prompts to the provider, and into each run's recording and report. Review says so on every kept name. The default for a name is to generalise it, not to keep it as found.
2. **Names are data.** Secret detection works on patterns and will miss things: a repository named after a client, a project's code name, a customer in a hostname, a token in an unfamiliar format. A name is kept as found only when a person keeps it in review. The documentation says that no scan catches everything.
3. **Remote agents never get discovered hostnames.** A hosted agent is sealed, so a real hostname resolves only to the world. A remote agent runs on its vendor's platform, where the same hostname reaches the company's real system. A world with a remote agent refuses discovered hostnames, or rewrites them so they cannot resolve outside the world, and `mirror run` checks this before it starts.
4. **Found files are hostile until parsed.**
   - Discovery never runs `git` or any program, hook or script it finds: repository configuration can make `git` run commands. It reads the files directly.
   - It follows no symbolic link out of the folders the user chose.
   - It parses YAML and JSON with safe loaders, and limits file sizes, file counts and depth.
   - A test suite of hostile repositories and files proves each rule.
5. **The scanner cannot send anything.**
   - Discovery code imports nothing that can open a network connection; `scripts/check_imports.py` enforces it.
   - Discovery runs in a separate process with no network access where the host allows it.
   - Third-party importer plug-ins are not loaded for discovery unless the user names them.
6. **Sources that are never read are enforced in code.** Browser profiles, mail stores, chat applications' data, keychains and password managers, `~/.aws`, `~/.kube`, `~/.gnupg` and the private keys in `~/.ssh` are refused by path, before any open. Every file opened is checked against the list the user approved, and a test fails on any other.
7. **No model on found files, ever.** Discovery is parsing, not reading by a model. Sending found files to a model would send the company's code and documents to a third party. This is permanent, not a first-version limit.
8. **The user's consent is not the company's.** A work computer holds the employer's data, and scanning it can break the employer's policy or trip its security tools. The documentation says to get the security team's approval first. `mirror world discover --plan` writes a list of the sources and folders it would read, for that team to review.
9. **A discovered world is marked.** The project folder records that it holds discovered names. `mirror report` and any export or share warn before including them, and `git` in the project folder ignores the draft and the world's generated files.

**Consequences**

- The world can use real internal names: hostnames, repository and channel names. Today's guide says real data never goes in. With discovery, the rule becomes: real names go in only when the user keeps them in review; real content never goes in. `docs/your-company.md` must say this plainly.
- A world built this way is specific to one company. Its project folder must be kept as private as the company's own configuration. The world itself still holds no secrets or real people.
- Discovery quality depends on what is on the computer. A laptop with three clones gives a narrower picture than the company has; the profile fills the rest.

## The first set of industries

Industries where companies are deploying AI agents, which is close to every sector with a technology team. They are grouped for the wizard; each line is one profile.

**Technology and media**

- Software and SaaS (the general profile)
- IT services and consulting
- Cybersecurity
- Telecommunications (mobile, broadband, cable)
- Media and publishing
- Streaming and entertainment
- Video games
- Advertising and marketing agencies
- Semiconductors and electronics

**Financial services**

- Retail and commercial banking
- Payments and fintech
- Capital markets and asset management
- Insurance (property and casualty)
- Insurance (life and health)
- Credit unions and community banks
- Accounting and tax services
- Cryptocurrency and digital assets

**Health and life sciences**

- Hospitals and health systems
- Clinics and physician groups
- Health insurance (payers)
- Pharmaceuticals
- Biotechnology
- Medical devices
- Digital health and telehealth
- Pharmacies
- Dental and veterinary practices
- Senior living and home care

**Consumer, fitness and wellness**

- Fitness clubs and studios
- Fitness and wellness apps and wearables
- Consumer goods and packaged foods
- Beauty and personal care
- Consumer electronics

**Retail and commerce**

- Retail stores and chains
- E-commerce and marketplaces
- Grocery and convenience
- Restaurants and food service
- Food delivery

**Travel, hospitality and leisure**

- Airlines
- Hotels and resorts
- Online travel agencies
- Cruise lines
- Car rental and mobility
- Live events and ticketing
- Casinos and gaming

**Government and public sector**

- Federal government (civilian agencies)
- Defense and national security
- State government
- Local government (cities and counties)
- Courts and justice
- Public safety and emergency services
- Public health agencies
- Social services and benefits

**Education and non-profit**

- K-12 school districts
- Universities and colleges
- Education technology
- Non-profits and foundations
- Research institutes

**Industry and infrastructure**

- Manufacturing (discrete)
- Manufacturing (process and chemicals)
- Automotive
- Aerospace
- Construction and engineering
- Energy: oil and gas
- Energy: utilities (power, water and gas)
- Renewable energy
- Mining and metals
- Agriculture and agritech

**Transport and logistics**

- Logistics and freight
- Shipping and ports
- Rail
- Trucking and fleets
- Postal and parcel delivery

**Professional services and real estate**

- Legal services
- Staffing and recruiting
- Management consulting
- Real estate and property management
- Architecture and design

That is 77 profiles. Each takes real writing (repositories, issue and chat themes, roles and vocabulary that read right to someone in that industry), so they are written in batches, most-requested first.

## Consequences

- A world reads as the company it is named for. A hospital's engineers talk about the HL7 interface engine and prior-authorization queues; a state agency's talk about open-records deadlines and the mainframe batch window.
- Profiles list systems that cannot run yet. Until there are more twins, most of an industry's typical systems show as "no twin yet". The profile is still worth it, because the content in Gitea and Mattermost becomes industry-specific. Each new twin (identity, ticketing, email, wiki) then lights up in every profile at once.
- The built-in scenarios keep working in every industry, because the common core stays. Scenarios written for one industry can say so (`industries: [hospitals]`), and `mirror run` warns when a scenario's industry does not match the world's.
- The catalog gains industry-specific systems a profile needs but the catalog lacks (for example telecom billing and network inventory, or EHRs beyond the two it lists). They enter as candidates with no twin.
- Golden worlds and review pages per profile make the test suite and the review work grow with the number of profiles.

## Alternatives considered

- **Templates per industry** (`--template hospital`), each a fixed `mirror.yaml`. Simpler, but a template is a list of systems, not content; worlds would still read as a software company.
- **Content generated by a model at `world new`.** Varied and cheap to extend, but not deterministic, it needs a key and a network call at setup, and its output would have to be screened for placeholder text and tells on every install.
- **Industry as a set of tags** (`regulated`, `retail`, `public`) mixed freely. More flexible, but harder to make read right; mixed vocabularies are themselves a tell. Profiles can still share parts through YAML anchors.

## To verify

- The common-core rule keeps every built-in scenario passing with `scripted-good` in a world from each profile.
- A reviewer from the industry (or the owner) reads one generated world per profile and finds nothing that reads wrong.
- Generation time and world size stay within the current figures for the same headcount and history.

## Open questions for the owner

1. Which profiles come first? A suggestion: healthcare (hospitals), telecommunications, state government, federal government, retail, hotels, fitness apps, banking, insurance, logistics, manufacturing and utilities.
2. Should a profile's typical systems be proposed automatically, or only shown, so that `--industry` changes content and nothing else unless the user accepts the systems?
3. Is `mirror world add` wanted now, or later with the next twins?
4. Discovery changes the promise that real data never goes in, to "real names only when kept in review; real content never". Is that the line you want?
5. Should discovery come with the industry profiles, or after them? It needs the profiles' generator to follow a found shape, so building it first would mean building that generator first.
6. Which sources are in the first version? The suggestion is the agent's own deployment files and repository clones, which together give hostnames, tools and conventions.
7. Who signs off a scan of a company computer: the user alone, or the user with their security team's approval recorded in the project?
