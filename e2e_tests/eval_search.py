#!/usr/bin/env python3
"""Search quality evaluation for CV Intelligence Layer.

Two evaluation modes:
  department  — Automated: checks if search results match the JD's department.
                Uses department tags already present in cvs.json and jds.json.
  golden      — Manual: compares results against expert-annotated golden set.

Usage:
    # Department-based (automated, no manual annotation needed):
    python eval_search.py --base-url http://localhost:8001 --api-key KEY \\
        --collection-id UUID --mode department --limit 10

    # Golden set (requires filled-in golden_set.json):
    python eval_search.py --base-url http://localhost:8001 --api-key KEY \\
        --collection-id UUID --mode golden --golden-set data/golden_set.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).parent / "data"
REPORT_DIR = Path(__file__).parent / "reports"


class SearchEvalClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def search(self, collection_id: str, query: str, limit: int = 10) -> dict:
        resp = self.client.post(
            "/api/v1/candidates/search",
            json={"collection_id": collection_id, "query": query, "limit": limit},
        )
        resp.raise_for_status()
        return resp.json()


def build_ext_id_to_dept(cvs: list[dict], count: int) -> dict[str, str]:
    """Map E2E-XXXX external_ids to department tags."""
    mapping: dict[str, str] = {}
    for i, cv in enumerate(cvs[:count]):
        ext_id = f"E2E-{i + 1:04d}"
        mapping[ext_id] = cv["department"]
    return mapping


def eval_department(
    client: SearchEvalClient,
    collection_id: str,
    jds: list[dict],
    ext_to_dept: dict[str, str],
    limit: int,
    jd_count: int,
) -> dict:
    """Evaluate search by checking department relevance of results."""
    results = []
    to_eval = jds[:jd_count]

    print(f"\n{'='*60}")
    print(f"SEARCH EVAL — Department Relevance (top-{limit})")
    print(f"{'='*60}")
    print(f"  Evaluating {len(to_eval)} job descriptions...\n")

    total_precision = 0.0
    total_recall = 0.0
    total_with_results = 0

    for i, jd in enumerate(to_eval, 1):
        dept = jd["department"]
        query = jd["job_description"]
        title = jd["title"]

        try:
            data = client.search(collection_id, query, limit=limit)
        except httpx.HTTPStatusError as e:
            print(f"  [{i}/{len(to_eval)}] ✗ \"{title[:40]}\" — HTTP {e.response.status_code}")
            results.append({"jd_index": i - 1, "title": title, "error": str(e)})
            continue

        hits = data.get("results", [])
        returned_ids = [h.get("external_id", "") for h in hits]

        on_dept = sum(1 for eid in returned_ids if ext_to_dept.get(eid) == dept)
        total_on_dept_in_collection = sum(1 for d in ext_to_dept.values() if d == dept)

        precision = on_dept / len(returned_ids) if returned_ids else 0.0
        recall = on_dept / total_on_dept_in_collection if total_on_dept_in_collection else 0.0

        if returned_ids:
            total_precision += precision
            total_recall += recall
            total_with_results += 1

        symbol = "✓" if precision >= 0.5 else "△" if precision > 0 else "✗"
        print(
            f"  [{i}/{len(to_eval)}] {symbol} \"{title[:40]}\" — "
            f"{on_dept}/{len(returned_ids)} on-dept "
            f"(P={precision:.0%}, R={recall:.0%})"
        )

        results.append({
            "jd_index": i - 1,
            "title": title,
            "department": dept,
            "returned_count": len(returned_ids),
            "on_department_count": on_dept,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "returned_ids": returned_ids,
        })

    mean_precision = total_precision / total_with_results if total_with_results else 0.0
    mean_recall = total_recall / total_with_results if total_with_results else 0.0

    print(f"\n{'─'*60}")
    print(f"  Mean Precision@{limit}: {mean_precision:.1%}")
    print(f"  Mean Recall@{limit}:    {mean_recall:.1%}")
    print(f"  JDs with results:       {total_with_results}/{len(to_eval)}")
    print(f"{'─'*60}\n")

    return {
        "mode": "department",
        "limit": limit,
        "jd_count": len(to_eval),
        "mean_precision": round(mean_precision, 3),
        "mean_recall": round(mean_recall, 3),
        "jds_with_results": total_with_results,
        "per_jd": results,
    }


def eval_golden(
    client: SearchEvalClient,
    collection_id: str,
    golden: list[dict],
    limit: int,
) -> dict:
    """Evaluate search against expert-annotated golden set."""
    results = []

    print(f"\n{'='*60}")
    print(f"SEARCH EVAL — Golden Set (top-{limit})")
    print(f"{'='*60}")
    print(f"  Evaluating {len(golden)} golden queries...\n")

    total_precision = 0.0
    total_recall = 0.0
    total_mrr = 0.0
    valid_count = 0

    for i, entry in enumerate(golden, 1):
        query = entry["query"]
        expected = set(entry.get("expected_external_ids", []))
        title = entry.get("jd_title", query[:40])

        if not expected:
            print(f"  [{i}/{len(golden)}] ⊘ \"{title[:40]}\" — no expected_external_ids, skipping")
            results.append({"query": query, "skipped": True, "notes": "No expected IDs"})
            continue

        try:
            data = client.search(collection_id, query, limit=limit)
        except httpx.HTTPStatusError as e:
            print(f"  [{i}/{len(golden)}] ✗ \"{title[:40]}\" — HTTP {e.response.status_code}")
            results.append({"query": query, "error": str(e)})
            continue

        hits = data.get("results", [])
        returned_ids = [h.get("external_id", "") for h in hits]
        returned_set = set(returned_ids)

        found = expected & returned_set
        precision = len(found) / len(returned_ids) if returned_ids else 0.0
        recall = len(found) / len(expected) if expected else 0.0

        rr = 0.0
        for rank, eid in enumerate(returned_ids, 1):
            if eid in expected:
                rr = 1.0 / rank
                break

        total_precision += precision
        total_recall += recall
        total_mrr += rr
        valid_count += 1

        symbol = "✓" if recall >= 0.5 else "△" if recall > 0 else "✗"
        print(
            f"  [{i}/{len(golden)}] {symbol} \"{title[:40]}\" — "
            f"found {len(found)}/{len(expected)} expected "
            f"(P={precision:.0%}, R={recall:.0%}, RR={rr:.2f})"
        )

        results.append({
            "query": query,
            "jd_title": title,
            "expected_ids": sorted(expected),
            "found_ids": sorted(found),
            "missing_ids": sorted(expected - returned_set),
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "reciprocal_rank": round(rr, 3),
            "returned_ids": returned_ids,
        })

    mean_p = total_precision / valid_count if valid_count else 0.0
    mean_r = total_recall / valid_count if valid_count else 0.0
    mrr = total_mrr / valid_count if valid_count else 0.0

    print(f"\n{'─'*60}")
    print(f"  Mean Precision@{limit}: {mean_p:.1%}")
    print(f"  Mean Recall@{limit}:    {mean_r:.1%}")
    print(f"  MRR:                    {mrr:.3f}")
    print(f"  Evaluated:              {valid_count}/{len(golden)}")
    print(f"{'─'*60}\n")

    return {
        "mode": "golden",
        "limit": limit,
        "query_count": len(golden),
        "evaluated": valid_count,
        "mean_precision": round(mean_p, 3),
        "mean_recall": round(mean_r, 3),
        "mrr": round(mrr, 3),
        "per_query": results,
    }


def save_report(report: dict, mode: str) -> Path:
    REPORT_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = REPORT_DIR / f"search_eval_{mode}_{ts}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"  Report saved: {path}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Search quality evaluation")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--api-key", required=True, help="API key (Bearer token, e.g. APP_API_KEY)")
    parser.add_argument("--collection-id", required=True)
    parser.add_argument("--mode", choices=["department", "golden"], default="department")
    parser.add_argument("--limit", type=int, default=10, help="Top-K results to evaluate")
    parser.add_argument("--jd-count", type=int, default=0, help="Number of JDs (0=all, department mode only)")
    parser.add_argument("--cv-count", type=int, default=0, help="Number of CVs indexed (for dept mapping)")
    parser.add_argument("--golden-set", type=str, default=str(DATA_DIR / "golden_set.json"))
    args = parser.parse_args()

    client = SearchEvalClient(args.base_url, args.api_key)

    if args.mode == "department":
        cvs = json.loads((DATA_DIR / "cvs.json").read_text())
        jds = json.loads((DATA_DIR / "jds.json").read_text())
        cv_count = args.cv_count or len(cvs)
        ext_to_dept = build_ext_id_to_dept(cvs, cv_count)
        jd_count = args.jd_count or len(jds)
        report = eval_department(client, args.collection_id, jds, ext_to_dept, args.limit, jd_count)
    else:
        golden_data = json.loads(Path(args.golden_set).read_text())
        golden = golden_data.get("search_golden", [])
        if not golden:
            print("ERROR: No search_golden entries in golden set file.", file=sys.stderr)
            sys.exit(1)
        report = eval_golden(client, args.collection_id, golden, args.limit)

    report["timestamp"] = datetime.now(timezone.utc).isoformat()
    report["collection_id"] = args.collection_id
    save_report(report, args.mode)


if __name__ == "__main__":
    main()
