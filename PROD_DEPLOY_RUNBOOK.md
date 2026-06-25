# Production Deployment Runbook — SkillConnect-native CV Intelligence Layer

**Target:** Promote the dev tree (`0007`, SkillConnect-native model + catalogs) onto the
production host, which currently runs the old flat-model build at migration `0003`.

**Verified premises (from the prod-vs-dev diff, 2026-06-25):**
- Prod has **no offline/proxy adaptations that dev lacks**. `Dockerfile.cpu` is byte-identical
  in both and is already offline-safe (bakes EasyOCR weights + spaCy wheels). Dev is a strict
  superset of prod's runtime adaptations.
- Prod's `.env` and compose topology are **prod-owned** and must be preserved, not overwritten.
- Prod data is test/disposable → **clean-slate cutover** (old flat-model rows are incompatible
  with the new code that reads `employee{}` / `skills[].name` / `experiences`).
- Prod has **no git** → deploy by file copy + (preferably) pre-built image tarball.

---

## 0. Pre-flight (on the PROD host)

```bash
cd /path/to/prod/cv-intelligence-layer        # the prod deploy dir

# 0.1 — Snapshot what prod runs today (rollback anchor)
cp .env .env.BAK.$(date +%Y%m%d_%H%M%S)
cp docker-compose.yml docker-compose.yml.BAK.$(date +%Y%m%d_%H%M%S)
docker compose ps                              # note running services/ports
docker compose exec cv-db psql -U cv_user -d cv_intelligence -c \
  "select version_num from alembic_version;"   # expect 0003_external_id_required

# 0.2 — Back up the prod DB (small/disposable, but cheap insurance)
docker compose exec cv-db pg_dump -U cv_user cv_intelligence \
  > /root/cv_prod_backup_$(date +%Y%m%d_%H%M%S).sql

# 0.3 — Tag the current images so you can roll back to them
docker image tag cv-api:cpu cv-api:cpu-rollback || true
```

---

## 1. Bring the new code onto prod (preserve `.env` + compose topology)

Prod has no git, so copy files — but **exclude the two prod-owned files** (`.env`,
`docker-compose.yml`) and the dev GPU bits you don't want on prod.

### Option A — rsync from the dev box (if reachable)
```bash
# Run FROM the dev box, pushing to prod. Adjust user@prodhost:path.
rsync -av --delete \
  --exclude='.env' \
  --exclude='docker-compose.yml' \
  --exclude='Dockerfile' \
  --exclude='.git/' \
  --exclude='__pycache__/' \
  --exclude='data/' \
  --exclude='e2e_tests/' \
  --exclude='tests/' \
  --exclude='*.tar.gz' \
  --exclude='cv-models/' \
  --exclude='easyocr-models/' \
  --exclude='cv_examples/' \
  --exclude='cv_intelligence_layer.egg-info/' \
  --exclude='.pytest_cache/' \
  --exclude='.ruff_cache/' \
  --exclude='.cursor/' \
  --exclude='prod_vs_dev_diff*' \
  ~/cv-intelligence-layer/ \
  user@prodhost:/path/to/prod/cv-intelligence-layer/
```

### Option B — tarball hand-off (air-gapped prod)
```bash
# On dev (~/cv-intelligence-layer):
tar czf /tmp/cvlayer_src.tgz \
  --exclude='.env' --exclude='docker-compose.yml' --exclude='Dockerfile' \
  --exclude='.git' --exclude='__pycache__' --exclude='data' \
  --exclude='e2e_tests' --exclude='tests' --exclude='*.tar.gz' \
  app prompts schemas alembic alembic.ini pyproject.toml \
  Dockerfile.cpu docker-compose.prod.yml \
  .env.example CLAUDE.md SPEC.md

# transfer /tmp/cvlayer_src.tgz to prod, then on prod:
tar xzf cvlayer_src.tgz -C /path/to/prod/cv-intelligence-layer/
```

