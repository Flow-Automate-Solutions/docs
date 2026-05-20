# magic-cms-docs

Two Mintlify projects served from this one repo.

| Project | Directory | URL (target) | Audience | Auth |
|---|---|---|---|---|
| External (Storefront API) | [external/](./external) | developers.magic-cms.com | Customers, storefront integrators | Public |
| Internal API | [internal/](./internal) | docs-internal.magic-cms.com | Magic CMS team | OAuth (configured in Mintlify dashboard) |

Each subdirectory has its own `docs.json` and is wired up as an independent Mintlify project pointed at that subdirectory. Pushes that only touch one subdirectory only rebuild that project.

## Source of truth

API reference pages are generated from OpenAPI specs in [_shared/](./_shared).

Per-service input files:

- `openapi-*-serverless.json` (for example `openapi-catalog-serverless.json`, `openapi-inventory-serverless.json`)

Generated output files:

- `openapi-internal.json` — merged internal API surface used by the dashboard docs
- `openapi-public.json` — derived from internal by keeping only operations tagged `public`

Generation is done by:

- `python tools/build_openapi.py`

Conflict policy is fail-fast:

- if two inputs define the same `path + method` differently, generation fails
- if two inputs define the same component key differently, generation fails

This keeps ownership per service explicit and prevents accidental schema overrides.

**Do not hand-edit generated files (`openapi-internal.json`, `openapi-public.json`) — they are overwritten on each regeneration.** Update the per-service source specs instead.

### Public tag convention

To expose an operation in `openapi-public.json`, include `public` in the operation `tags` list.

Example:

```json
{
  "tags": ["public", "Products"]
}
```

## Local dev

```bash
cd external && mint dev   # serve external on localhost:3000
cd internal && mint dev   # serve internal on localhost:3000
```

Run them in separate terminals if you want both up at once (Mintlify picks a free port for the second one).

Install the CLI once with `npm i -g mint`.

## Regenerate OpenAPI locally

```bash
python tools/build_openapi.py
```

This script updates:

- `_shared/openapi-internal.json`
- `_shared/openapi-public.json`

The docs repo CI workflow (`.github/workflows/build-openapi.yml`) runs the same command and fails if generated output is not committed.

## Mintlify dashboard setup

For each project:

1. Create a new Mintlify project pointing at this repo.
2. Set **Repository → Subdirectory** to `external` or `internal`.
3. Add a custom domain in **Settings → Domains**.
4. For the internal project, enable authentication under **Settings → Authentication** (OAuth via Google/Azure AD or JWT against FlowAutomate).

Reference: <https://mintlify.com/docs/settings>.
