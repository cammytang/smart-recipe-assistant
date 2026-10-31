# Container images

Run these commands from the repository root. Build contexts must be `backend/`
and `frontend/`, respectively. CI should build for the server's `linux/amd64`
platform and publish versioned images; the server only pulls and runs them.

```sh
docker build --platform linux/amd64 -t smart-recipe-backend:local ./backend
docker build --platform linux/amd64 -t smart-recipe-frontend:local ./frontend
```

The frontend uses a Node build stage and an Nginx runtime stage. Only the built
static files enter the runtime image. `VITE_API_BASE_URL` defaults to `/api` and
is embedded at build time. Do not pass secrets in build arguments. Local `.env`
files, dependencies, logs and runtime data are excluded from build contexts.

## Runtime requirements

- Run the two containers on the same user-defined Docker network. The backend
  hostname defaults to `backend`; set frontend runtime variables `BACKEND_HOST`
  and `BACKEND_PORT` if needed. Nginx uses Docker DNS and re-resolves the hostname
  when backend containers are replaced.
- Publish only the frontend port. Nginx strips the outer `/api` prefix and forwards
  API requests to port 8000. For example, `/api/api/v1/sessions` reaches the
  existing `/api/v1/sessions` authentication route. React routes fall back to
  `index.html`. SSE buffering is disabled and proxy read timeout is 600 seconds.
- Supply backend settings at runtime using an env file or the orchestrator's
  secret configuration. See `backend/.env.example`. In production use
  `APP_ENV=production`, `AUTH_COOKIE_SECURE=true` and the exact HTTPS frontend
  origin in `AUTH_ALLOWED_ORIGINS`. Terminate HTTPS at the external reverse proxy
  or gateway; this frontend image itself listens on HTTP port 80.
- PostgreSQL is a separate service. `DATABASE_URL` must use its network hostname,
  not `localhost`. Initialize a new database using `backend/database/init.sql`
  before starting the backend. Application startup checks the schema but does
  not create or migrate it. Never rerun initialization over an existing database.
- Persist `/app/qdrant_data`, `/app/notes` and, if file logs are needed,
  `/app/logs`. The backend runs as UID/GID `10001:10001`; bind-mounted directories
  must be writable by that user. PostgreSQL needs its own persistent storage.
- Existing local Qdrant files are intentionally not included in the image.
  Initialize an empty mounted index once with the backend image using
  `python scripts/index_recipes.py`, with the same environment and volume as the
  running backend. Stop the application while indexing: embedded Qdrant must not
  have two processes accessing its directory. The image includes `dishes.json`.
  Use the same embedding model for indexing and queries. Do not rebuild the
  index on every deployment; `--recreate` deletes the existing collection.
- Keep one backend worker. The embedded Qdrant directory and current process-local
  rate limiter are not designed for a multi-worker deployment. Proxy forwarding
  headers are deliberately not trusted; current IP rate limits therefore see
  the proxy address. Configure gateway limits or a reviewed trusted-proxy policy
  before opening registration to a broad audience.

## Validation

Both images define health checks. The frontend `/healthz` checks Nginx only;
`/api/healthz` is forwarded to the backend. The backend `/healthz` checks HTTP
liveness, not external model/search/embedding readiness. A full acceptance test
still needs PostgreSQL, initialized Qdrant, configured providers and a real
login/menu-generation flow. Build and deployment do not call model APIs.

## Publish images with GitHub Actions

`.github/workflows/publish-images.yml` is manually triggered and publishes both
images for `linux/amd64`. Commit and push the workflow and image definitions to
the repository's default branch. In GitHub select **Actions → Publish container
images → Run workflow** and choose the intended branch. No personal access token
or model credentials are needed: the jobs use `GITHUB_TOKEN` with `packages: write`.
Repository or organization policies must allow these actions and package writes.

Images are named `ghcr.io/<lowercase-owner>/smart-recipe-backend` and
`ghcr.io/<lowercase-owner>/smart-recipe-frontend`. Each has a `sha-<full-commit-sha>`
tag; the run summary also records its digest. There is no mutable `latest` tag.
Both jobs must succeed before treating the pair as a usable release. This workflow
builds/publishes only; it does not run the project test suite or deploy to a server.

Find published images under the GitHub profile's **Packages** section. Newly
published packages may be private even when the source repository is public.
For anonymous server pulls, explicitly make the intended packages public;
otherwise configure a server-side credential with `read:packages` access. Never
paste tokens into chat or commit them. Pull the exact image references from the
successful run summary to verify server access and full layer downloads.

Compose, HTTPS and automatic deployment will be added separately; publishing
images alone does not deploy the application.
