# Contributing

Thanks for your interest in sliderule-schema-server. This repo is the
source tree and deploy pipeline for the static JSON distribution at
`schema.testsliderule.org` — what the SlideRule ecosystem treats as
the authoritative schema surface for request parameters, output
columns, and HDF5 field selectors.

## TL;DR workflow

```bash
git clone git@github.com:SlideRuleEarth/sliderule-schema-server.git
cd sliderule-schema-server

# Edit something under schema-endpoints/authored/ or schema-endpoints/generated/
python3 schema-endpoints/merge.py        # refresh merged/
make verify                              # asserts merged/ + tf fmt
git add schema-endpoints/                # include both the source edit AND merged/
git commit -m "your message"
git push
# open a PR into main
```

That's the whole loop. The rest of this doc explains why each step
exists and what can go wrong.

## Why paired commits (authored/ + merged/ together)

`schema-endpoints/merged/` is a build artifact committed to git —
unusual, but load-bearing. See the
[Repo artifacts policy](README.md#repo-artifacts-policy) section in
the top-level README for the full rationale. Short version: reviewers
see the exact bytes going to S3 in the same diff as the source edit
that caused them. `make verify` fails if you edit
`authored/`/`generated/` without re-running the merge.

## Setting up your environment

### Required

- **git** (obviously)
- **Python 3.11+** — `merge.py` uses modern type hints (`list[str]`,
  `dict | None`) and `Path.is_file()`.
- **Terraform 1.5+** — `required_version = ">= 1.5.0"` in
  [terraform/versions.tf](terraform/versions.tf).
- **AWS CLI** — only for actual deploys. Cloning + running `make verify`
  doesn't need AWS.

### Optional

- **make** — thin wrapper around the scripts; you can also invoke
  scripts directly.
- **jq** — nice for poking at JSON responses.
- **gitleaks** — used in the pre-merge secret audit; run with
  `docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:latest git /repo`.

## The three-tier content model

```
schema-endpoints/
├── authored/     humans edit here
├── generated/    tools emit here (hand-maintained for now; long-term from /source/defaults)
├── merged/       merge.py output — committed artifact
└── merge.py
```

- `authored/<domain>/{structure,behavior}.json` control how params
  are grouped and which couplings they carry.
- `generated/<domain>/params.json` is the factual parameter baseline.
- `generated/{icesat2,gedi}/fields/<sel>.json` are produced by
  `scripts/enumerate_h5_fields.py` in THIS repo (adopted in Apr 2026
  from the sliderule server repo; extended at adoption time with
  ATL24 and GEDI support). `generated/<domain>/output/<api>.json`
  is still produced by `test_server_generated_schema.sh` in the
  sliderule server repo and mirrored here.

Read [schema-endpoints/README.md](schema-endpoints/README.md) for
the full split-rule explanation (which fields go where and why).

## Pre-flight validations

`merge.py` fails loudly — before touching `merged/` — on any of
these:

- JSON parse error anywhere under `authored/` or `generated/`
- Advertised `param_count` in the index disagrees with the generated
  baseline
- A stage-source file is missing or not a regular file
- An advertised URL disagrees with its label context (e.g.
  `gedi.schema_url` pointing at `core.json`)
- An advertised URL doesn't resolve to a file the staging pipeline
  would publish
- A parameter in `structure.json` isn't in `generated/params.json`
  (or vice versa)
- A parameter has a behavior entry but no factual entry

A failing validation leaves your committed `merged/` tree untouched.
Fix the source, re-run, commit.

## Running the test deploy

If you have AWS credentials with the right profile:

```bash
make deploy-to-testsliderule       # stands up infra + content
make smoketest-testsliderule       # verify the deployed distribution
```

CloudFront distribution creation takes a few minutes; DNS propagation
a few more. If smoketest fails right after the first apply, wait
5–10 minutes and re-run.

## Reviewing a PR

Checklist for reviewers:

- [ ] `make verify` passes (CI should enforce this)
- [ ] `merged/` diff matches intent of the authored/generated edit
- [ ] No new untracked files that should have been committed
- [ ] Terraform changes, if any, run through `terraform fmt` and
      `terraform validate`
- [ ] If a new domain or API was added, `schema.json` was updated
      (via the authored/ index) and its advertised URLs all resolve

## Style

- **JSON formatting:** `merge.py` uses `indent=2`, no `sort_keys`,
  trailing newline. The generators should match. Inconsistent
  formatting will show up as unnecessary diff noise in `merged/`.
- **Commit messages:** first line is a short summary ("area: what
  changed"). Body explains *why*, not *what* — the diff shows what.
  Reference the issue or review finding that prompted the change
  where applicable.
- **Python:** the current codebase targets Python 3.11+. Type hints
  are encouraged. Keep `merge.py` readable — it's the kind of file
  future maintainers grep into, not just execute.

## Getting help

- Open a GitHub issue for bugs or proposed changes.
- Email **security@mail.slideruleearth.io** for security issues (see
  [SECURITY.md](SECURITY.md)).
- For SlideRule usage questions, try the `sliderule-docsearch` or
  `nsidc-reference` skills — this repo's concern is the schema
  surface itself, not how to use SlideRule.
