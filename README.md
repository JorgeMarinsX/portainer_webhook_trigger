# webhook_cron_trigger

Calls **Portainer webhooks on a schedule** so production stacks redeploy at fixed times
(e.g. 02:00 local). Single container, single process, no database, no UI.

## How it works

- `JOBS` (env) lists the jobs; each is a name, a 5-field cron expression, and a Portainer
  webhook URL. Schedules are interpreted in `TZ`.
- APScheduler fires each job; the job `POST`s an empty body to the webhook. Portainer
  answers `204`.
- Failures are retried 3 times with a short backoff, logged at `ERROR`, then dropped until
  the next scheduled run. One failing job never affects the others, and never crashes the process.
- Missed runs (container was down) are **not** backfilled — `coalesce=True`,
  `misfire_grace_time=60`.
- Every trigger (scheduled or manual) posts its outcome to each configured channel in
  `app/notifications/`. Success is posted silently; only failures ping. A broken notifier is
  logged and never affects the trigger.

## HTTP

| Route | What |
|---|---|
| `GET /health` | `200` + every job with its cron and next run time |
| `POST /trigger/{job_name}` | fires that job now — `200` if the webhook accepted, `502` if not, `404` for an unknown name |

No auth. The container is internal-only until it is put behind Traefik.

## Configuration

| Var | Required | Meaning |
|---|---|---|
| `JOBS` | yes | JSON array of `{name, cron, url}` objects |
| `TZ` | yes | IANA timezone, e.g. `America/Sao_Paulo` |
| `LOG_LEVEL` | no | default `INFO` |
| `DISCORD_WEBHOOK` | no | Discord webhook URL for trigger notifications; unset = off. A secret. |

```json
[
  { "name": "prod-api",    "cron": "0 2 * * *",  "url": "https://portainer.example.com/api/webhooks/<uuid>" },
  { "name": "prod-worker", "cron": "30 2 * * *", "url": "https://portainer.example.com/api/webhooks/<uuid>" }
]
```

**`JOBS` is a secret** — the webhook UUID *is* the credential. It is validated at startup and
the process exits with a clear error if it is missing, malformed, has duplicate names, an
invalid cron expression, or a non-HTTP(S) URL. A schedule that silently never fires is the
worst failure mode here, so it fails fast instead.

## Dev

```bash
cp .env.example .env          # then edit JOBS / TZ
docker compose -f docker-compose.dev.yml up --build
curl localhost:8000/health
curl -X POST localhost:8000/trigger/prod-api
```

Source is bind-mounted and uvicorn runs with `--reload`.

Tests (config parsing/validation, notification fan-out):

```bash
docker compose -f docker-compose.dev.yml run --rm webhook-cron-trigger pytest
```

Dependencies are managed with **uv**, never `pip install`. To change them, edit
`pyproject.toml` and relock:

```bash
docker run --rm -v "$PWD:/w" -w /w ghcr.io/astral-sh/uv:python3.13-bookworm-slim uv lock
```

## Release

Push a tag matching `v<major>.<minor>.<patch>-prod`:

```bash
git tag v1.4.0-prod && git push origin v1.4.0-prod
```

`.github/workflows/release.yml` builds `Dockerfile.prod` and pushes two tags —
`1.4.0` and `latest` — to the private registry. Branch pushes and non-`-prod` tags publish
nothing, and CI never deploys.

Required GitHub secrets: `REGISTRY`, `REGISTRY_USERNAME`, `REGISTRY_PASSWORD`, `IMAGE_NAME`.
The registry host, user, and password are never hardcoded in this repo.

## Deploy (Portainer)

1. **Portainer → Registries** — add the private registry with its username and password so
   the stack can pull. This is a manual, one-time step; it is deliberately not automated.
2. Create a stack from `docker-compose.prod.yml` and set the stack environment variables:
   `REGISTRY`, `IMAGE_NAME`, `TZ`, `JOBS` (and optionally `LOG_LEVEL`, `DISCORD_WEBHOOK`).
3. To ship a new version, push a `-prod` tag, then redeploy the stack in Portainer so it
   re-pulls `latest` — the same webhook mechanism this service triggers.

## Non-goals

No database, web UI, per-job auth, runtime job editing, metrics, multiple workers, Traefik
config, or Portainer API client. Ask before adding any of them.
