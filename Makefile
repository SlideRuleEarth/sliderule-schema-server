####################################################################################################
#
# SlideRule Schema Server — publishes schema-endpoints/source/ to a JSON-only CloudFront
# distribution. The source tree mirrors the S3 layout (and public URLs) 1:1, so build/deploy
# is a straight copy + sync + invalidation.
#
# Target naming, variable names, and per-env wrapper targets mirror sliderule-web-client/Makefile
# so that `make deploy-to-testsliderule` feels like a sibling of the web client's
# `make deploy-client-to-testsliderule`.
#
####################################################################################################

SHELL := /bin/bash
ROOT  = $(shell pwd)

# DOMAIN / S3_BUCKET / DOMAIN_APEX are supplied by wrapper targets (or the environment).
DOMAIN          ?=
DOMAIN_ROOT     = $(firstword $(subst ., ,$(DOMAIN)))
DOMAIN_APEX     ?= $(DOMAIN)
S3_BUCKET       ?=
DISTRIBUTION_ID = $(shell aws cloudfront list-distributions --query "DistributionList.Items[?Aliases.Items[0]=='$(DOMAIN)'].Id" --output text)

BUILD_DIR = $(ROOT)/build
SRC_DIR   = $(ROOT)/schema-endpoints

.PHONY: help build clean deploy smoketest verify tf-fmt tf-fmt-check terraform-apply terraform-destroy check-vars \
        deploy-to-testsliderule deploy-to-slideruleearth \
        destroy-testsliderule destroy-slideruleearth \
        live-update-testsliderule live-update-slideruleearth

help: ## That's me!
	@printf "\033[37m%-40s\033[0m %s\n" "#-----------------------------------------------------------------------------------------"
	@printf "\033[37m%-40s\033[0m %s\n" "# Makefile Help"
	@printf "\033[37m%-40s\033[0m %s\n" "#-----------------------------------------------------------------------------------------"
	@grep -E '^[a-zA-Z_-].+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-40s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo DOMAIN:          $(DOMAIN)
	@echo DOMAIN_ROOT:     $(DOMAIN_ROOT)
	@echo DOMAIN_APEX:     $(DOMAIN_APEX)
	@echo S3_BUCKET:       $(S3_BUCKET)
	@echo DISTRIBUTION_ID: $(DISTRIBUTION_ID)

clean: ## Remove the build/ tree
	rm -rf $(BUILD_DIR)

build: ## Run merge, then stage schema-endpoints/merged/ into build/
	@bash $(ROOT)/scripts/build.sh

verify: tf-fmt-check ## Check merged/ is up to date + Terraform is formatted
	@python3 schema-endpoints/merge.py > /dev/null
	@if ! git diff --quiet schema-endpoints/merged/; then \
	  echo "❌ merged/ is out of date. Run 'python3 schema-endpoints/merge.py' and commit the result."; \
	  git diff --stat schema-endpoints/merged/; \
	  exit 1; \
	fi
	@echo "✅ merged/ is up to date with authored/ + generated/"

tf-fmt: ## Format all Terraform files in place
	terraform fmt -recursive terraform/

tf-fmt-check: ## Verify Terraform formatting (fails if drift; CI gate)
	@terraform fmt -check -recursive terraform/ > /dev/null || { \
	  echo "❌ Terraform formatting drift. Run 'make tf-fmt' and commit."; \
	  terraform fmt -check -diff -recursive terraform/ | head -40; \
	  exit 1; \
	}
	@echo "✅ Terraform formatting clean"

# ---- Sync + invalidate ----------------------------------------------------------------------------

upload: ## Sync build/ to s3://$(S3_BUCKET)/ (Content-Type auto-detected from .json)
	@test -d $(BUILD_DIR) || (echo "❌ $(BUILD_DIR) missing — run 'make build' first"; exit 1)
	export AWS_MAX_ATTEMPTS=5 AWS_RETRY_MODE=standard && \
	echo "Syncing $(BUILD_DIR) -> s3://$(S3_BUCKET)/" && \
	aws s3 sync $(BUILD_DIR)/ s3://$(S3_BUCKET)/ \
		--delete \
		--cache-control "max-age=60"

invalidate: ## Invalidate /source/schema/* on the CloudFront distribution
	export AWS_MAX_ATTEMPTS=5 AWS_RETRY_MODE=standard && \
	echo "Invalidating CloudFront distribution $(DISTRIBUTION_ID)..." && \
	aws cloudfront create-invalidation --distribution-id $(DISTRIBUTION_ID) --paths "/source/*" "/errors/*"

