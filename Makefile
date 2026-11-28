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
TF_CONSOLE_DIR := terraform/envs/dev-console
TF_LAUNCH_DIR := terraform/envs/dev-launch
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

.PHONY: console-plan console-session console-check console-destroy
# dev-console has a partial backend (the state bucket name holds the account
# ID, which a committed file must not). orchestration/console_init.sh reads the
# account ID with one sts:GetCallerIdentity call and passes the backend
# settings as -backend-config flags; the session, check and destroy scripts
# use the same helper, so all of them agree.
MINUTES ?= 90
console-plan: ## READ-ONLY, owner-run: init dev-console against the shared state backend, then terraform plan (applies nothing)
	@TF_BIN=$(TF_BIN) orchestration/console_init.sh && \
	$(TF_BIN) -chdir=$(TF_CONSOLE_DIR) plan

console-session: ## AWS WRITE, owner-run: one live Grafana session -- preflight, y/N, apply, countdown, destroy from an EXIT trap, check (MINUTES=90, 1 to 120; ARGS=--yes; about 0.068 USD/hour)
	TF_BIN=$(TF_BIN) orchestration/console_session.sh --minutes $(MINUTES) $(ARGS)

console-check: ## READ-ONLY: every session count must be 0 (instances, distributions, VPC origins, Cognito client, IAM, SG, NAT route, live.json, state)
	TF_BIN=$(TF_BIN) orchestration/console_check.sh

console-destroy: ## AWS WRITE, owner-run: destroy dev-console after an interrupted session (-refresh=false retry, ENI wait), then console-check
	TF_BIN=$(TF_BIN) orchestration/console_session.sh --destroy

# Live-check harness (plan docs/plans/2026-11-15-live-check-harness.md). Read-only. The
# standing URL comes from the dev-standing outputs; nothing here writes to AWS.
.PHONY: console-wait console-verify-public console-verify
console-wait: ## READ-ONLY, no password: wait for live.json 200 and ring the bell (ARGS=--gone waits for it to go)
	@cd console && uv run --no-project --python 3.12 python -m cerberus_live_check watch \
	  --standing "$$($(TF_BIN) -chdir=../$(TF_STANDING_DIR) output -raw console_url)" $(ARGS)

console-verify-public: ## READ-ONLY, no password, Claude-safe: headers, 401/404, CSP, TLS, live.json (ARGS=--no-wait skips the wait for a session)
	@cd console && uv run --no-project --python 3.12 --with playwright==1.65.1 --with pytest==9.1.1 \
	  python -m cerberus_live_check verify --no-sign-in \
	  --standing "$$($(TF_BIN) -chdir=../$(TF_STANDING_DIR) output -raw console_url)" $(ARGS)

console-verify: ## READ-ONLY, owner-run in your own terminal: public checks plus the console-check sign-in checks; asks for the password
	@cd console && uv run --no-project --python 3.12 --with playwright==1.65.1 --with pytest==9.1.1 \
	  python -m cerberus_live_check verify \
	  --standing "$$($(TF_BIN) -chdir=../$(TF_STANDING_DIR) output -raw console_url)" $(ARGS)

.PHONY: exercise exercise-check
exercise: ## one-command compute exercise: apply -> run -> collect -> destroy (orchestration/exercise.sh; ARGS="--generate 1000000")
	orchestration/exercise.sh $(ARGS)

exercise-check: ## read-only preflight for an exercise: no cluster, empty dev-compute state, nothing running
	orchestration/exercise.sh --check

.PHONY: verify verify-full
verify: ## OFFLINE, no AWS: the standard checks for a change (ruff, console/status/grafana tests, terraform fmt, console JavaScript, shell syntax, account-number scan); skips what is not on the branch
	orchestration/verify.sh

verify-full: ## OFFLINE, Docker: verify plus the alert-rule, e2e and dashboard-render checks
	orchestration/verify.sh --full

