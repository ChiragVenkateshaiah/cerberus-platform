.DEFAULT_GOAL := help

TF_DEV_DIR := terraform/envs/dev
TF_BOOTSTRAP_DIR := terraform/bootstrap

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

.PHONY: bootstrap-init bootstrap-plan bootstrap-apply
bootstrap-init: ## terraform init the state-backend bootstrap
	cd $(TF_BOOTSTRAP_DIR) && terraform init

bootstrap-plan: ## terraform plan the state-backend bootstrap
	cd $(TF_BOOTSTRAP_DIR) && terraform plan

bootstrap-apply: ## terraform apply the state-backend bootstrap
	cd $(TF_BOOTSTRAP_DIR) && terraform apply

.PHONY: dev-init dev-plan dev-apply dev-destroy
dev-init: ## terraform init the dev environment
	cd $(TF_DEV_DIR) && terraform init

dev-plan: ## terraform plan the dev environment
	cd $(TF_DEV_DIR) && terraform plan

dev-apply: ## terraform apply the dev environment
	cd $(TF_DEV_DIR) && terraform apply

dev-destroy: ## terraform destroy the dev environment
	cd $(TF_DEV_DIR) && terraform destroy

.PHONY: fmt
fmt: ## terraform fmt across the whole terraform/ tree
	terraform fmt -recursive terraform/

.PHONY: clean
clean: ## Remove local Terraform working state (not remote state)
	find terraform -type d -name ".terraform" -prune -exec rm -rf {} +