> **Note:** `Dockerfile.gpu` and `docker-compose.gpu.yml` exist only in **prod** (created
> there manually). They are NOT in dev. Do not try to include them in the tarball — prod
> already has them and they are untouched by this deploy.

> **Why exclude `docker-compose.yml`?** Prod promoted its base compose file to the CPU/8801
> production config. Dev's base compose file is the GPU dev variant. Overwriting prod's would
> silently switch it to a GPU build on the next `up`. Keep prod's. You will still drive the
> deploy through `docker-compose.prod.yml` (see §4), which is identical in both trees.

After copying, sanity-check the new files landed:
```bash
ls app/services/{catalog_store,catalog_refresh,skill_resolver,skillconnect_client}.py
ls alembic/versions/000[4-7]*.py        # 4 new migrations present
```

---

## 2. Append the new `.env` keys (do NOT replace the file)

Prod's `.env` keeps all its existing values (`APP_ENV=production`, `EASYOCR_GPU=false`,
`SEARCH_API_BASE_URL=http://nginx:80`, prod search keys). Append the new block:

```bash
cat >> /path/to/prod/cv-intelligence-layer/.env <<'EOF'

# ── SkillConnect (Ooredoo HR) catalog integration ───────────────────
# Leave SKILLCONNECT_API_BASE_URL unset to run on the seeded catalog only
# (221 skills / 67 establishments / 5 languages from migration 0006).
# Set it once Ooredoo's elevate-api is reachable from the prod network.
SKILLCONNECT_API_BASE_URL=https://elevate.ooredoo.dz/elevate-api
SKILLCONNECT_SSL_VERIFY=true          # set false ONLY behind a TLS-intercepting proxy
# SKILLCONNECT_PROXY=http://proxy:8080  # or rely on HTTPS_PROXY/NO_PROXY in the container env
SKILLCONNECT_REFRESH_SECONDS=3600

# ── Gemini context cache (stable extraction-prompt prefix) ──────────
GEMINI_CACHE_ENABLED=true
GEMINI_CACHE_TTL_SECONDS=3600
EOF
```

> **Proxy note:** the catalog refresh is **fail-soft** — if `elevate.ooredoo.dz` is unreachable
> at startup, the app logs a warning and runs on the seeded catalog. So you can deploy with
> `SKILLCONNECT_API_BASE_URL` set even before the network path is open; resolution still works
> off the seed. If Ooredoo requires a proxy, set `SKILLCONNECT_PROXY` (or the standard
> `HTTPS_PROXY`/`NO_PROXY` env on the container) and keep `SKILLCONNECT_SSL_VERIFY=true` unless
> the proxy does TLS interception.

---

## 3. Build (or load) the CPU image

`Dockerfile.cpu` bakes EasyOCR + spaCy offline, but **torch is pulled from the PyTorch CDN at
build time**. Pick the path that matches prod's build-time network:

### Path 3A — prod can reach the PyTorch CDN (directly or via proxy)
```bash
cd /path/to/prod/cv-intelligence-layer
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
```

### Path 3B — air-gapped prod (build on a connected box, ship the image)
```bash
# On a connected box with the same repo:
docker build -f Dockerfile.cpu -t cv-api:cpu .
docker save cv-api:cpu | gzip > cv-images.tar.gz      # the artifact you already use

# transfer cv-images.tar.gz to prod, then on prod:
docker load < cv-images.tar.gz
# prod's docker-compose.yml already pins `image: cv-api:cpu`, so no rebuild needed.
```

> Confirm the baked models are present in the image (cheap guard against a bad build):
> ```bash
> docker run --rm cv-api:cpu ls /opt/easyocr-models        # craft_mlt_25k.pth + lang weights
> docker run --rm cv-api:cpu python -c "import spacy; spacy.load('fr_core_news_sm'); spacy.load('en_core_web_sm'); print('spaCy OK')"
> ```

---

## 4. Stop, migrate, clean-slate, start

