# sliderule-schema-server

A dedicated JSON-only CloudFront distribution that serves the SlideRule
schema endpoints. Separate from the web client's distribution — different
bucket, different distribution, different CORS and cache policy.

## URL / S3 / disk layout (all identical)

The publishable tree lives at
[`schema-endpoints/merged/source/`](schema-endpoints/merged/source/) and
mirrors the S3 bucket layout, which mirrors the public URL structure
**1:1 with no rewriting, no CloudFront Function, no Lambda@Edge**.
CloudFront takes the URL path, strips the leading `/`, and looks up that
exact key in the bucket.

`merged/` is an artifact produced by [`schema-endpoints/merge.py`](schema-endpoints/merge.py)
from [`schema-endpoints/authored/`](schema-endpoints/authored/) (human-edited)
and [`schema-endpoints/generated/`](schema-endpoints/generated/) (tool-emitted).
It is committed to git so reviewers see the S3-bound diff on every PR,
and `make verify` asserts it matches what `merge.py` would produce
today. See [`schema-endpoints/README.md`](schema-endpoints/README.md) for
the three-tier architecture.

```
schema-endpoints/merged/source/                   ← on disk in this repo
                                                  ← same keys in s3://sliderule-schema-test/
                                                  ← same paths at https://schema.testsliderule.org/
├── schema.json                                   (index of available domains)
└── schema/
    ├── core.json                                 (shared request parameters)
    ├── icesat2.json                              (ICESat-2 request parameters)
    ├── gedi.json                                 (GEDI request parameters)
    ├── swot.json                                 (not yet generated → 404)
    ├── cre.json                                  (not yet generated → 404)
    │
    ├── icesat2/
    │   ├── fields.json                           (selector listing)
    │   │
    │   ├── fields/                               ← columns added by *_fields selectors
    │   │   ├── atl03_ph.json
    │   │   ├── atl03_geo.json
    │   │   ├── atl03_corr.json
    │   │   ├── atl03_bckgrd.json
    │   │   ├── atl06.json
    │   │   ├── atl08.json
    │   │   ├── atl09.json
    │   │   └── atl13.json
    │   │
    │   └── output/                               ← per-API output column schemas
    │       ├── atl03x.json                       (base + fit/phoreal/yapc/atl24/atl13 mods)
    │       ├── atl06x.json                       (base land-ice segment columns)
    │       ├── atl08x.json                       (base land/veg segment columns)
    │       ├── atl13x.json                       (base inland-water columns)
    │       └── atl24x.json                       (base bathymetry photon columns)
    │
    └── gedi/
        ├── fields.json                           (future: GEDI selector listing)
        ├── fields/                               (future: GEDI *_fields selectors)
        └── output/
            └── gedil4ax.json                     (base GEDI L4A footprint columns)
```

Anything not present in the source tree (including `swot.json`, `cre.json`,
and any unpublished path) returns `HTTP 404` with body:

```json
{"error": "not yet generated"}
```

This is configured via CloudFront `custom_error_response` pointing at
`/errors/not-found.json`, which `make deploy` uploads alongside the schema
tree. The source of that body is
[`schema-endpoints/authored/errors/not-found.json`](schema-endpoints/authored/errors/not-found.json).

## Source files: where they come from

Every file served by the distribution starts life in
[`schema-endpoints/authored/`](schema-endpoints/authored/) (human-edited) or
[`schema-endpoints/generated/`](schema-endpoints/generated/) (tool-emitted).
[`schema-endpoints/merge.py`](schema-endpoints/merge.py) fuses the two into
`merged/`, which [`scripts/build.sh`](scripts/build.sh) copies verbatim into
`build/` for the S3 sync.

| Published URL                                 | In-repo source                                            | Origin in the sliderule repo                                            |
| --------------------------------------------- | --------------------------------------------------------- | ----------------------------------------------------------------------- |
| `/source/schema.json` (domain/API index)      | `schema-endpoints/authored/schema.json`                   | Hand-written in this repo                                               |
| `/source/schema/{core,icesat2,gedi}.json`     | Merged from `generated/<domain>/params.json` + `authored/<domain>/{structure,behavior}.json` | `generated/<domain>/params.json` will eventually come from the sliderule server's `/source/defaults` endpoint ([`packages/core/endpoints/defaults.lua`](../sliderule/packages/core/endpoints/defaults.lua)); hand-maintained for now |
| `/source/schema/icesat2/fields.json`          | `schema-endpoints/authored/icesat2/fields.json`           | Hand-written selector listing                                           |
| `/source/schema/icesat2/fields/<selector>.json` | `schema-endpoints/generated/icesat2/fields/<selector>.json` | `sliderule/schema_fields/fields_<selector>.json` (from `enumerate_h5_fields.py`) |
| `/source/schema/icesat2/output/<api>.json`    | `schema-endpoints/generated/icesat2/output/<api>.json`    | `sliderule/tmp_server_generated_schema_test/schema_<API>DataFrame.json` (from `test_server_generated_schema.sh`) |
| `/source/schema/gedi/output/gedil4ax.json`    | `schema-endpoints/generated/gedi/output/gedil4ax.json`    | `sliderule/tmp_server_generated_schema_test/schema_Gedi04aDataFrame.json` |

