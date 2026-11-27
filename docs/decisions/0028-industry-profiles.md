# 0028. Industry profiles shape the world

Status: Proposed.

## Context

`company.industry` in `mirror.yaml` is free text, and today it changes only two things: the suffix of a suggested company name and the two line items on the billing code's sample invoice. Every world is otherwise the same software company: the same repositories (`billing-service`, `platform-docs`, `data-pipeline`, `infra-config`, `customer-portal`, `ops-scripts`), the same kinds of issues and chat, the same roles.

So a world named "Halden Health" reads as a SaaS company with a hospital's name on it. A person setting up a world for their company has to describe it system by system, and an agent that knows what a hospital's engineering work looks like could notice that nothing here does. That mismatch is a tell.

The owner's proposal (2026-11-27): a user names their industry, and the mirror builds the environment a company in that industry would have. The user then adds their own specific tools.

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
