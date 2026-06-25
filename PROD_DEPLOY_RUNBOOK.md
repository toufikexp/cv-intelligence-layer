# Production Deployment Runbook — SkillConnect-native CV Intelligence Layer

**Target:** Promote dev (`0007`, SkillConnect-native model + catalogs) onto prod, which runs the
old flat-model build at migration `0003`.

**Prod facts (settled — correct me if any line is wrong):**
- Single host, **CPU only**, inside Ooredoo's network. Semantic Search is co-located; the CV
  layer reaches it at `http://nginx:80` over the external `shared-ingress` docker network.
- **Prod runs entirely from the `cv-api:cpu` image.** Its compose has **no code bind-mounts** —
  only `data/uploads` and `cv-models/fasttext/lid.176.bin`. So `app/`, `prompts/`, `schemas/`,
  `alembic/` are **baked into the image at build time**, not read from the host.
- Deploy pattern = **build on dev (WSL) → `docker save` → `cv-images.tar.gz` → copy → `docker
  load` on prod.** No git on prod, no build on prod, no PyTorch CDN needed on prod.
- Prod's base `docker-compose.yml` is **already** the full prod CPU config → use **plain
  `docker compose`** on prod (no `-f … -f docker-compose.prod.yml` overlay).
- Prod data is test/disposable → **clean-slate cutover** (old flat-model rows break the new code).

> Because everything ships inside the image, the ONLY host-side changes on prod are: load the new
> image, the `.env` additions (✅ already done in step 2), run migrations, clear data. No source
> tree copy to prod is required.

---

## 1. Build the image on dev (WSL) and export it

```bash
cd ~/cv-intelligence-layer

# Build the CPU image. Dockerfile.cpu bakes torch (PyTorch CDN), EasyOCR weights
# (from ./easyocr-models), and spaCy wheels (from ./cv-models/spacy) — all of which
# you already have locally on the dev box.
docker build -f Dockerfile.cpu -t cv-api:cpu .

# Sanity-check the new code + models are actually in the image
docker run --rm cv-api:cpu alembic heads          # expect 0007_fix_corrupted_skill_names
docker run --rm cv-api:cpu ls /opt/easyocr-models # craft_mlt_25k.pth + lang weights
docker run --rm cv-api:cpu python -c "import spacy; spacy.load('fr_core_news_sm'); spacy.load('en_core_web_sm'); print('spaCy OK')"

# Export for transfer
docker save cv-api:cpu | gzip > cv-images.tar.gz
```

Copy `cv-images.tar.gz` to the prod host (scp/USB/whatever you use today).

---

## 2. `.env` additions on prod — ✅ ALREADY DONE

You appended the SkillConnect + Gemini-cache keys. Nothing more here. For the record, the block
was:

```
SKILLCONNECT_API_BASE_URL=https://elevate.ooredoo.dz/elevate-api
SKILLCONNECT_SSL_VERIFY=true
# SKILLCONNECT_PROXY=http://proxy:8080
SKILLCONNECT_REFRESH_SECONDS=3600
GEMINI_CACHE_ENABLED=true
GEMINI_CACHE_TTL_SECONDS=3600
```

> Catalog refresh is **fail-soft**: if `elevate.ooredoo.dz` is unreachable at startup it logs a
> warning and runs on the seeded catalog (221/67/5 from migration 0006). Safe to leave the URL set.

---

## 3. Pre-flight on PROD (rollback anchors)

```bash
cd /path/to/prod/cv-intelligence-layer        # where prod's docker-compose.yml + .env live

# 3.1 — Confirm current state
docker compose ps
docker compose exec cv-db psql -U cv_user -d cv_intelligence -c \
  "select version_num from alembic_version;"   # expect 0003_external_id_required

# 3.2 — Keep the OLD image as a rollback target (do this BEFORE docker load)
docker image tag cv-api:cpu cv-api:cpu-rollback

# 3.3 — Back up the DB
docker compose exec -T cv-db pg_dump -U cv_user -c cv_intelligence \
  > /root/cv_prod_backup_$(date +%Y%m%d_%H%M%S).sql   # -c = include DROPs, clean restore
```

---

## 4. Load the new image on PROD

