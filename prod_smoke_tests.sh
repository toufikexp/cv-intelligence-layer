#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════
# prod_smoke_tests.sh — PRODUCTION verification: infra → auth → every API
# Run ON THE PROD HOST, from the prod deploy dir (where docker-compose.yml lives).
#
#   bash prod_smoke_tests.sh
#
# Requires: curl, jq. Prod API is published on host port 8801 (prod compose
# maps 8801:8001). Override with PORT=... if different.
# ════════════════════════════════════════════════════════════════════════
set -uo pipefail

# ── Config (prod) ───────────────────────────────────────────────────────
PORT="${PORT:-8801}"
BASE="http://localhost:${PORT}"
KEY="${APP_API_KEY:-5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8}"
AUTH="Authorization: Bearer ${KEY}"
# A sample CV must exist on the prod host. scp one over and set CV_FILE.
CV_FILE="${CV_FILE:-./sample_cv.pdf}"
DB_EXEC="docker compose exec -T cv-db psql -U cv_user -d cv_intelligence -tA"

pass(){ echo "  ✅ $*"; }
fail(){ echo "  ❌ $*"; }
hdr(){ echo; echo "════════ $* ════════"; }

# ════════════════════════════════════════════════════════════════════════
hdr "PHASE 0 — INFRASTRUCTURE / SYSTEM HEALTH"
# ════════════════════════════════════════════════════════════════════════

echo "[0.1] Containers up + healthy"
docker compose ps

echo "[0.2] Startup markers in logs (catalog + OCR ready)"
docker compose logs cv-api 2>&1 | grep -iE "SkillConnect catalog ready|OCR model ready|Application startup complete" | tail -5 \
  && pass "startup markers present" || fail "missing startup markers — check 'docker compose logs cv-api'"

echo "[0.3] DB migration version == head (0007)"
VER=$($DB_EXEC -c "select version_num from alembic_version;" 2>/dev/null)
[ "$VER" = "0007_fix_corrupted_skill_names" ] && pass "alembic at $VER" || fail "alembic at '$VER' (expected 0007_fix_corrupted_skill_names)"

echo "[0.4] Catalog seed counts (221 / 67 / 5)"
$DB_EXEC -c "select
  (select count(*) from skillconnect_skills),
  (select count(*) from skillconnect_establishments),
  (select count(*) from skillconnect_languages);" 2>/dev/null

echo "[0.5] Redis reachable"
docker compose exec -T cv-redis redis-cli ping 2>/dev/null | grep -q PONG && pass "redis PONG" || fail "redis not responding"

echo "[0.6] Celery worker alive (default,ocr queues)"
docker compose exec -T cv-worker celery -A app.tasks.celery_app inspect ping 2>/dev/null | grep -q pong \
  && pass "worker pong" || fail "worker not responding (check 'docker compose logs cv-worker')"

echo "[0.7] Liveness /health"
curl -fsS "$BASE/health" && pass "/health 200" || fail "/health failed"

echo "[0.8] Readiness /ready (checks DB + Semantic Search reachability)"
curl -fsS "$BASE/ready" && pass "/ready 200" || fail "/ready failed — DB or Semantic Search (nginx:80) unreachable"

echo "[0.9] Prometheus /metrics exposed"
curl -fsS "$BASE/metrics" | grep -q "cvlayer_" && pass "/metrics has cvlayer_* series" || fail "/metrics missing cvlayer_*"

# ════════════════════════════════════════════════════════════════════════
hdr "PHASE 1 — AUTH"
# ════════════════════════════════════════════════════════════════════════

echo "[1.1] No header → 401"
c=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/v1/collections")
[ "$c" = 401 ] && pass "401 unauthenticated" || fail "got $c (expected 401)"

echo "[1.2] Wrong key → 403"
c=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer wrong" "$BASE/api/v1/collections")
[ "$c" = 403 ] && pass "403 bad key" || fail "got $c (expected 403)"

echo "[1.3] Valid key → 200"
c=$(curl -s -o /dev/null -w '%{http_code}' -H "$AUTH" "$BASE/api/v1/collections")
[ "$c" = 200 ] && pass "200 authenticated" || fail "got $c (expected 200)"

# ════════════════════════════════════════════════════════════════════════
hdr "PHASE 2 — COLLECTIONS"
# ════════════════════════════════════════════════════════════════════════

