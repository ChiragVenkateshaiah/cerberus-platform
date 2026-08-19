# 4.2 -- one shared image for the two "CLI-heavy" orchestration steps that
# have no native Step Functions integration (ADR 0009's conceded friction
# point): the transform step (kubectl-based Spark-on-EKS submission and
# polling) and the dbt-run step. Built and pushed by
# terraform/modules/orchestration_runner's null_resource, not a CI/CD
# pipeline -- Phase 5's job, not this one's.
#
# Build context is the repo root, not this directory -- see the module's
# `docker build` invocation and ../../.dockerignore. That's what lets this
# COPY transform/dbt/ and transform/spark/ alongside orchestration/runner/
# itself, without also pulling in transform/dbt/'s gitignored local build
# artifacts (target/, logs/, etc. -- see .dockerignore).
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl unzip ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# AWS CLI v2 -- pinned, not "latest" (matching kubectl's own pin below,
# and this project's general practice of verifying versions live rather
# than guessing -- see transform/spark/spark-application.yaml's header).
# 2.36.25 verified live against
# https://raw.githubusercontent.com/aws/aws-cli/v2/CHANGELOG.rst on
# 2026-08-19 as the changelog's top (most recent) entry. Both entrypoint
# scripts shell out to this directly (s3 cp, eks update-kubeconfig, athena
# start-query-execution), the same way submit_job.sh and
# run_demo_query.sh already do outside a container.
ARG AWSCLI_VERSION=2.36.25
RUN curl -sSLf "https://awscli.amazonaws.com/awscli-exe-linux-x86_64-${AWSCLI_VERSION}.zip" -o /tmp/awscliv2.zip && \
    unzip -q /tmp/awscliv2.zip -d /tmp && \
    /tmp/aws/install && \
    rm -rf /tmp/awscliv2.zip /tmp/aws

# kubectl -- pinned rather than tracking latest. The eks module's own
# kubernetes_version is left unset (AWS picks its current default at apply
# time, since the cluster is spun up and destroyed per job rather than
# upgraded in place) -- kubectl supports +/-1 minor version of skew
# against the API server, so this only needs bumping if that drifts
# further than that from 1.31. -f/--fail on the curl below matters here:
# without it, an HTTP error response gets silently saved as the kubectl
# binary and chmod +x still "succeeds," so the failure only surfaces at
# container runtime instead of at build time.
ARG KUBECTL_VERSION=1.31.0
RUN curl -sSLf "https://dl.k8s.io/release/v${KUBECTL_VERSION}/bin/linux/amd64/kubectl" -o /usr/local/bin/kubectl && \
    chmod +x /usr/local/bin/kubectl

# dbt -- same pins as transform/dbt/requirements.txt, installed once here
# rather than duplicated.
COPY transform/dbt/requirements.txt /opt/dbt/requirements.txt
RUN pip install --no-cache-dir -r /opt/dbt/requirements.txt

# The dbt project, baked in at build time (see header). profiles.yml's
# aws_profile_name line is stripped in place rather than replaced with a
# second, hand-maintained committed file -- that variant used to be
# orchestration/runner/profiles.orchestration.yml, but a second file
# copying every other setting (region, buckets, workgroup, schema,
# threads, retries) by hand was pure drift risk: this way there is
# structurally only one source of truth for everything except the one
# line that has to differ (aws_profile_name names a CLI profile this
# container doesn't have -- the task role supplies credentials directly
# instead, so dbt-athena needs to fall back to the default boto3 chain).
COPY transform/dbt/ /opt/dbt/
RUN sed -i '/aws_profile_name/d' /opt/dbt/profiles.yml

# The transform step's working files: what submit_job.sh's original would
# have read from its own SCRIPT_DIR. spark-application.yaml's
# mainApplicationFile is a hardcoded s3a:// path, not templated from the
# SILVER_BUCKET env var entrypoint_transform.sh uses -- see that script's
# header for why this doesn't drift in practice.
COPY transform/spark/spark-application.yaml /opt/spark/spark-application.yaml
COPY transform/spark/promote_payments_spark.py /opt/spark/promote_payments_spark.py

COPY orchestration/runner/lib.sh /opt/runner/lib.sh
COPY orchestration/runner/entrypoint_transform.sh /opt/runner/entrypoint_transform.sh
COPY orchestration/runner/entrypoint_dbt.sh /opt/runner/entrypoint_dbt.sh
RUN chmod +x /opt/runner/entrypoint_transform.sh /opt/runner/entrypoint_dbt.sh

WORKDIR /opt/runner