### Regenerating the source JSON

Field enumerations (granule-level HDF5 structure):

```bash
# From the sliderule repo:
cd ../sliderule
python scripts/download_h5_granules.py
python scripts/enumerate_h5_fields.py
# Output lands in sliderule/schema_fields/fields_*.json

# Mirror into this repo and re-merge:
cp ../sliderule/schema_fields/fields_*.json schema-endpoints/generated/icesat2/fields/
python3 schema-endpoints/merge.py
```

Output DataFrame schemas (what the server actually returns per API):

```bash
# From the sliderule repo:
cd ../sliderule
bash scripts/test_server_generated_schema.sh
# Output lands in sliderule/tmp_server_generated_schema_test/

# Mirror into this repo and re-merge:
cp ../sliderule/tmp_server_generated_schema_test/schema_Atl03DataFrame.json schema-endpoints/generated/icesat2/output/atl03x.json
cp ../sliderule/tmp_server_generated_schema_test/schema_Atl06DataFrame.json schema-endpoints/generated/icesat2/output/atl06x.json
# ... etc for atl08x, atl13x, atl24x, gedil4ax (Gedi04aDataFrame.json)
python3 schema-endpoints/merge.py
```

Request-parameter schemas (`schema/core.json`, `icesat2.json`, `gedi.json`):

```bash
# Against a running sliderule server:
curl http://<server>:9081/source/defaults | jq '.core'    > schema-endpoints/generated/core/params.json
curl http://<server>:9081/source/defaults | jq '.icesat2' > schema-endpoints/generated/icesat2/params.json
curl http://<server>:9081/source/defaults | jq '.gedi'    > schema-endpoints/generated/gedi/params.json
python3 schema-endpoints/merge.py
```

Commit the resulting `schema-endpoints/merged/` diff. `make verify`
will flag any drift in CI if you forget.

## Environments

| Environment   | Domain                     | S3 bucket               |
| ------------- | -------------------------- | ----------------------- |
| test          | `schema.testsliderule.org` | `sliderule-schema-test` |
| prod (future) | `schema.slideruleearth.io` | `sliderule-schema-prod` |

Per-environment wrapper targets in the Makefile
(`deploy-to-testsliderule`, `deploy-to-slideruleearth`, etc.) carry the
`DOMAIN` / `S3_BUCKET` / `DOMAIN_APEX` variables, matching the pattern in
`sliderule-web-client/Makefile`. `DISTRIBUTION_ID` is auto-resolved from the
domain alias via `aws cloudfront list-distributions`.

## Makefile targets

```
make build                       Run merge, then stage schema-endpoints/merged/
                                 into build/
make clean                       Remove build/
make verify                      Assert merged/ matches merge.py output
                                 (run after any edit to authored/ or generated/)

make live-update                 Verify + build + aws s3 sync + invalidation
                                 (requires DOMAIN + S3_BUCKET + DOMAIN_APEX)
make deploy                      Alias for live-update

make terraform-apply             Create/update distribution + bucket + DNS
make terraform-destroy           Tear down the above

make smoketest                   curl the public endpoints and verify
                                 status + Content-Type + CORS

# Per-env wrappers (no variables needed):
make deploy-to-testsliderule     Infra + content at schema.testsliderule.org
make live-update-testsliderule   Content only (assumes infra exists)
make destroy-testsliderule       Tear down the test env
```

## Repo artifacts policy

[`schema-endpoints/merged/`](schema-endpoints/merged/) is a build
artifact — output of [`merge.py`](schema-endpoints/merge.py) from
`authored/` + `generated/` — that is nevertheless **committed to git**.
Two concrete reasons:

1. **Paired-diff review.** Every source edit under `authored/` or
   `generated/` is committed alongside the resulting `merged/` diff, so
   reviewers see the exact bytes going to S3 next to the edit that
   caused them. A coupling added in `authored/icesat2/behavior.json`
   shows up paired with the new field appearing in the correct param in
   the merged `source/schema/icesat2.json` — catches translation bugs
   (wrong group, wrong position) that the source diff alone wouldn't
   surface.

2. **A simple drift check.** `make verify` asserts `git diff --quiet
   schema-endpoints/merged/` after running `merge.py`. If someone edits
   `authored/` or `generated/` without regenerating, the diff is
   non-empty and verify fails. No schema-comparison logic needed — just
   git. The merge is deterministic (no `sort_keys`, `indent=2`, trailing
   newline) so the git-diff check is reliable.

**`terraform/.terraform.lock.hcl` is also committed** (per HashiCorp
recommendation): without it, `terraform init` picks the latest provider
matching the version constraint and different teammates resolve to
different SHAs. Committing the lock pins the whole team to the same
provider build.

**Ignored (see [.gitignore](.gitignore)):**

- `/build/` — downstream of `merged/` (pure `cp -R`). No new review
  signal, regenerated on every `make build`.