.PHONY: mcp
mcp: ## OFFLINE, no AWS: the local stdio MCP server for the review tools (14.2c); reads stdin, writes stdout; a client such as Claude Code starts it as a stdio command (see agents/README.md)
	@PYTHONPATH=agents:console uv run --no-project --python 3.12 python -m cerberus_agents.mcp_server

.PHONY: status-e2e
status-e2e: ## OFFLINE, Docker only: push run records to a throwaway Prometheus on 127.0.0.1:9099 and check every status query (10.2c; no AWS)
	observability/status/e2e.sh

.PHONY: status-render status-render-shots
status-render: ## OFFLINE, Docker only: throwaway Prometheus + Grafana 13.2.3 on 127.0.0.1 (9098, 3098); every status-dashboard query through Grafana (10.3b; no AWS)
	observability/grafana/render_check/run.sh

status-render-shots: ## OFFLINE, Docker + Playwright, local only: two screenshots of the status dashboard into observability/grafana/render_check/screenshots/ (git-ignored)
	RENDER_CMD="uv run --no-project --python 3.12 --with playwright==1.65.1 python -I observability/grafana/render_check/screenshot.py" observability/grafana/render_check/run.sh

.PHONY: alerts-test
alerts-test: ## OFFLINE, Docker only: promtool check and test the alert rules, amtool check the Alertmanager template (10.4a; no AWS)
	observability/alerts/test.sh

.PHONY: status-publish status-smoke
# AWS WRITE, owner-run (10.2d). Both are a dry run unless ARGS=--send, which signs
# a remote-write to AMP as cerberus-admin and needs aps:RemoteWrite (policy paste).
status-publish: ## AWS WRITE, owner-run: publish a run's status series; EXECUTION= required; dry run unless ARGS=--send
	@test -n "$(EXECUTION)" || { echo "EXECUTION= is required"; exit 2; }
	AWS_PROFILE=cerberus-admin uv run -q --no-project --python 3.12 --with boto3==1.43.67 \
	  python observability/status/publish.py end --execution "$(EXECUTION)" $(ARGS)

status-smoke: ## AWS WRITE, owner-run: write one cerberus_publisher_smoke sample and read it back; dry run unless ARGS=--send
	AWS_PROFILE=cerberus-admin uv run -q --no-project --python 3.12 --with boto3==1.43.67 \
	  python observability/status/publish.py smoke $(ARGS)

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

.PHONY: cerberus
cerberus: ## run one read-only console command locally as cerberus-console-cli (CMD="status"; CMD="--json run latest")
	cd console && uv run --no-project --python 3.12 --with boto3==1.43.67 python -m cerberus_console $(CMD)

.PHONY: status
# The AMP URL is AMP_QUERY_URL, else CERBERUS_AMP_QUERY_URL, else `terraform output` (read-only, 30 s limit).
status: ## READ-ONLY, owner-run: pipeline status from AMP + Step Functions + Athena + newest record (optional AMP_QUERY_URL=<workspace query URL>); needs cerberus-admin credentials to assume cerberus-console-cli
	@CERBERUS_AMP_QUERY_URL="$${AMP_QUERY_URL:-$${CERBERUS_AMP_QUERY_URL:-$$(timeout 30 $(TF_BIN) -chdir=$(TF_STANDING_DIR) output -raw prometheus_endpoint 2>/dev/null || true)}}" \
	  $(MAKE) --no-print-directory cerberus CMD=status

.PHONY: console-site console-site-preview console-site-publish
console-site: ## build the public landing page into console/site-dist (one same-origin script for the live dashboard link; no AWS; ADR 0024)
	cd console && rm -rf site-dist && uv run --no-project --python 3.12 python -m cerberus_landing build --out site-dist

console-site-preview: ## serve console/site-dist at http://127.0.0.1:8088/ with the edge CSP (run console-site first; no live.json, so the live link stays hidden)
	cd console && uv run --no-project --python 3.12 python -m cerberus_landing.serve --dir site-dist