echo "[2.1] Create collection"
COLL=$(curl -fsS -X POST "$BASE/api/v1/collections" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"prod-smoke","description":"smoke test","language":"auto"}' | jq -r '.id')
[ -n "$COLL" ] && [ "$COLL" != null ] && pass "collection $COLL" || { fail "collection create failed"; exit 1; }

echo "[2.2] List collections"
curl -fsS "$BASE/api/v1/collections" -H "$AUTH" | jq '{total, first: .collections[0].name}'

# Pull a REAL seeded skill name so the strict catalog check passes on create
SKILL=$($DB_EXEC -c "select name from skillconnect_skills order by name limit 1;" 2>/dev/null)
echo "  (using seeded skill for create test: '$SKILL')"

# ════════════════════════════════════════════════════════════════════════
hdr "PHASE 3 — EXTRACT (stateless preview, no DB write)"
# ════════════════════════════════════════════════════════════════════════
if [ -f "$CV_FILE" ]; then
  echo "[3.1] POST /candidates/extract → SkillConnect profile shape"
  curl -fsS -X POST "$BASE/api/v1/candidates/extract" -H "$AUTH" -F "file=@${CV_FILE}" \
    | jq '{language, extraction_method,
           employee: .profile.employee,
           n_skills: (.profile.skills|length),
           first_skill: .profile.skills[0],
           first_edu: .profile.educations[0]}' \
    && pass "extract returned a profile" || fail "extract failed"
else
  fail "CV_FILE '$CV_FILE' not found — scp a sample PDF to the prod host and set CV_FILE=..."
fi

# ════════════════════════════════════════════════════════════════════════
hdr "PHASE 4 — CREATE FROM JSON + GET + PATCH"
# ════════════════════════════════════════════════════════════════════════
EXT="SMOKE-001"
echo "[4.1] POST /candidates (JSON profile, real catalog skill)"
CV_ID=$(curl -fsS -X POST "$BASE/api/v1/candidates" -H "$AUTH" -H 'Content-Type: application/json' -d "{
  \"collection_id\": \"$COLL\",
  \"external_id\": \"$EXT\",
  \"profile\": {
    \"summary\": \"Smoke-test candidate\",
    \"employee\": {\"firstname\": \"Test\", \"lastname\": \"Candidate\", \"email\": \"test@example.com\", \"function\": \"Data Engineer\"},
    \"skills\": [{\"skill\": \"$SKILL\", \"score\": \"ADVANCED\"}],
    \"experiences\": [{\"role\": \"Data Engineer\", \"company\": \"ACME\", \"startDate\": \"2020-01-01\", \"endDate\": \"present\"}],
    \"languages\": [{\"language\": \"Anglais\", \"proficiency\": \"C1\"}]
  }
}" | jq -r '.cv_id')
[ -n "$CV_ID" ] && [ "$CV_ID" != null ] && pass "created cv_id $CV_ID" || fail "create failed (422? check skill is a real catalog code/name)"

echo "[4.2] GET /candidates/{cv_id}"
curl -fsS "$BASE/api/v1/candidates/$CV_ID" -H "$AUTH" | jq '{status, external_id, name: .profile.employee.firstname, skills: .profile.skills}'

echo "[4.3] GET by business key /collections/{coll}/candidates/{external_id}"
curl -fsS "$BASE/api/v1/collections/$COLL/candidates/$EXT" -H "$AUTH" | jq '{cv_id, external_id, status}'

echo "[4.4] PATCH /candidates/{cv_id} → updates + re-indexes to Semantic Search"
curl -fsS -X PATCH "$BASE/api/v1/candidates/$CV_ID" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"summary":"Patched summary — senior data engineer"}' | jq '{status, summary: .profile.summary}'

