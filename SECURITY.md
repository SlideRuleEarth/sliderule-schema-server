# Security policy

## Reporting a vulnerability

If you believe you've found a security issue in sliderule-schema-server
— whether in the served content, the merge pipeline, the Terraform
infrastructure, or the packaged Claude skill — **please do not open a
public GitHub issue**.

Instead, email **security@mail.slideruleearth.io** with:

- A short description of the issue
- Steps to reproduce
- The impact you believe it has
- (Optional) A suggested fix

We'll acknowledge within 5 business days and keep you updated as we
triage, fix, and disclose.

Credible reports that demonstrate exploitable impact will be
acknowledged in the release notes unless you prefer otherwise.

## Scope

### In scope

- The schema distribution at `https://schema.testsliderule.org/` and
  any production variant.
- The merge pipeline (`schema-endpoints/merge.py` and the tree it
  produces).
- Terraform in `terraform/` — the CloudFront / S3 / ACM / Route 53
  wiring.
- The `sliderule-schema` Claude skill in [skills/sliderule-schema/](skills/sliderule-schema/).

### Out of scope

- Rate-limiting / denial-of-service. CloudFront has standard WAF
  thresholds; reports of "I can make it slow with 10k requests/s"
  are expected behaviour.
- Issues in SlideRule itself — use the
  [sliderule repository](https://github.com/SlideRuleEarth/sliderule)
  instead.
- Issues in the narrative docs at docs.slideruleearth.io — report to
  the web-client / docs repos.

## What we protect

- **No secrets in the repo.** The git history is audited (gitleaks,
  run against the whole history) and CI includes drift checks for
  committed artifacts. If you spot something that looks like a
  leaked credential in the repo, please email rather than post
  publicly; we'll rotate immediately.
- **Terraform + lock file commit.** `terraform/.terraform.lock.hcl`
  pins the AWS provider SHA so fresh clones reproduce the same
  provider build.
- **Static-only serving surface.** CloudFront serves JSON from a
  private S3 bucket; there is no server-side execution, no auth
  cookie path, no query-string logic.
