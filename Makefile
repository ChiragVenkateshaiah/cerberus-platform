.DEFAULT_GOAL := help

# Override with `make standing-plan TF_BIN=tofu` to use OpenTofu instead of Terraform.
TF_BIN ?= terraform
TF_STANDING_DIR := terraform/envs/dev-standing
TF_COMPUTE_DIR := terraform/envs/dev-compute
TF_BOOTSTRAP_DIR := terraform/bootstrap

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

.PHONY: bootstrap-init bootstrap-plan bootstrap-apply
bootstrap-init: ## terraform init the state-backend bootstrap
	cd $(TF_BOOTSTRAP_DIR) && $(TF_BIN) init

bootstrap-plan: ## terraform plan the state-backend bootstrap
	cd $(TF_BOOTSTRAP_DIR) && $(TF_BIN) plan

bootstrap-apply: ## terraform apply the state-backend bootstrap
	cd $(TF_BOOTSTRAP_DIR) && $(TF_BIN) apply

.PHONY: standing-init standing-plan standing-apply standing-destroy
standing-init: ## terraform init the CI-managed standing environment (S3/IAM/Glue/Athena/Lambda/orchestration)
	cd $(TF_STANDING_DIR) && $(TF_BIN) init

standing-plan: ## terraform plan the standing environment -- same plan GitHub Actions runs on PR
	cd $(TF_STANDING_DIR) && $(TF_BIN) plan

standing-apply: ## terraform apply the standing environment -- same apply GitHub Actions runs on merge to main
	cd $(TF_STANDING_DIR) && $(TF_BIN) apply

standing-destroy: ## terraform destroy the standing environment (rarely needed -- this is the always-on layer)
	cd $(TF_STANDING_DIR) && $(TF_BIN) destroy

.PHONY: compute-init compute-plan compute-apply compute-destroy
compute-init: ## terraform init the human-run compute environment (VPC NAT/EIP, EKS, Spark)
	cd $(TF_COMPUTE_DIR) && $(TF_BIN) init

compute-plan: ## terraform plan the compute environment -- spin up for a Spark exercise
	cd $(TF_COMPUTE_DIR) && $(TF_BIN) plan

compute-apply: ## terraform apply the compute environment -- spin up for a Spark exercise
	cd $(TF_COMPUTE_DIR) && $(TF_BIN) apply

compute-destroy: ## terraform destroy the compute environment -- tear down after a Spark exercise (cost discipline)
	cd $(TF_COMPUTE_DIR) && $(TF_BIN) destroy

.PHONY: fmt
fmt: ## terraform fmt across the whole terraform/ tree
	$(TF_BIN) fmt -recursive terraform/

.PHONY: clean
clean: ## Remove local Terraform working state (not remote state)
	find terraform -type d -name ".terraform" -prune -exec rm -rf {} +