- `**/.terraform/*`, `*.tfstate*`, `*.tfplan`, `*.tfvars` — ephemeral
  or secret-bearing. Terraform state lives in S3 per
  [terraform/backend.tf](terraform/backend.tf).
- `__pycache__/`, `*.pyc`, `.DS_Store`, etc. — per-user / per-OS
  noise.

**Workflow implication.** Edits to `authored/` or `generated/` are
two-step commits: change the source, `python3 schema-endpoints/merge.py`,
`git add` both trees, commit together. The friction is deliberate —
it's the price of the paired-diff review benefit.

## Distribution configuration

- **Origin:** S3 bucket, fronted by an Origin Access Identity. The bucket is
  private; only CloudFront can read it.
- **Path mapping:** 1:1. CloudFront strips the leading `/` from the request
  path and looks for that exact key in the bucket. No CloudFront Functions,
  no Lambda@Edge, no SPA fallback.
- **Content-Type:** `aws s3 sync` auto-detects `application/json` from the
  `.json` extension — no per-file content-type flag needed.
- **CORS:** `Access-Control-Allow-Origin: *`, `Methods: GET, OPTIONS`,
  `Headers: *`. Applied via a CloudFront response headers policy so every
  response (including errors) gets the CORS headers.
- **Cache:** `Cache-Control: max-age=60` while iterating. Raise once the
  schemas stabilise.
- **TLS:** ACM certificate for `schema.<apex>`, DNS-validated against the
  existing Route 53 zone for the apex. TLS 1.2+.
- **Errors:** 403/404 from S3 → 404 from CloudFront with body
  `/errors/not-found.json` (`{"error": "not yet generated"}`). This covers
  `swot.json`, `cre.json`, and any other unpublished path.

## Smoke tests

`make smoketest` runs these against `https://$DOMAIN`:

```
curl  /source/schema.json                                       -> 200 application/json
curl  /source/schema/core.json                                  -> 200 application/json
curl  /source/schema/icesat2.json                               -> 200 application/json
curl  /source/schema/gedi.json                                  -> 200 application/json

curl  /source/schema/icesat2/fields.json                        -> 200 application/json
curl  /source/schema/icesat2/fields/atl03_ph.json               -> 200 application/json
curl  /source/schema/icesat2/fields/atl03_geo.json              -> 200 application/json
curl  /source/schema/icesat2/fields/atl03_corr.json             -> 200 application/json
curl  /source/schema/icesat2/fields/atl03_bckgrd.json           -> 200 application/json
curl  /source/schema/icesat2/fields/atl06.json                  -> 200 application/json
curl  /source/schema/icesat2/fields/atl08.json                  -> 200 application/json
curl  /source/schema/icesat2/fields/atl09.json                  -> 200 application/json
curl  /source/schema/icesat2/fields/atl13.json                  -> 200 application/json

curl  /source/schema/icesat2/output/atl03x.json                 -> 200 application/json
curl  /source/schema/icesat2/output/atl06x.json                 -> 200 application/json
curl  /source/schema/icesat2/output/atl08x.json                 -> 200 application/json
curl  /source/schema/icesat2/output/atl13x.json                 -> 200 application/json
curl  /source/schema/icesat2/output/atl24x.json                 -> 200 application/json

curl  /source/schema/gedi/output/gedil4ax.json                  -> 200 application/json

curl  /source/schema/swot.json                                  -> 404 application/json
curl  /source/schema/cre.json                                   -> 404 application/json

curl -H "Origin: https://example.com" /source/schema.json       -> header Access-Control-Allow-Origin: *
```

## First-time setup

1. Populate `schema-endpoints/authored/` and `schema-endpoints/generated/`
   with the files listed in the "Source files" table above. Anything not
   present will simply 404 in production.
2. `python3 schema-endpoints/merge.py` to produce
   `schema-endpoints/merged/` (and commit the result).
3. `make deploy-to-testsliderule`
   - Terraform stands up the bucket, distribution, ACM cert, and Route 53
     record.
   - The same wrapper then runs `live-update`, which verifies, stages,
     and syncs the JSON tree and kicks off an invalidation.
4. `make smoketest DOMAIN=schema.testsliderule.org`

CloudFront distribution creation takes a few minutes; DNS propagation can
take a few more. If `smoketest` fails immediately after the first apply,
give it 5–10 minutes and re-run.

## Re-deploy after changes to the schema files

```bash
# After editing anything under schema-endpoints/authored/ or schema-endpoints/generated/:
python3 schema-endpoints/merge.py      # refresh merged/, commit the diff
make live-update-testsliderule         # verify + build + sync + invalidate
make smoketest DOMAIN=schema.testsliderule.org
```

## Configuration surface

- `DOMAIN`, `S3_BUCKET`, `DOMAIN_APEX` — set by the per-env wrapper
  targets, or overrideable on the command line for ad-hoc deploys.
- `DISTRIBUTION_ID` — looked up from the `DOMAIN` alias; no manual input.
- `terraform/backend.tf` — state is stored in
  `s3://sliderule/tf-states/schema-server.tfstate` with per-domain
  workspaces, mirroring the web client's backend layout.
