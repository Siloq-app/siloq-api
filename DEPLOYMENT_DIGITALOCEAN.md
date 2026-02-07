# Deploy siloq-backend on DigitalOcean App Platform

This guide walks you through deploying the Django backend to [DigitalOcean App Platform](https://docs.digitalocean.com/products/app-platform/).

## Prerequisites

- A DigitalOcean account
- This repo pushed to GitHub (or GitLab)
- Your app is in the `siloq-backend` directory (or adjust paths below)

## Option A: Deploy from the Dashboard (recommended)

1. **Create a new App**
   - In [DigitalOcean Control Panel](https://cloud.digitalocean.com/) go to **Apps** → **Create App**.
   - Choose **GitHub** (or GitLab), authorize DO, and select the repo and branch (e.g. `main`).

2. **Configure the backend component**
   - If the repo root is the monorepo, set **Source Directory** to `siloq-backend`.
   - **Resource Type**: Web Service.
   - **Build Command** (optional; buildpack may detect it):
     ```bash
     pip install -r requirements.txt && python manage.py collectstatic --noinput
     ```
   - **Run Command**:
     ```bash
     gunicorn --worker-tmp-dir /dev/shm --bind 0.0.0.0:$PORT siloq_backend.wsgi:application
     ```
   - **HTTP Port**: `8000` (or leave default; DO sets `PORT` automatically).

3. **Add a PostgreSQL database**
   - In the same app, click **Add Resource** → **Database** → **PostgreSQL** (e.g. version 15).
   - Create the database. App Platform will set `DATABASE_URL` for your web service when you link it.

4. **Link database to the web service**
   - Open your web service → **Settings** → **App-Level Environment Variables** (or component env vars).
   - Add:
     - `DATABASE_URL`: use the value from the database component (usually `${db.DATABASE_URL}` if the database component is named `db`).
   - Or use the UI “Link Database” so DO injects `DATABASE_URL` automatically.

5. **Set environment variables**
   Set these in the web service (and in the Pre-Deploy job if you add one):

   | Variable | Example | Notes |
   |----------|---------|--------|
   | `SECRET_KEY` | (long random string) | **Required.** Use a strong secret; set as **Encrypted** in DO. |
   | `DEBUG` | `False` | **Required** in production. |
   | `ALLOWED_HOSTS` | (optional) | Comma-separated. If not set, `APP_DOMAIN` (set by DO) is used. |
   | `CORS_ALLOWED_ORIGINS_EXTRA` | `https://siloq.ai,https://www.siloq.ai` | Comma-separated origins for the dashboard/frontend. |

   Do **not** commit real secrets; set them only in the DO dashboard.

6. **Run migrations (release phase)**
   - Add a **Pre-Deploy Job** (or use “Run Command” once):
     - **Source Directory**: `siloq-backend`
     - **Run Command**: `python manage.py migrate --noinput`
     - Use the same env vars as the web service (especially `DATABASE_URL` and `SECRET_KEY`).
   - This runs before each deployment so the DB schema is up to date.

7. **Deploy**
   - Save and deploy. After the build, the app URL (e.g. `https://siloq-backend-xxxxx.ondigitalocean.app`) will serve the API.

8. **Post-deploy**
   - Set `CORS_ALLOWED_ORIGINS_EXTRA` to your dashboard/frontend URLs (e.g. `https://siloq.ai`).
   - Point your frontend (siloq-dashboard) and WordPress plugin API URL to this app URL.

---

## Option B: Deploy using `.do/app.yaml`

The repo includes a spec file at `.do/app.yaml`. You can use it to define the app in code.

1. **Edit `.do/app.yaml`**
   - Replace `YOUR_ORG/siloq` with your GitHub org/repo (e.g. `yourusername/siloq`).
   - If the backend is not in `siloq-backend`, change `source_dir` for the service and the job.
   - Replace `CHANGE_ME_STRONG_SECRET` with a strong secret (or remove it from the file and set `SECRET_KEY` only in the dashboard as an encrypted env var).

2. **Create the app**
   - Using [doctl](https://docs.digitalocean.com/reference/doctl/):
     ```bash
     doctl apps create --spec .do/app.yaml
     ```
   - Or in the dashboard: **Create App** → **Import from spec** and paste/upload the spec.

3. **Set secrets**
   - In the DO dashboard, set `SECRET_KEY` (and any other secrets) as **Encrypted** so they are not stored in the repo.

4. **Deploy**
   - Push to the connected branch or trigger a deploy from the dashboard.

---

## What’s already configured in the repo

- **requirements.txt**: Includes `gunicorn`, `whitenoise`, `dj-database-url`.
- **settings.py**:
  - Uses `DATABASE_URL` when set (e.g. by DO); otherwise uses `DB_*` env vars for local dev.
  - Serves static files with WhiteNoise; `STATIC_ROOT` is `staticfiles`.
  - `ALLOWED_HOSTS`: from `ALLOWED_HOSTS` env or `APP_DOMAIN` (set by DO).
  - CORS: `CORS_ALLOWED_ORIGINS_EXTRA` adds production origins.
- **Procfile**: `web: gunicorn siloq_backend.wsgi:application --bind 0.0.0.0:${PORT:-8000}` (used if the platform respects Procfile).

---

## Troubleshooting

- **502 Bad Gateway**: Ensure the run command binds to `$PORT` and the HTTP port in DO matches (e.g. 8000).
- **Static files 404**: Build command should run `python manage.py collectstatic --noinput`; WhiteNoise then serves from `staticfiles`.
- **Database connection errors**: Confirm the database is linked and `DATABASE_URL` is set for both the web service and the migrate job.
- **CORS errors**: Add your frontend origin to `CORS_ALLOWED_ORIGINS_EXTRA` (comma-separated, no trailing slashes).

---

## Summary checklist

- [ ] Repo connected to App Platform (with correct branch and source directory).
- [ ] PostgreSQL database created and linked (`DATABASE_URL` set).
- [ ] `SECRET_KEY` set (encrypted); `DEBUG=False`.
- [ ] Run command: `gunicorn --worker-tmp-dir /dev/shm --bind 0.0.0.0:$PORT siloq_backend.wsgi:application`.
- [ ] Pre-deploy job: `python manage.py migrate --noinput` with same env (e.g. `DATABASE_URL`, `SECRET_KEY`).
- [ ] `CORS_ALLOWED_ORIGINS_EXTRA` set to your frontend URL(s).
- [ ] Frontend and WordPress plugin use the deployed app URL as the API base.