console-site-publish: console-site ## AWS WRITE, needs approval: publish console/site-dist to the standing edge (owner fallback for console-site.yml)
	console/publish_site.sh console/site-dist \
	  "$$($(TF_BIN) -chdir=$(TF_STANDING_DIR) output -raw console_site_bucket_name)" \
	  "$$($(TF_BIN) -chdir=$(TF_STANDING_DIR) output -raw console_distribution_id)" \
	  "$$($(TF_BIN) -chdir=$(TF_STANDING_DIR) output -raw console_url)"

.PHONY: showcase-snapshot showcase-check
showcase-snapshot: ## OFFLINE, git only: write observability/showcase/*.json from the run records, with the fail-closed redaction gate (11.2a; no AWS)
	PYTHONPATH=console uv run --no-project --python 3.12 python -m cerberus_landing.showcase --runs observability/scale/runs --out observability/showcase

showcase-check: ## OFFLINE, git only: fail if the committed observability/showcase/*.json are stale (11.2a; no AWS)
	PYTHONPATH=console uv run --no-project --python 3.12 python -m cerberus_landing.showcase --runs observability/scale/runs --out observability/showcase --check

.PHONY: fmt
fmt: ## terraform fmt across the whole terraform/ tree
	$(TF_BIN) fmt -recursive terraform/

.PHONY: clean
clean: ## Remove local Terraform working state (not remote state)
	find terraform -type d -name ".terraform" -prune -exec rm -rf {} +

.PHONY: console-terminal console-terminal-preview console-terminal-publish
console-terminal: ## build the terminal page into console/terminal-dist (plain DOM terminal, no AWS; ADR 0024 amendment 2026-11-12)
	cd console && rm -rf terminal-dist && uv run --no-project --python 3.12 python -m cerberus_terminal build --out terminal-dist

console-terminal-preview: ## serve console/terminal-dist at http://127.0.0.1:8089/terminal/index.html with the edge CSP (run console-terminal first; no config.json, so it shows "not configured")
	cd console && uv run --no-project --python 3.12 python -m cerberus_terminal.serve --dir terminal-dist

console-terminal-publish: console-terminal ## AWS WRITE, needs approval: publish console/terminal-dist to the standing edge (owner fallback for console-terminal.yml)
	console/publish_terminal.sh console/terminal-dist \
	  "$$($(TF_BIN) -chdir=$(TF_STANDING_DIR) output -raw console_site_bucket_name)" \
	  "$$($(TF_BIN) -chdir=$(TF_STANDING_DIR) output -raw console_distribution_id)" \
	  "$$($(TF_BIN) -chdir=$(TF_STANDING_DIR) output -raw console_url)" \
	  "$$($(TF_BIN) -chdir=$(TF_STANDING_DIR) output -raw console_client_id)" \
	  "$$($(TF_BIN) -chdir=$(TF_STANDING_DIR) output -raw console_auth_domain)"

.PHONY: console-artifacts
console-artifacts: ## AWS WRITE, needs approval: stage the pinned Grafana tarball and AMP plugin in the private artifacts/ prefix of the site bucket (once per version)
	observability/grafana/console/stage_artifacts.sh \
	  "$$($(TF_BIN) -chdir=$(TF_STANDING_DIR) output -raw console_site_bucket_name)"

.PHONY: traceability traceability-check
traceability: ## Regenerate observability/showcase/history.json and docs/traceability.md (git only, no AWS)
	python3 tools/traceability/generate.py

traceability-check: ## Fail if the traceability files are stale or a link dangles (what CI runs)
	python3 tools/traceability/generate.py --check

# 17.3b (ADR 0030): the per-session launch edge. The 17.4 targets sit between
# launch-plan and launch-function-test; launch-exercise (17.5) goes at the end of the file.
.PHONY: launch-plan launch-function-test
launch-plan: ## READ-ONLY, owner-run: init dev-launch against the shared state backend, then terraform plan with no load generator (applies nothing)
	@TF_BIN=$(TF_BIN) orchestration/launch_init.sh && \
	$(TF_BIN) -chdir=$(TF_LAUNCH_DIR) plan -var create_load_gen=false

