# App catalog

An index of enterprise apps, so that naming an app while defining or importing a world resolves to a known entry. It is not a list of twins: today only Gitea and Mattermost can be built.

- `apps.csv`: 500 candidates in 18 categories and three tiers.
- `backlog.csv`: about 290 more.
- `overrides.yaml`: aliases, kinds and hostname patterns for entries that need them, and the two buildable twins.

**Every row is unverified.** Before relying on one, check that the product still exists under that name. To add or correct an entry, open a pull request against one file; CI checks the schema, slug uniqueness and alias collisions.

**Trademarks.** Product names in this folder are trademarks of their owners and are used only to identify those products. No affiliation or endorsement is implied. The catalog holds names and public facts only: no logos, screenshots or copied documentation.
