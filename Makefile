.DEFAULT_GOAL := help

# Override with `make standing-plan TF_BIN=tofu` to use OpenTofu instead of Terraform.
TF_BIN ?= terraform

# Every target runs as cerberus-admin unless the shell already sets a
# profile (`AWS_PROFILE=other make ...` still wins). Terraform's S3 backend
# and providers read it from the environment; without it, a shell with no
# profile set fails with "No valid credential sources found" (twice on
# 2026-10-08). orchestration/exercise.sh sets the same profile itself.
export AWS_PROFILE ?= cerberus-admin
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

.PHONY: exercise exercise-check
exercise: ## one-command compute exercise: apply -> run -> collect -> destroy (orchestration/exercise.sh; ARGS="--generate 1000000")
	orchestration/exercise.sh $(ARGS)

exercise-check: ## read-only preflight for an exercise: no cluster, empty dev-compute state, nothing running
	orchestration/exercise.sh --check

.PHONY: grafana-up grafana-down grafana-logs grafana-token
# up.sh looks up the AMP endpoint and assumes cerberus-grafana-read (ADR 0024).
# down and logs only need placeholders to satisfy the compose interpolation.
GRAFANA_COMPOSE := docker compose -f observability/grafana/compose.yaml --env-file observability/grafana/.env
GRAFANA_STUB_ENV := AMP_URL=unused AWS_ACCESS_KEY_ID=unused AWS_SECRET_ACCESS_KEY=unused AWS_SESSION_TOKEN=unused
grafana-up: ## start the local Grafana on 127.0.0.1:3000 with short-lived cerberus-grafana-read credentials (ADR 0024; needs observability/grafana/.env)
	@test -f observability/grafana/.env || { echo "create observability/grafana/.env (see observability/grafana/.env.example)"; exit 1; }
	@observability/grafana/up.sh

grafana-down: ## stop and remove the local Grafana container (keeps the data volume and repo files)
	$(GRAFANA_STUB_ENV) $(GRAFANA_COMPOSE) down

grafana-logs: ## follow the local Grafana logs
	$(GRAFANA_STUB_ENV) $(GRAFANA_COMPOSE) logs -f grafana

grafana-token: ## make the Grafana service account and its 30-day annotation token (needs grafana-up)
	@observability/grafana/token.sh

.PHONY: demo-forward
demo-forward: ## port-forward the agent UI (:9090) and the current Spark driver UI (:4040) to localhost (ADR 0022)
	@observability/demo/forward.sh

.PHONY: fmt
fmt: ## terraform fmt across the whole terraform/ tree
	$(TF_BIN) fmt -recursive terraform/

.PHONY: clean
clean: ## Remove local Terraform working state (not remote state)
	find terraform -type d -name ".terraform" -prune -exec rm -rf {} +
