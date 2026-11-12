# Local Grafana (ADR 0022)

Grafana 13.2.3 in Docker Compose, bound to `127.0.0.1:3000`. It reads the
standing AMP workspace and CloudWatch with short-lived, read-only credentials
from the `cerberus-grafana-read` role (ADR 0024).
Datasources and dashboards come from `provisioning/` and `dashboards/`, with
fixed uids (`amp`, `cloudwatch`) that the dashboards reference.

## Start

1. Check that the read-only role exists:
   `aws iam get-role --role-name cerberus-grafana-read --profile cerberus-admin --query Role.Arn`.
2. Create the password file once:
   `(umask 077; echo "GF_SECURITY_ADMIN_PASSWORD=$(openssl rand -base64 18)" > observability/grafana/.env)`
3. `make grafana-up` (from the repo root). It assumes `cerberus-grafana-read`
   and prints the role, the session name and the expiry.
4. Open http://localhost:3000 and sign in as `admin` with the password from `.env`.

`make grafana-logs` follows the logs. `make grafana-down` stops and removes
the container. The `grafana-data` volume (Grafana's own state) stays; no repo
file is deleted. To drop the volume as well, run:
`AMP_URL=unused AWS_ACCESS_KEY_ID=unused AWS_SECRET_ACCESS_KEY=unused AWS_SESSION_TOKEN=unused docker compose -f observability/grafana/compose.yaml --env-file observability/grafana/.env down -v`

The session lasts 12 hours. After that the panels show credential errors.
Run `make grafana-up` again to renew it; Compose recreates the container and
the volume stays. `GRAFANA_SESSION_HOURS` (1 to 12) sets a shorter session.

In Connections → Data sources → CloudWatch, "Save & test" reports that the metrics API works and that the logs query failed (`AccessDeniedException` on `DescribeLogGroups`). This is expected: `cerberus-grafana-read` has no CloudWatch Logs read, and the dashboards use CloudWatch metrics only.

The first start downloads the AMP plugin (about one minute) before Grafana serves; later starts reuse it from the volume.

## Run annotations

`orchestration/exercise.sh` posts step times, the data-quality verdict and the
account-wide teardown check to this Grafana as annotations (ADR 0022
amendment). Run `make grafana-token` once after `make grafana-up`, and again
before the 30-day token expires. It creates the service account
`cerberus-exercise` (Editor) and writes `GRAFANA_ANNOTATE_TOKEN` into `.env`
(mode 600). The script reads only that key. Without a token, or with Grafana
down, the run prints one `annotation skipped` line and carries on;
`--no-annotate` turns it off. `orchestration/annotate.sh --replay EXECUTION`
posts the annotations of a finished run again.

## Security

- Grafana binds to `127.0.0.1` only, and anonymous access is off.
- No long-lived AWS keys are in the container. It gets short-lived, read-only session credentials (up to 12 h) in its environment, which anyone with Docker access can read with `docker inspect`. It runs as your uid.
- `GRAFANA_ANNOTATE_TOKEN` in `.env` is an Editor service-account token (30-day expiry, mode 600). Revoke it in Administration → Service accounts, or re-run `make grafana-token`.

## Console session artifacts (step 10)

The console session (ADR 0024) installs Grafana from private copies, not from the internet. `console/artifacts.json` pins two files: the Grafana OSS 13.2.3 linux arm64 tarball and the `grafana-amazonprometheus-datasource` 3.2.0 linux arm64 plugin. A CI test checks that the versions match `compose.yaml`.

Run `make console-artifacts` once per version. It downloads each file, checks the sha256 and size, and uploads it to the `artifacts/grafana/` prefix of the site bucket with the sha256 in the object metadata. An object that already carries the pinned sha256 is skipped. The prefix is private: the CloudFront deny on `artifacts/*` keeps it off the public site. The target writes to AWS, so it needs the owner's approval.

## Console Grafana module (step 10)

The console host (ADR 0024) shows the recorded runs in a per-session Grafana that has only the AMP data source. The files in `console/` build everything it needs from files already in the repo. They use only the standard library and run on Python 3.9, the system `python3` of Amazon Linux 2023.

| File | Job |
|---|---|
| `annotations.py` | Turns each run record in `observability/scale/runs/` into annotations: run start and end, one region per step, the quality verdict, the Now tile, an approximate generator region, and a Clean-up tile that says it is not recorded. Tags match `orchestration/annotate.sh`, plus `console`. |
| `dashboards.py` | Makes console copies of the three dashboards (the shared files are not changed) and the home dashboard "0 · Recorded runs", with one link per run, newest first and failed runs marked. The CloudWatch panels become AMP-only: the story "Pipeline journey" keeps its AMP rows and gains an annotation layer, "Cost so far" becomes a compute estimate, and two panels become text that explains why. The default time is the newest run. |
| `load.py` | Posts the annotations to Grafana. It refuses any host except `127.0.0.1` and `localhost`, does not follow redirects, and reads the admin password from `GRAFANA_ADMIN_PASSWORD` only. |
| `grafana.ini.tmpl`, `grafana_ini.py` | The hardened `grafana.ini` template and the small renderer that fills it from a JSON object on stdin. |
| `build.py` | One command that writes the dashboards and `annotations.json`. |

```
python3 -I console/build.py --dashboards dashboards --runs ../scale/runs --out /tmp/console
GRAFANA_ADMIN_PASSWORD=... python3 -I console/load.py /tmp/console/annotations.json --wait 120
python3 -I console/grafana_ini.py console/grafana.ini.tmpl < values.json > grafana.ini
```

Run `pytest observability/grafana/console` for the tests. They use the real run records and dashboards, with no AWS and no network. Several `grafana.ini` key names are marked "unverified" in the template; the first live session checks them.
