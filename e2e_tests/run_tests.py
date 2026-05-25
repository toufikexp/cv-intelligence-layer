#!/usr/bin/env python3
"""E2E test runner for CV Intelligence Layer APIs.

Usage:
    python run_tests.py --base-url http://localhost:8001 --api-key YOUR_KEY

    # Run specific test groups
    python run_tests.py --tests extract,create,search,rank

    # Control sample sizes
    python run_tests.py --extract-count 10 --create-count 50 --rank-count 20

    # GPU mode (sets EASYOCR_GPU env var for OCR-heavy tests)
    python run_tests.py --mode gpu

Full test flow:
    1. Create a test collection
    2. Extract CVs from PDFs (stateless, no DB)
    3. Create candidates from JSON profiles
    4. Update (PATCH) a subset of candidates
    5. Search candidates with various queries
    6. Rank candidates against job descriptions
    7. Delete all created candidates
    8. Delete test collection
    9. Generate report
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).parent / "data"
REPORT_DIR = Path(__file__).parent / "reports"


# ────────────────────────────────────────────────────────────
# Metrics
# ────────────────────────────────────────────────────────────
@dataclass
class OpResult:
    name: str
    success: bool
    duration_ms: float
    status_code: int | None = None
    error: str | None = None
    detail: dict | None = None


@dataclass
class TestGroupMetrics:
    group: str
    results: list[OpResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def fail_count(self) -> int:
        return self.total - self.success_count

    @property
    def durations_ms(self) -> list[float]:
        return [r.duration_ms for r in self.results if r.success]

    def stats(self) -> dict:
        d = self.durations_ms
        if not d:
            return {
                "count": self.total, "success": 0, "fail": self.fail_count,
                "min_ms": 0, "max_ms": 0, "avg_ms": 0,
                "p50_ms": 0, "p95_ms": 0, "p99_ms": 0,
                "total_ms": 0, "throughput_ops_sec": 0,
            }
        d_sorted = sorted(d)
        total_ms = sum(d)
        return {
            "count": self.total,
            "success": self.success_count,
            "fail": self.fail_count,
            "min_ms": round(min(d), 1),
            "max_ms": round(max(d), 1),
            "avg_ms": round(statistics.mean(d), 1),
            "median_ms": round(statistics.median(d), 1),
            "p50_ms": round(d_sorted[len(d_sorted) * 50 // 100], 1),
            "p95_ms": round(d_sorted[min(len(d_sorted) - 1, len(d_sorted) * 95 // 100)], 1),
            "p99_ms": round(d_sorted[min(len(d_sorted) - 1, len(d_sorted) * 99 // 100)], 1),
            "std_dev_ms": round(statistics.stdev(d), 1) if len(d) > 1 else 0,
            "total_ms": round(total_ms, 1),
            "total_sec": round(total_ms / 1000, 2),
            "throughput_ops_sec": round(len(d) / (total_ms / 1000), 2) if total_ms > 0 else 0,
        }


# ────────────────────────────────────────────────────────────
# API client
# ────────────────────────────────────────────────────────────
class CVApiClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def _timed_request(
        self, method: str, path: str, name: str, **kwargs
    ) -> tuple[OpResult, httpx.Response | None]:
        start = time.perf_counter()
        try:
            resp = self.client.request(method, path, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000
            success = 200 <= resp.status_code < 300
            error = None
            if not success:
                try:
                    error = resp.json().get("detail", resp.text[:200])
                except Exception:
                    error = resp.text[:200]
            return OpResult(
                name=name, success=success, duration_ms=duration_ms,
                status_code=resp.status_code, error=str(error) if error else None,
            ), resp
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            return OpResult(
                name=name, success=False, duration_ms=duration_ms,
                error=str(exc),
            ), None

    def health(self) -> bool:
        res, resp = self._timed_request("GET", "/health", "health_check")
        return res.success

    def create_collection(self, name: str) -> tuple[OpResult, dict | None]:
        res, resp = self._timed_request(
            "POST", "/api/v1/collections", "create_collection",
            json={"name": name, "description": f"E2E test collection {name}"},
        )
        data = resp.json() if resp and res.success else None
        return res, data

    def list_collections(self) -> dict | None:
        res, resp = self._timed_request("GET", "/api/v1/collections", "list_collections")
        if resp and res.success:
            return resp.json()
        return None

    def extract_cv(self, pdf_path: Path) -> tuple[OpResult, dict | None]:
        with open(pdf_path, "rb") as f:
            res, resp = self._timed_request(
                "POST", "/api/v1/candidates/extract", "extract_cv",
                files={"file": (pdf_path.name, f, "application/pdf")},
            )
        data = resp.json() if resp and res.success else None
        return res, data

    def create_candidate(
        self, collection_id: str, external_id: str, profile: dict
    ) -> tuple[OpResult, dict | None]:
        res, resp = self._timed_request(
            "POST", "/api/v1/candidates", "create_candidate",
            json={
                "collection_id": collection_id,
                "external_id": external_id,
                "profile": profile,
            },
        )
        data = resp.json() if resp and res.success else None
        return res, data

    def update_candidate(
        self, cv_id: str, patch: dict
    ) -> tuple[OpResult, dict | None]:
        res, resp = self._timed_request(
            "PATCH", f"/api/v1/candidates/{cv_id}", "update_candidate",
            json=patch,
        )
        data = resp.json() if resp and res.success else None
        return res, data

    def get_candidate(self, cv_id: str) -> tuple[OpResult, dict | None]:
        res, resp = self._timed_request(
            "GET", f"/api/v1/candidates/{cv_id}", "get_candidate",
        )
        data = resp.json() if resp and res.success else None
        return res, data

    def get_candidate_status(self, cv_id: str) -> str | None:
        res, resp = self._timed_request(
            "GET", f"/api/v1/candidates/{cv_id}/status", "get_candidate_status",
        )
        if resp and res.success:
            return resp.json().get("status")
        return None

    def delete_candidate(self, cv_id: str) -> OpResult:
        res, _ = self._timed_request(
            "DELETE", f"/api/v1/candidates/{cv_id}", "delete_candidate",
        )
        return res

    def search_candidates(
        self, collection_id: str, query: str, limit: int = 20
    ) -> tuple[OpResult, dict | None]:
        res, resp = self._timed_request(
            "POST", "/api/v1/candidates/search", "search_candidates",
            json={
                "collection_id": collection_id,
                "query": query,
                "limit": limit,
            },
        )
        data = resp.json() if resp and res.success else None
        return res, data

    def rank_candidates(
        self, collection_id: str, jd: dict, recall_size: int = 10
    ) -> tuple[OpResult, dict | None]:
        body = {
            "collection_id": collection_id,
            "job_description": jd["job_description"],
            "required_skills": jd.get("required_skills"),
            "preferred_skills": jd.get("preferred_skills"),
            "min_experience_years": jd.get("min_experience_years", 0),
            "required_languages": jd.get("required_languages"),
            "education_requirements": jd.get("education_requirements"),
            "recall_size": recall_size,
        }
        res, resp = self._timed_request(
            "POST", "/api/v1/candidates/rank", "rank_candidates",
            json=body,
        )
        data = resp.json() if resp and res.success else None
        return res, data

    def close(self) -> None:
        self.client.close()


# ────────────────────────────────────────────────────────────
# Test groups
# ────────────────────────────────────────────────────────────
def test_extract(
    client: CVApiClient, pdf_dir: Path, count: int
) -> TestGroupMetrics:
    metrics = TestGroupMetrics(group="extract")
    pdf_files = sorted(pdf_dir.glob("*.pdf"))[:count]

    if not pdf_files:
        print("  ⚠ No PDF files found in data/pdfs/. Run generate_data.py first.")
        return metrics

    print(f"  Testing extract API with {len(pdf_files)} PDFs...")
    for i, pdf_path in enumerate(pdf_files, 1):
        res, data = client.extract_cv(pdf_path)
        metrics.results.append(res)
        status = "✓" if res.success else "✗"
        name = data["profile"]["name"] if data else "N/A"
        print(f"    [{i}/{len(pdf_files)}] {status} {pdf_path.name} → {name} ({res.duration_ms:.0f}ms)")

    return metrics


def test_create(
    client: CVApiClient,
    cvs: list[dict],
    collection_id: str,
    count: int,
) -> tuple[TestGroupMetrics, list[dict]]:
    metrics = TestGroupMetrics(group="create")
    created: list[dict] = []
    candidates = cvs[:count]

    print(f"  Creating {len(candidates)} candidates...")
    for i, cv in enumerate(candidates, 1):
        ext_id = f"E2E-{i:04d}"
        res, data = client.create_candidate(collection_id, ext_id, cv["profile"])
        metrics.results.append(res)

        if res.success and data:
            created.append({"cv_id": data["cv_id"], "external_id": ext_id, "data": data})
            if i % 25 == 0 or i == len(candidates):
                print(f"    [{i}/{len(candidates)}] ✓ created ({res.duration_ms:.0f}ms)")
        else:
            err = res.error or "unknown"
            if i % 10 == 0 or not res.success:
                print(f"    [{i}/{len(candidates)}] ✗ {err[:80]} ({res.duration_ms:.0f}ms)")

    return metrics, created


def test_update(
    client: CVApiClient,
    created: list[dict],
    count: int,
) -> TestGroupMetrics:
    metrics = TestGroupMetrics(group="update")
    to_update = created[:count]

    patches = [
        {"summary": "Updated summary via E2E test — experienced professional with diverse skills."},
        {"skills": ["Python", "Leadership", "Strategic Planning", "Communication"]},
        {"location": "Remote"},
        {"current_title": "Senior Consultant"},
        {"phone": "+33 6 00 00 00 00"},
    ]

    print(f"  Updating {len(to_update)} candidates...")
    for i, candidate in enumerate(to_update, 1):
        patch = patches[i % len(patches)]
        res, data = client.update_candidate(candidate["cv_id"], patch)
        metrics.results.append(res)
        status = "✓" if res.success else "✗"
        if i % 10 == 0 or i == len(to_update):
            print(f"    [{i}/{len(to_update)}] {status} PATCH {list(patch.keys())} ({res.duration_ms:.0f}ms)")

    return metrics


def wait_for_indexing(
    client: CVApiClient,
    candidates: list[dict],
    timeout: int = 120,
    poll_interval: float = 2.0,
) -> None:
    """Poll candidate status until all are ready/failed or timeout."""
    pending = {c["cv_id"]: c.get("external_id", c["cv_id"]) for c in candidates}
    start = time.perf_counter()
    ready_count = 0
    failed_count = 0

    print(f"  Waiting for {len(pending)} candidates to be indexed (timeout {timeout}s)...")
    while pending and (time.perf_counter() - start) < timeout:
        done_ids = []
        for cv_id in list(pending.keys()):
            status = client.get_candidate_status(cv_id)
            if status == "ready":
                ready_count += 1
                done_ids.append(cv_id)
            elif status in ("failed", "index_failed"):
                failed_count += 1
                done_ids.append(cv_id)
        for cv_id in done_ids:
            pending.pop(cv_id)
        if pending:
            elapsed = time.perf_counter() - start
            print(
                f"    {ready_count} ready, {failed_count} failed, "
                f"{len(pending)} pending ({elapsed:.0f}s elapsed)"
            )
            time.sleep(poll_interval)

    elapsed = time.perf_counter() - start
    if pending:
        print(f"  ⚠ Timeout after {elapsed:.0f}s — {len(pending)} still pending")
    else:
        print(f"  ✓ All indexed: {ready_count} ready, {failed_count} failed ({elapsed:.0f}s)")


def test_search(
    client: CVApiClient,
    collection_id: str,
    count: int,
) -> TestGroupMetrics:
    metrics = TestGroupMetrics(group="search")

    queries = [
        "Python developer with machine learning experience",
        "Ingénieur DevOps avec expérience Kubernetes",
        "Financial analyst with Excel and SAP",
        "Cybersecurity analyst SIEM Splunk",
        "Data scientist deep learning NLP",
        "Chef de projet agile Scrum",
        "Marketing digital SEO Google Analytics",
        "HR manager talent acquisition",
        "Civil engineer AutoCAD structural",
        "Sales manager B2B CRM Salesforce",
        "Développeur full stack React Node.js",
        "Cloud architect AWS Terraform",
        "Analyste financier contrôle de gestion",
        "Machine learning engineer PyTorch TensorFlow",
        "Responsable RH formation développement",
        "Penetration tester OSCP security",
        "Product owner agile backlog",
        "Ingénieur qualité ISO 9001 Six Sigma",
        "Business developer SaaS enterprise",
        "Data engineer Spark Hadoop ETL",
        "Comptable senior IFRS consolidation",
        "Architecte logiciel microservices",
        "Senior consultant management strategy",
        "Network security firewall IDS",
        "Growth hacker acquisition marketing automation",
    ]

    search_queries = queries[:count]
    print(f"  Running {len(search_queries)} search queries...")
    for i, query in enumerate(search_queries, 1):
        res, data = client.search_candidates(collection_id, query, limit=10)
        metrics.results.append(res)
        status = "✓" if res.success else "✗"
        n_results = data.get("total", 0) if data else 0
        print(f"    [{i}/{len(search_queries)}] {status} \"{query[:50]}\" → {n_results} hits ({res.duration_ms:.0f}ms)")

    return metrics


def test_rank(
    client: CVApiClient,
    jds: list[dict],
    collection_id: str,
    count: int,
) -> TestGroupMetrics:
    metrics = TestGroupMetrics(group="rank")
    to_rank = jds[:count]

    print(f"  Ranking against {len(to_rank)} job descriptions...")
    for i, jd in enumerate(to_rank, 1):
        res, data = client.rank_candidates(collection_id, jd, recall_size=10)
        metrics.results.append(res)
        status = "✓" if res.success else "✗"
        n_results = len(data.get("results", [])) if data else 0
        took = data.get("took_ms", 0) if data else 0
        print(
            f"    [{i}/{len(to_rank)}] {status} \"{jd['title'][:40]}\" "
            f"→ {n_results} ranked (API: {took}ms, total: {res.duration_ms:.0f}ms)"
        )

    return metrics


def test_delete(
    client: CVApiClient,
    created: list[dict],
) -> TestGroupMetrics:
    metrics = TestGroupMetrics(group="delete")

    print(f"  Deleting {len(created)} candidates...")
    for i, candidate in enumerate(created, 1):
        res = client.delete_candidate(candidate["cv_id"])
        metrics.results.append(res)
        if i % 25 == 0 or i == len(created):
            status = "✓" if res.success else "✗"
            print(f"    [{i}/{len(created)}] {status} ({res.duration_ms:.0f}ms)")

    return metrics


# ────────────────────────────────────────────────────────────
# Report
# ────────────────────────────────────────────────────────────
def generate_report(
    all_metrics: list[TestGroupMetrics],
    mode: str,
    total_duration_sec: float,
    args: argparse.Namespace,
) -> dict:
    report = {
        "test_run": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "base_url": args.base_url,
            "total_duration_sec": round(total_duration_sec, 2),
            "config": {
                "extract_count": args.extract_count,
                "create_count": args.create_count,
                "update_count": args.update_count,
                "search_count": args.search_count,
                "rank_count": args.rank_count,
            },
        },
        "summary": {
            "total_operations": sum(m.total for m in all_metrics),
            "total_success": sum(m.success_count for m in all_metrics),
            "total_failures": sum(m.fail_count for m in all_metrics),
            "overall_success_rate": 0.0,
        },
        "groups": {},
        "errors": [],
    }

    total_ops = report["summary"]["total_operations"]
    if total_ops > 0:
        report["summary"]["overall_success_rate"] = round(
            report["summary"]["total_success"] / total_ops * 100, 2
        )

    for m in all_metrics:
        report["groups"][m.group] = m.stats()

    for m in all_metrics:
        for r in m.results:
            if not r.success:
                report["errors"].append({
                    "group": m.group,
                    "operation": r.name,
                    "status_code": r.status_code,
                    "error": r.error,
                    "duration_ms": round(r.duration_ms, 1),
                })

    return report


def print_report(report: dict) -> None:
    print("\n" + "=" * 80)
    print("  E2E TEST REPORT")
    print("=" * 80)

    run = report["test_run"]
    print(f"\n  Timestamp:      {run['timestamp']}")
    print(f"  Mode:           {run['mode']}")
    print(f"  Base URL:       {run['base_url']}")
    print(f"  Total Duration: {run['total_duration_sec']:.2f}s")

    summary = report["summary"]
    print(f"\n  Total Ops:      {summary['total_operations']}")
    print(f"  Success:        {summary['total_success']}")
    print(f"  Failures:       {summary['total_failures']}")
    print(f"  Success Rate:   {summary['overall_success_rate']:.1f}%")

    print(f"\n  {'Group':<12} {'Count':>6} {'OK':>5} {'Fail':>5} {'Min':>8} {'Avg':>8} {'P50':>8} {'P95':>8} {'P99':>8} {'Max':>8} {'Ops/s':>7}")
    print(f"  {'─' * 12} {'─' * 6} {'─' * 5} {'─' * 5} {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 7}")

    for group_name, stats in report["groups"].items():
        print(
            f"  {group_name:<12} "
            f"{stats['count']:>6} "
            f"{stats['success']:>5} "
            f"{stats['fail']:>5} "
            f"{stats['min_ms']:>7.0f}{'ms'} "
            f"{stats['avg_ms']:>7.0f}{'ms'} "
            f"{stats['p50_ms']:>7.0f}{'ms'} "
            f"{stats['p95_ms']:>7.0f}{'ms'} "
            f"{stats['p99_ms']:>7.0f}{'ms'} "
            f"{stats['max_ms']:>7.0f}{'ms'} "
            f"{stats['throughput_ops_sec']:>6.1f}"
        )

    errors = report.get("errors", [])
    if errors:
        print(f"\n  Errors ({len(errors)}):")
        shown = errors[:20]
        for e in shown:
            print(f"    [{e['group']}] HTTP {e.get('status_code', '?')}: {(e.get('error') or 'unknown')[:100]}")
        if len(errors) > 20:
            print(f"    ... and {len(errors) - 20} more")

    print("\n" + "=" * 80)


# ────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="E2E test runner for CV Intelligence Layer")
    parser.add_argument("--base-url", default="http://localhost:8001", help="API base URL")
    parser.add_argument("--api-key", required=True, help="API key (Bearer token)")
    parser.add_argument("--mode", choices=["cpu", "gpu"], default="cpu", help="CPU or GPU mode")
    parser.add_argument("--tests", default="extract,create,update,search,rank,delete",
                        help="Comma-separated list of test groups to run")
    parser.add_argument("--extract-count", type=int, default=20, help="Number of PDFs to extract")
    parser.add_argument("--create-count", type=int, default=200, help="Number of candidates to create")
    parser.add_argument("--update-count", type=int, default=30, help="Number of candidates to update")
    parser.add_argument("--search-count", type=int, default=25, help="Number of search queries")
    parser.add_argument("--rank-count", type=int, default=10, help="Number of JDs to rank against")
    parser.add_argument("--collection-name", default=None,
                        help="Name for a new test collection (auto-generated if omitted). Ignored if --collection-id is set.")
    parser.add_argument("--collection-id", default=None,
                        help="Use an existing collection (mirrors HR platform flow with predefined collections). "
                             "Skips collection creation entirely.")
    parser.add_argument("--timeout", type=float, default=120.0, help="HTTP timeout in seconds")
    parser.add_argument("--index-timeout", type=int, default=120,
                        help="Max seconds to wait for Semantic Search indexing before search/rank tests")
    parser.add_argument("--keep-data", action="store_true", help="Don't delete candidates after test")
    args = parser.parse_args()

    if args.mode == "gpu":
        os.environ["EASYOCR_GPU"] = "true"
        print("GPU mode: set EASYOCR_GPU=true (applies to OCR-triggered extractions only)")

    test_groups = [t.strip() for t in args.tests.split(",")]

    cvs_path = DATA_DIR / "cvs.json"
    jds_path = DATA_DIR / "jds.json"
    pdf_dir = DATA_DIR / "pdfs"

    if not cvs_path.exists() or not jds_path.exists():
        print("Test data not found. Run generate_data.py first:")
        print("  python e2e_tests/generate_data.py")
        sys.exit(1)

    with open(cvs_path, encoding="utf-8") as f:
        all_cvs = json.load(f)
    with open(jds_path, encoding="utf-8") as f:
        all_jds = json.load(f)

    print(f"Loaded {len(all_cvs)} CVs, {len(all_jds)} JDs, {len(list(pdf_dir.glob('*.pdf')))} PDFs")

    client = CVApiClient(args.base_url, args.api_key, timeout=args.timeout)

    all_metrics: list[TestGroupMetrics] = []
    created_candidates: list[dict] = []
    setup_metrics = TestGroupMetrics(group="setup")
    all_metrics.append(setup_metrics)
    collection_id: str | None = None
    total_start = time.perf_counter()

    try:
        print("\nChecking API health...")
        if not client.health():
            print("✗ API is not healthy. Check that the server is running.")
            return
        print("✓ API is healthy\n")

        if args.collection_id:
            collection_id = args.collection_id
            print(f"Using existing collection: {collection_id}\n")
        else:
            collection_name = args.collection_name or f"e2e-test-{uuid.uuid4().hex[:8]}"
            print(f"Creating test collection: {collection_name}")
            coll_res, collection = client.create_collection(collection_name)
            setup_metrics.results.append(coll_res)
            if not collection:
                print(f"✗ Failed to create collection (HTTP {coll_res.status_code}): {coll_res.error}")
                print("  → The CV layer's SEARCH_API_KEY may lack collection-create permission.")
                print("  → Pre-create a collection out-of-band and re-run with --collection-id <uuid>.")
                return
            collection_id = collection["id"]
            print(f"✓ Collection created: {collection_id}\n")

        if "extract" in test_groups:
            print("━" * 60)
            print("TEST GROUP: Extract CV (stateless)")
            print("━" * 60)
            m = test_extract(client, pdf_dir, args.extract_count)
            all_metrics.append(m)
            print(f"  Done: {m.success_count}/{m.total} succeeded\n")

        if "create" in test_groups:
            print("━" * 60)
            print("TEST GROUP: Create Candidates (JSON)")
            print("━" * 60)
            m, created_candidates = test_create(
                client, all_cvs, collection_id, args.create_count
            )
            all_metrics.append(m)
            print(f"  Done: {m.success_count}/{m.total} created\n")

        if "update" in test_groups and created_candidates:
            print("━" * 60)
            print("TEST GROUP: Update Candidates (PATCH)")
            print("━" * 60)
            m = test_update(client, created_candidates, args.update_count)
            all_metrics.append(m)
            print(f"  Done: {m.success_count}/{m.total} updated\n")

        needs_indexed = ("search" in test_groups or "rank" in test_groups)
        if needs_indexed and created_candidates:
            print("━" * 60)
            print("WAIT: Indexing completion (Semantic Search embedding)")
            print("━" * 60)
            wait_for_indexing(client, created_candidates, timeout=args.index_timeout)
            print()

        if "search" in test_groups:
            print("━" * 60)
            print("TEST GROUP: Search Candidates")
            print("━" * 60)
            m = test_search(client, collection_id, args.search_count)
            all_metrics.append(m)
            print(f"  Done: {m.success_count}/{m.total} queries\n")

        if "rank" in test_groups:
            print("━" * 60)
            print("TEST GROUP: Rank Candidates (AI Search)")
            print("━" * 60)
            m = test_rank(client, all_jds, collection_id, args.rank_count)
            all_metrics.append(m)
            print(f"  Done: {m.success_count}/{m.total} rankings\n")

        if "delete" in test_groups and created_candidates and not args.keep_data:
            print("━" * 60)
            print("TEST GROUP: Delete Candidates")
            print("━" * 60)
            m = test_delete(client, created_candidates)
            all_metrics.append(m)
            print(f"  Done: {m.success_count}/{m.total} deleted\n")
        elif args.keep_data:
            print(f"\n  --keep-data: skipping deletion of {len(created_candidates)} candidates")

    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
    except Exception as exc:
        print(f"\n\n✗ Unexpected error: {exc}")
    finally:
        total_duration = time.perf_counter() - total_start
        client.close()

        non_empty_metrics = [m for m in all_metrics if m.total > 0]
        report = generate_report(non_empty_metrics, args.mode, total_duration, args)
        print_report(report)

        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = REPORT_DIR / f"e2e_report_{args.mode}_{ts}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n  Report saved: {report_path}")


if __name__ == "__main__":
    main()