```bash
docker load < cv-images.tar.gz        # overwrites the cv-api:cpu tag with the new build
docker image inspect cv-api:cpu --format '{{.Id}}'   # note new id (differs from rollback tag)
```

> No rebuild on prod, no source copy. The compose file already pins `image: cv-api:cpu`.

---

## 5. Stop, migrate, clean-slate, start

```bash
cd /path/to/prod/cv-intelligence-layer

# 5.1 — Stop app + worker; keep DB + redis running for the migration
docker compose stop cv-api cv-worker

# 5.2 — Run migrations 0004→0007 from the NEW image (alembic + migrations are baked in).
#        --rm one-off container; reads DATABASE_URL from compose env.
docker compose run --rm cv-api alembic upgrade head
docker compose run --rm cv-api alembic current      # expect 0007_fix_corrupted_skill_names

# 5.3 — Verify the catalog seed landed
docker compose exec -T cv-db psql -U cv_user -d cv_intelligence -c \
  "select (select count(*) from skillconnect_skills)         as skills,
          (select count(*) from skillconnect_establishments) as estabs,
          (select count(*) from skillconnect_languages)      as langs;"
# expect 221 | 67 | 5

# 5.4 — CLEAN-SLATE: old flat-model rows are incompatible with the new code.
docker compose exec -T cv-db psql -U cv_user -d cv_intelligence -c \
  "truncate table cv_profiles restart identity cascade;"
#  ^ confirm cv_profiles is the only CV-data table; cascade clears dependents.

# 5.5 — Clear the Semantic Search collection (remove old-shape docs).
#        << prod-specific: use whatever you use to empty the SS collection
#           (its admin/delete API or drop+recreate). CV layer re-indexes on next upload. >>

# 5.6 — Start everything
docker compose up -d
docker compose ps
```

---

## 6. Smoke tests

```bash
PORT=8801
KEY=<prod APP_API_KEY from .env>

curl -s localhost:$PORT/health
curl -s localhost:$PORT/ready                    # checks DB + Semantic Search reachability
docker compose logs cv-api | grep -i "SkillConnect catalog ready"

# Extract → SkillConnect shape (employee{} from spaCy/regex + 6 lists, skill codes resolved)
curl -s -X POST localhost:$PORT/api/v1/candidates/extract \
  -H "Authorization: Bearer $KEY" \
  -F "file=@/path/to/a_test_cv.pdf" \
  | jq '.profile | {employee, first_skill: .skills[0], first_edu: .educations[0]}'

# Full pipeline: upload a CV, then rank against a JD → results still carry names + external_id
```

---

## 7. Rollback

```bash
cd /path/to/prod/cv-intelligence-layer

docker compose down

# 7.1 — Restore the old image
docker image tag cv-api:cpu-rollback cv-api:cpu

# 7.2 — Restore the DB to its 0003 state. The dump was taken with -c (clean), so it
#        DROPs the new catalog tables + cv_profiles and recreates the old schema/rows.
docker compose up -d cv-db
sleep 5
docker compose exec -T cv-db psql -U cv_user -d cv_intelligence < /root/cv_prod_backup_<ts>.sql

# 7.3 — Revert the .env additions (optional; the old image ignores the new keys anyway)
#        and bring prod back up
docker compose up -d
docker compose exec -T cv-db psql -U cv_user -d cv_intelligence -c \
  "select version_num from alembic_version;"     # expect 0003 again
```

> Keep `cv-images.tar.gz` of the OLD build (or the `cv-api:cpu-rollback` tag) until the new
> deploy is signed off. The `.env` keys are forward-only and harmless to the old image.

---

## 8. Post-deploy (coordination, not blocking)

- **SkillConnect "Update → PUT"** maps to **our PATCH** (JSON). Our PUT stays the CV-file replace.
  Tell the integration team to call PATCH.
- **Live catalog refresh:** once the prod network can reach `elevate.ooredoo.dz`, watch for
  `catalog refreshed (221 skills…)` in the logs. Until then the seed carries resolution.
- The stray `Dockerfile.gpu` / `docker-compose.gpu.yml` on prod are unused (prod is CPU) — delete
  them if you want to avoid confusion. They are not part of this deploy.