# ════════════════════════════════════════════════════════════════════════
hdr "PHASE 5 — UPLOAD (async pipeline) + STATUS POLL"
# ════════════════════════════════════════════════════════════════════════
if [ -f "$CV_FILE" ]; then
  echo "[5.1] POST /candidates/upload"
  UP=$(curl -fsS -X POST "$BASE/api/v1/candidates/upload" -H "$AUTH" \
    -F "file=@${CV_FILE}" -F "collection_id=$COLL" -F "external_id=SMOKE-UP-001")
  UCV=$(echo "$UP" | jq -r '.cv_id'); JOB=$(echo "$UP" | jq -r '.job_id')
  echo "  cv_id=$UCV job_id=$JOB"

  echo "[5.2] Poll status until ready/failed (max ~90s)"
  for i in $(seq 1 30); do
    ST=$(curl -fsS "$BASE/api/v1/candidates/$UCV/status" -H "$AUTH" | jq -r '.status')
    echo "    [$i] status=$ST"
    [ "$ST" = ready ] && { pass "pipeline reached ready"; break; }
    [ "$ST" = failed ] || [ "$ST" = index_failed ] && { fail "pipeline ended $ST"; break; }
    sleep 3
  done

  echo "[5.3] GET final profile"
  curl -fsS "$BASE/api/v1/candidates/$UCV" -H "$AUTH" | jq '{status, extraction_method, n_skills: (.profile.skills|length)}'
else
  fail "skipping upload pipeline — no CV_FILE"
fi

# ════════════════════════════════════════════════════════════════════════
hdr "PHASE 6 — SEARCH"
# ════════════════════════════════════════════════════════════════════════
echo "[6.1] POST /candidates/search"
curl -fsS -X POST "$BASE/api/v1/candidates/search" -H "$AUTH" -H 'Content-Type: application/json' -d "{
  \"collection_id\": \"$COLL\",
  \"query\": \"data engineer\",
  \"limit\": 10
}" | jq '{total, results: [.results[] | {external_id, score, candidate_name, skills}]}'

# ════════════════════════════════════════════════════════════════════════
hdr "PHASE 7 — RANK (recall + LLM scoring)"
# ════════════════════════════════════════════════════════════════════════
echo "[7.1] POST /candidates/rank against a JD"
curl -fsS -X POST "$BASE/api/v1/candidates/rank" -H "$AUTH" -H 'Content-Type: application/json' -d "{
  \"collection_id\": \"$COLL\",
  \"job_description\": \"Senior Data Engineer with strong ETL and cloud experience.\",
  \"required_skills\": [\"$SKILL\"],
  \"min_experience_years\": 2,
  \"recall_size\": 10
}" | jq '{job_id, results: [.results[] | {external_id, score, recommendation}]}'

# ════════════════════════════════════════════════════════════════════════
hdr "PHASE 8 — SCORE ANSWERS"
# ════════════════════════════════════════════════════════════════════════
echo "[8.1] POST /candidates/score-answers"
curl -fsS -X POST "$BASE/api/v1/candidates/score-answers" -H "$AUTH" -H 'Content-Type: application/json' -d "{
  \"collection_id\": \"$COLL\",
  \"questions\": [{
    \"question_id\": \"q1\",
    \"question_text\": \"What is a star schema?\",
    \"question_type\": \"technical\",
    \"reference_answer\": \"A star schema is a dimensional model with a central fact table linked to dimension tables.\",
    \"candidate_answer\": \"It's a fact table in the middle joined to several dimension tables.\",
    \"max_points\": 10
  }],
  \"use_llm_grading\": true
}" | jq '{total_score, max_score, score_percentage, first: .results[0]}'

# ════════════════════════════════════════════════════════════════════════
hdr "PHASE 9 — PUT (file replace) + DELETE (cleanup)"
# ════════════════════════════════════════════════════════════════════════
if [ -f "$CV_FILE" ] && [ -n "${UCV:-}" ]; then
  echo "[9.1] PUT /candidates/{cv_id} → replace file, re-run pipeline"
  curl -fsS -X PUT "$BASE/api/v1/candidates/$UCV" -H "$AUTH" -F "file=@${CV_FILE}" | jq '{cv_id, job_id, status}'
fi

echo "[9.2] DELETE the JSON-created candidate (removes DB row + search index)"
c=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$BASE/api/v1/candidates/$CV_ID" -H "$AUTH")
[ "$c" = 204 ] && pass "deleted ($c)" || fail "delete got $c (expected 204)"

echo; echo "════════ DONE ════════"
echo "Review ❌ lines above. To fully reset prod test data:"
echo "  docker compose exec -T cv-db psql -U cv_user -d cv_intelligence -c \"truncate table cv_profiles restart identity cascade;\""
echo "  + clear the Semantic Search collection."
