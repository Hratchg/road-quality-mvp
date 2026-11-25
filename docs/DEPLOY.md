# Deploying to Fly.io

The stack deploys to Fly.io as three apps — `road-quality-db`,
`road-quality-backend`, `road-quality-frontend` — via a GitHub Actions
workflow on push to `main`. The workflow lives at
`.github/workflows/deploy.yml`; the per-app Fly configs live under
`deploy/{db,backend,frontend}/fly.toml`. Phase 5 ships this path; Phase 6
will use it to put the demo on a public URL.

### Prerequisites

1. **Fly.io account** with billing set up. Sign up at <https://fly.io/app/sign-up>.
2. **flyctl CLI** installed locally for hotfix deploys + secret management:

    ```bash
    curl -L https://fly.io/install.sh | sh
    flyctl auth login
    ```

3. **GitHub repo secret** `FLY_API_TOKEN` configured. Generate the token via:

    ```bash
    fly tokens create deploy -x 999999h --name "github-actions-deploy"
    ```

    Copy the output, then in GitHub: Settings → Secrets and variables → Actions → New repository secret. Name: `FLY_API_TOKEN`. Value: the token output.

### Initial deploy

Run these once, in order, from your local machine. After this, every push to `main` redeploys whichever app changed.

1. Create the three Fly apps (one-time):

    ```bash
    flyctl apps create road-quality-db
    flyctl apps create road-quality-backend
    flyctl apps create road-quality-frontend
    ```

2. Generate a Postgres password and an auth signing key (32+ chars), and stash them in your shell:

    ```bash
    PG_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
    AUTH_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    ```

3. Set Fly secrets per [05-RESEARCH §2](../.planning/phases/05-cloud-deployment/05-RESEARCH.md):

    ```bash
    # DB app
    flyctl secrets set --app road-quality-db POSTGRES_PASSWORD="$PG_PASSWORD"

    # Backend app
    flyctl secrets set --app road-quality-backend \
      DATABASE_URL="postgres://rq:$PG_PASSWORD@road-quality-db.internal:5432/roadquality" \
      AUTH_SIGNING_KEY="$AUTH_KEY" \
      ALLOWED_ORIGINS="https://road-quality-frontend.fly.dev"

    # Optional: Mapillary token if you want to ingest real imagery later (Phase 6).
    # flyctl secrets set --app road-quality-backend MAPILLARY_ACCESS_TOKEN="..."
    ```

4. Push to `main` (or trigger manually via the GitHub Actions UI). The workflow will deploy db → backend → frontend in order. Watch progress at `https://github.com/<org>/<repo>/actions`.

5. After the first deploy completes, populate the routable graph (one-time; SC #7):

    ```bash
    gh workflow run deploy.yml --ref main -f seed=true
    ```

    This triggers the `seed-on-demand` job which runs `python scripts/seed_data.py` from the GH Actions runner (host venv) against the deployed Fly DB via `flyctl proxy`. The seed takes ~5 minutes (downloads OSMnx data + inserts ~10k segments + builds pgRouting topology).

6. Verify the deploy:

    ```bash
    curl https://road-quality-backend.fly.dev/health
    # Expected: {"status":"ok","db":"reachable"}

    curl -I https://road-quality-frontend.fly.dev/
    # Expected: HTTP/2 200, content-type: text/html
    ```

7. Open <https://road-quality-frontend.fly.dev/> in a browser and confirm the map renders LA segments. Sign in with the demo account (see [Public Demo Account](#public-demo-account) above).

### Hotfix

For urgent fixes that bypass the GH Actions queue:

```bash
# Build + deploy a single app from your local checkout
flyctl deploy --remote-only --config deploy/backend/fly.toml --app road-quality-backend .
```

This builds on Fly's remote builder (no local Docker required) and pushes the new image. Fly does a rolling restart by default.

### Rollback

```bash
# List recent images
flyctl image list --app road-quality-backend

# Roll back to the previous image
flyctl deploy --image <previous-image-ref> --app road-quality-backend
```

There is no automated rollback — operators trigger this manually after observing a regression in Fly logs (`flyctl logs --app road-quality-backend`).

### Volume snapshot caveat

Fly takes nightly volume snapshots of the db app (5-day retention by default). If you ever restore a snapshot, the migrations baked into the db image will NOT re-run (Postgres' init scripts are first-boot-only). Apply migrations manually post-restore:

```bash
flyctl ssh console --app road-quality-db -C \
  "psql -U rq -d roadquality -f /docker-entrypoint-initdb.d/01-schema.sql"
# Repeat for 02-mapillary.sql, 03-users.sql, etc.
```

All migrations use `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` so manual re-application is safe.