```bash
cd /path/to/prod/cv-intelligence-layer
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

# 4.1 — Stop app + worker (keep DB + redis up for the migration)
$COMPOSE stop cv-api cv-worker

# 4.2 — Apply migrations 0004→0007 (catalog tables + seed 221/67/5 + name fix)
#        Start the new API container detached just to run alembic, or exec into db tooling.
$COMPOSE run --rm cv-api alembic upgrade head
$COMPOSE run --rm cv-api alembic current        # expect 0007_fix_corrupted_skill_names

# 4.3 — Verify the seed landed
$COMPOSE exec cv-db psql -U cv_user -d cv_intelligence -c \
  "select (select count(*) from skillconnect_skills)        as skills,
          (select count(*) from skillconnect_establishments) as estabs,
          (select count(*) from skillconnect_languages)      as langs;"
# expect 221 | 67 | 5

# 4.4 — CLEAN-SLATE cutover: old flat-model rows are incompatible with new code.
#        Prod data is disposable → truncate CV rows.
$COMPOSE exec cv-db psql -U cv_user -d cv_intelligence -c \
  "truncate table cv_profiles cascade;"
#        (Add any other CV-derived tables to the truncate if present.)

# 4.5 — Clear the Semantic Search collection so it has no orphaned old-shape docs.
#        Use the SS admin API / its own tooling to empty the collection used by prod.
#        (CV layer re-indexes on the next upload/create.)

# 4.6 — Bring everything up
$COMPOSE up -d
$COMPOSE ps
```

---

## 5. Smoke tests

```bash
PORT=8801
KEY=<prod APP_API_KEY from .env>
COLL=6e3c9ed4-2158-44e3-abbb-fb95c7a8675b

# 5.1 — Liveness / readiness (readiness checks DB + Semantic Search)
curl -s localhost:$PORT/health
curl -s localhost:$PORT/ready

# 5.2 — Catalog loaded (check logs for the startup line)
docker compose logs cv-api | grep -i "SkillConnect catalog ready"

# 5.3 — Extract returns the SkillConnect profile shape (employee{} + 6 lists)
curl -s -X POST localhost:$PORT/api/v1/candidates/extract \
  -H "Authorization: Bearer $KEY" \
  -F "file=@/path/to/a_test_cv.pdf" | jq '.profile | {employee, skills: (.skills[0]), educations: (.educations[0])}'
# expect employee{} populated from spaCy/regex, skills[].name set, codes resolved for catalog hits

# 5.4 — Create from JSON → GET echoes it → rank/search still return names
#        (run an upload + a /candidates/rank against a JD to confirm the full pipeline)
```

---

## 6. Rollback

If anything fails before you trust the new build:

```bash
cd /path/to/prod/cv-intelligence-layer
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

$COMPOSE down
# restore prod-owned files
cp .env.BAK.<ts> .env
cp docker-compose.yml.BAK.<ts> docker-compose.yml
# restore the old image
docker image tag cv-api:cpu-rollback cv-api:cpu
# restore DB (migrations 0004-0007 added tables/data; the dump is at 0003)
$COMPOSE up -d cv-db
cat /root/cv_prod_backup_<ts>.sql | $COMPOSE exec -T cv-db psql -U cv_user -d cv_intelligence
$COMPOSE up -d
```

> Note: code rollback also requires restoring the old `app/`, `prompts/`, `alembic/`. Keep the
> pre-deploy prod tree (or its `cv-images.tar.gz`) around until the new build is signed off.

---

## 7. Post-deploy follow-ups (coordination, not blocking)

- **SkillConnect "Update → PUT"**: their team must call **our PATCH** (JSON) for profile edits.
  Our PUT stays the CV-file replace. Flag this to the integration team.
- **Live catalog refresh**: once Ooredoo's `elevate-api` path is confirmed open from prod, watch
  for `catalog refreshed (221 skills…)` in logs. Until then the seed carries resolution.
- **Old `docker-compose.gpu.yml` on prod** references a default `Dockerfile` prod doesn't have —
  harmless (unused, prod is CPU) but delete it to avoid confusion if you like.
