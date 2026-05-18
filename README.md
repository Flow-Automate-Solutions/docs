# magic-cms-docs

Two Mintlify projects served from this one repo.

| Project | Directory | URL (target) | Audience | Auth |
|---|---|---|---|---|
| External (Storefront API) | [external/](./external) | developers.magic-cms.com | Customers, storefront integrators | Public |
| Internal API | [internal/](./internal) | docs-internal.magic-cms.com | Magic CMS team | OAuth (configured in Mintlify dashboard) |

Each subdirectory has its own `docs.json` and is wired up as an independent Mintlify project pointed at that subdirectory. Pushes that only touch one subdirectory only rebuild that project.

## Source of truth

API reference pages are generated from OpenAPI specs in [_shared/](./_shared):

- `openapi-public.json` — subset of endpoints reachable via storefront API keys (rendered into the external docs)
- `openapi-internal.json` — full backend surface used by the dashboard (rendered into the internal docs)

Both specs are intended to be emitted by a generator script in `magic-cms-scripts/` (TODO) that introspects the Pydantic models in `magic-cms-catalog-serverless-apis/` and `magic-cms-common-serverless-apis/`. Until that lands, the files here are hand-written stubs with a handful of representative operations.

**Do not hand-edit field descriptions in the JSON files once the generator is live — they get overwritten on each regen. Edit the Pydantic models instead** (`Field(description="...")`).

## Local dev

```bash
cd external && mint dev   # serve external on localhost:3000
cd internal && mint dev   # serve internal on localhost:3000
```

Run them in separate terminals if you want both up at once (Mintlify picks a free port for the second one).

Install the CLI once with `npm i -g mint`.

## Mintlify dashboard setup

For each project:

1. Create a new Mintlify project pointing at this repo.
2. Set **Repository → Subdirectory** to `external` or `internal`.
3. Add a custom domain in **Settings → Domains**.
4. For the internal project, enable authentication under **Settings → Authentication** (OAuth via Google/Azure AD or JWT against FlowAutomate).

Reference: <https://mintlify.com/docs/settings>.