live-update: check-vars verify build upload invalidate ## Verify, build, upload, and invalidate

deploy: live-update ## Alias for live-update (build + upload + invalidate)

# ---- Terraform (distribution lifecycle) -----------------------------------------------------------

terraform-apply: ## Create/update the bucket + distribution + DNS via Terraform
	mkdir -p terraform/ && cd terraform/ && terraform init && \
	(terraform workspace select $(DOMAIN)-schema-server || terraform workspace new $(DOMAIN)-schema-server) && \
	terraform validate && \
	terraform apply \
		-var domainName=$(DOMAIN) \
		-var domainApex=$(DOMAIN_APEX) \
		-var domain_root=$(DOMAIN_ROOT) \
		-var s3_bucket_name=$(S3_BUCKET)

terraform-destroy: ## Tear down the bucket + distribution + DNS via Terraform
	cd terraform/ && terraform init && \
	(terraform workspace select $(DOMAIN)-schema-server || terraform workspace new $(DOMAIN)-schema-server) && \
	terraform destroy \
		-var domainName=$(DOMAIN) \
		-var domainApex=$(DOMAIN_APEX) \
		-var domain_root=$(DOMAIN_ROOT) \
		-var s3_bucket_name=$(S3_BUCKET)

# ---- Smoke tests ----------------------------------------------------------------------------------

smoketest: ## curl the public endpoints and verify status + Content-Type + CORS
	@DOMAIN=$(DOMAIN) bash $(ROOT)/scripts/smoketest.sh

# ---- Per-environment wrappers (mirror sliderule-web-client conventions) ---------------------------

deploy-to-testsliderule: ## Create infra + upload content at schema.testsliderule.org
	make terraform-apply DOMAIN=schema.testsliderule.org S3_BUCKET=sliderule-schema-test DOMAIN_APEX=testsliderule.org && \
	make live-update     DOMAIN=schema.testsliderule.org S3_BUCKET=sliderule-schema-test DOMAIN_APEX=testsliderule.org

live-update-testsliderule: ## Build + upload + invalidate at schema.testsliderule.org
	make live-update DOMAIN=schema.testsliderule.org S3_BUCKET=sliderule-schema-test DOMAIN_APEX=testsliderule.org

destroy-testsliderule: ## Tear down schema.testsliderule.org infrastructure
	make terraform-destroy DOMAIN=schema.testsliderule.org S3_BUCKET=sliderule-schema-test DOMAIN_APEX=testsliderule.org

deploy-to-slideruleearth: ## Create infra + upload content at schema.slideruleearth.io
	make terraform-apply DOMAIN=schema.slideruleearth.io S3_BUCKET=sliderule-schema-prod DOMAIN_APEX=slideruleearth.io && \
	make live-update     DOMAIN=schema.slideruleearth.io S3_BUCKET=sliderule-schema-prod DOMAIN_APEX=slideruleearth.io

live-update-slideruleearth: ## Build + upload + invalidate at schema.slideruleearth.io
	make live-update DOMAIN=schema.slideruleearth.io S3_BUCKET=sliderule-schema-prod DOMAIN_APEX=slideruleearth.io

destroy-slideruleearth: ## Tear down schema.slideruleearth.io infrastructure
	make terraform-destroy DOMAIN=schema.slideruleearth.io S3_BUCKET=sliderule-schema-prod DOMAIN_APEX=slideruleearth.io

# ---- Validation -----------------------------------------------------------------------------------

check-vars:
	@test -n "$(DOMAIN)"          || (echo "❌ DOMAIN is not set"; exit 1)
	@test -n "$(S3_BUCKET)"       || (echo "❌ S3_BUCKET is not set"; exit 1)
	@test -n "$(DOMAIN_APEX)"     || (echo "❌ DOMAIN_APEX is not set"; exit 1)
	@test -n "$(DISTRIBUTION_ID)" || (echo "❌ DISTRIBUTION_ID could not be resolved for DOMAIN=$(DOMAIN)"; exit 1)
	@echo "✅ All required variables are set:"
	@echo "   DOMAIN          = $(DOMAIN)"
	@echo "   DOMAIN_APEX     = $(DOMAIN_APEX)"
	@echo "   S3_BUCKET       = $(S3_BUCKET)"
	@echo "   DISTRIBUTION_ID = $(DISTRIBUTION_ID)"
