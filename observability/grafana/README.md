# Local Grafana (ADR 0022)

Grafana 13.2.3 in Docker Compose, bound to `127.0.0.1:3000`. It reads the
standing AMP workspace and CloudWatch with your `cerberus-admin` AWS profile.
Datasources and dashboards come from `provisioning/` and `dashboards/`, with
the same uids (`amp`, `cloudwatch`) as the in-cluster Grafana.

## Start

1. Check the `cerberus-admin` profile works: `aws sts get-caller-identity --profile cerberus-admin`.
2. Create the password file once:
   `(umask 077; echo "GF_SECURITY_ADMIN_PASSWORD=$(openssl rand -base64 18)" > observability/grafana/.env)`
3. `make grafana-up` (from the repo root).
4. Open http://localhost:3000 and sign in as `admin` with the password from `.env`.

`make grafana-logs` follows the logs. `make grafana-down` stops and removes
the container. The `grafana-data` volume (Grafana's own state) stays; no repo
file is deleted. To drop the volume as well, run:
`AMP_URL=unused docker compose -f observability/grafana/compose.yaml --env-file observability/grafana/.env down -v`

The first start downloads the AMP plugin (about one minute) before Grafana serves; later starts reuse it from the volume.

## Security

- Grafana binds to `127.0.0.1` only, and anonymous access is off.
- `~/.aws` is mounted read-only, and the container runs as your uid.
- Keep your keys private: `chmod 700 ~/.aws && chmod 600 ~/.aws/credentials ~/.aws/config`. The container still reads them.