# 17.4 (ADR 0030): the launch session tooling. Pass flags with ARGS, for
# example `make launch-session SCENARIO=bcd MINUTES=90 ARGS=--yes`. SCENARIO,
# MINUTES, PREWARM and HOLD reach the script through the environment.
.PHONY: launch-baseline launch-session launch-collect launch-check launch-destroy launch-test
launch-baseline: ## READ-ONLY (Cost Explorer), owner-run once before Run A: write launch/cost_baseline.json (November Usage through 11-24, credits excluded)
	python3 launch/ledger.py baseline

launch-session: ## AWS WRITE, owner-run: one launch session (SCENARIO, MINUTES, PREWARM, HOLD; ARGS=--dry-run prints the plan and calls nothing)
	@TF_BIN=$(TF_BIN) orchestration/launch_session.sh $(ARGS)

launch-collect: ## AWS WRITE (bronze), owner-run: copy the CDN logs of RUN_ID (read from the environment) to bronze (checked against the field allowlist first; repeatable)
	@orchestration/launch_collect.sh

launch-check: ## READ-ONLY: report 0 for every launch resource; exit 1 on any leftover or unreadable value
	@TF_BIN=$(TF_BIN) orchestration/launch_check.sh

launch-destroy: ## AWS WRITE, owner-run: stage 1 (leftover cookie parameter) and stage 2 destroy of dev-launch, then launch-check. Needs no shell state
	@TF_BIN=$(TF_BIN) orchestration/launch_destroy.sh

launch-test: ## offline: pytest of the launch tooling (stubs aws, terraform, openssl, k6 and curl on PATH)
	uv run --no-project --python 3.12 --with pytest==9.1.1 --with sqlglot==30.35.0 python -m pytest -q launch/tests

# 17.7: the launch results. The two pulls are read-only and owner-run; the render
# reads the files they write and needs no AWS.
.PHONY: launch-pull-results launch-pull-cost launch-results-render
launch-pull-results: ## READ-ONLY (Athena), owner-run: pull the gold marts into observability/launch/extracts/ (SESSION= one or more run ids separated by spaces, EXERCISE= the exercise run id)
	@printf '%s\n' "$$SESSION $$EXERCISE" | grep -Eqx '[a-z0-9-]+( [a-z0-9-]+)+' \
	  || { echo "SESSION= (one or more run ids) and EXERCISE= are required, as [a-z0-9-] ids"; exit 2; }
	set -f; args=""; for s in $$SESSION; do args="$$args --session $$s"; done; \
	  uv run -q --no-project --python 3.12 --with boto3==1.43.67 \
	  python launch/results_pull.py results $$args --exercise "$$EXERCISE"

launch-pull-cost: ## READ-ONLY (Cost Explorer), owner-run: write observability/launch/extracts/cost.json (November Usage total and daily cost by service; needs ce:GetCostAndUsage)
	AWS_PROFILE=cerberus-admin uv run -q --no-project --python 3.12 --with boto3==1.43.67 \
	  python launch/results_pull.py cost

launch-results-render: ## OFFLINE, no AWS: render docs/launch-day-results.md and docs/img/launch/*.svg from the run records, ledger and extracts
	python3 launch/results_render.py

launch-function-test: ## offline: node tests of the /license Function and the launch edge Terraform (no AWS, no network)
	node --test terraform/modules/launch_edge/function/license.test.mjs terraform/modules/launch_edge/static.test.mjs

# 17.5 (ADR 0030): the downloads telemetry exercise. Owner-run: it applies
# dev-compute, then destroys it before dbt and data quality. The other launch-*
# targets belong to 17.4.
.PHONY: launch-exercise
launch-exercise: ## OWNER-RUN, AWS: apply dev-compute -> generate downloads events -> silver -> destroy -> dbt marts -> data quality (orchestration/launch_exercise.sh; ARGS="--generate 1000000"; fails closed without the spend guard)
	orchestration/launch_exercise.sh $(ARGS)
