#!/usr/bin/env python3
"""Rank quality evaluation for CV Intelligence Layer.

Two evaluation modes:
  department  — Automated: checks if top-ranked candidates share the JD's
                department. Also measures rank position bias (on-dept vs off-dept).
  expert      — Manual: compares LLM scores against expert-annotated golden set.
                Computes Spearman correlation, top-3 overlap, and score inflation.

Usage:
    # Department-based (automated):
    python eval_rank.py --base-url http://localhost:8001 --api-key KEY \\
        --collection-id UUID --mode department --recall-size 10

    # Expert comparison (requires filled-in golden_set.json):
    python eval_rank.py --base-url http://localhost:8001 --api-key KEY \\
        --collection-id UUID --mode expert --golden-set data/golden_set.json
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


class RankEvalClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0) -> None:
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def rank(self, collection_id: str, jd: dict, recall_size: int = 10) -> dict:
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
        resp = self.client.post("/api/v1/candidates/rank", json=body)
        resp.raise_for_status()
        return resp.json()


def build_ext_id_to_dept(cvs: list[dict], count: int) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for i, cv in enumerate(cvs[:count]):
        mapping[f"E2E-{i + 1:04d}"] = cv["department"]
    return mapping


def spearman_rank_correlation(x: list[float], y: list[float]) -> float | None:
    """Compute Spearman rank correlation without scipy."""
    n = len(x)
    if n < 3:
        return None

    def _ranks(values: list[float]) -> list[float]:
        indexed = sorted(enumerate(values), key=lambda t: t[1])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and indexed[j + 1][1] == indexed[j][1]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                ranks[indexed[k][0]] = avg_rank
            i = j + 1
        return ranks

    rx = _ranks(x)
    ry = _ranks(y)
    d_sq = sum((a - b) ** 2 for a, b in zip(rx, ry))
    return round(1 - (6 * d_sq) / (n * (n * n - 1)), 3)


def eval_department(
    client: RankEvalClient,
    collection_id: str,
    jds: list[dict],
    ext_to_dept: dict[str, str],
    recall_size: int,
    jd_count: int,
) -> dict:
    """Evaluate ranking by checking department relevance and rank position."""
    results = []
    to_eval = jds[:jd_count]

    print(f"\n{'='*60}")
    print(f"RANK EVAL — Department Relevance (recall_size={recall_size})")
    print(f"{'='*60}")
    print(f"  Evaluating {len(to_eval)} job descriptions...\n")

    total_precision = 0.0
    total_dept_mean_rank = 0.0
    total_offdept_mean_rank = 0.0
    valid_count = 0

    for i, jd in enumerate(to_eval, 1):
        dept = jd["department"]
        title = jd["title"]

        try:
            data = client.rank(collection_id, jd, recall_size=recall_size)
        except httpx.HTTPStatusError as e:
            print(f"  [{i}/{len(to_eval)}] ✗ \"{title[:40]}\" — HTTP {e.response.status_code}")
            results.append({"jd_index": i - 1, "title": title, "error": str(e)})
            continue

        ranked = data.get("results", [])
        took_ms = data.get("took_ms", 0)

        on_dept_ranks = []
        off_dept_ranks = []
        on_dept_count = 0

        for rank, r in enumerate(ranked, 1):
            ext_id = r.get("external_id", "")
            if ext_to_dept.get(ext_id) == dept:
                on_dept_count += 1
                on_dept_ranks.append(rank)
            else:
                off_dept_ranks.append(rank)

        precision = on_dept_count / len(ranked) if ranked else 0.0
        dept_mean_rank = sum(on_dept_ranks) / len(on_dept_ranks) if on_dept_ranks else 0.0
        offdept_mean_rank = sum(off_dept_ranks) / len(off_dept_ranks) if off_dept_ranks else 0.0

        total_precision += precision
        if on_dept_ranks:
            total_dept_mean_rank += dept_mean_rank
        if off_dept_ranks:
            total_offdept_mean_rank += offdept_mean_rank
        valid_count += 1

        symbol = "✓" if precision >= 0.5 else "△" if precision > 0 else "✗"
        rank_info = f"avg rank: on-dept={dept_mean_rank:.1f}" if on_dept_ranks else "no on-dept"
        print(
            f"  [{i}/{len(to_eval)}] {symbol} \"{title[:40]}\" — "
            f"{on_dept_count}/{len(ranked)} on-dept "
            f"(P={precision:.0%}, {rank_info}) [{took_ms}ms]"
        )

        results.append({
            "jd_index": i - 1,
            "title": title,
            "department": dept,
            "ranked_count": len(ranked),
            "on_department_count": on_dept_count,
            "precision": round(precision, 3),
            "on_dept_mean_rank": round(dept_mean_rank, 2),
            "off_dept_mean_rank": round(offdept_mean_rank, 2),
            "took_ms": took_ms,
            "candidates": [
                {
                    "rank": idx + 1,
                    "external_id": r.get("external_id", ""),
                    "on_dept": ext_to_dept.get(r.get("external_id", "")) == dept,
                    "score": r.get("score"),
                    "recommendation": r.get("recommendation"),
                    "reasoning": r.get("reasoning", "")[:200],
                }
                for idx, r in enumerate(ranked)
            ],
        })

    mean_precision = total_precision / valid_count if valid_count else 0.0

    print(f"\n{'─'*60}")
    print(f"  Mean Precision@{recall_size}: {mean_precision:.1%}")
    print(f"  JDs evaluated:           {valid_count}/{len(to_eval)}")
    print(f"{'─'*60}\n")

    return {
        "mode": "department",
        "recall_size": recall_size,
        "jd_count": len(to_eval),
        "mean_precision": round(mean_precision, 3),
        "jds_evaluated": valid_count,
        "per_jd": results,
    }


def eval_expert(
    client: RankEvalClient,
    collection_id: str,
    jds: list[dict],
    golden: list[dict],
    recall_size: int,
) -> dict:
    """Evaluate ranking against expert-annotated scores."""
    results = []

    print(f"\n{'='*60}")
    print(f"RANK EVAL — Expert Comparison (recall_size={recall_size})")
    print(f"{'='*60}")
    print(f"  Evaluating {len(golden)} golden entries...\n")

    total_top3_overlap = 0.0
    total_spearman = 0.0
    spearman_count = 0
    inflation_cases = 0
    valid_count = 0

    for i, entry in enumerate(golden, 1):
        jd_index = entry["jd_index"]
        title = entry.get("jd_title", f"JD[{jd_index}]")
        expert_rankings = entry.get("expert_rankings", [])

        if not expert_rankings:
            print(f"  [{i}/{len(golden)}] ⊘ \"{title[:40]}\" — no expert rankings, skipping")
            results.append({"jd_title": title, "skipped": True})
            continue

        if jd_index >= len(jds):
            print(f"  [{i}/{len(golden)}] ✗ \"{title[:40]}\" — jd_index {jd_index} out of range")
            results.append({"jd_title": title, "error": f"jd_index {jd_index} out of range"})
            continue

        jd = jds[jd_index]

        try:
            data = client.rank(collection_id, jd, recall_size=recall_size)
        except httpx.HTTPStatusError as e:
            print(f"  [{i}/{len(golden)}] ✗ \"{title[:40]}\" — HTTP {e.response.status_code}")
            results.append({"jd_title": title, "error": str(e)})
            continue

        ranked = data.get("results", [])
        took_ms = data.get("took_ms", 0)
        llm_by_id = {r["external_id"]: r for r in ranked if r.get("external_id")}
        llm_top3 = {r.get("external_id") for r in ranked[:3]}

        expert_ids = [er["external_id"] for er in expert_rankings]
        expert_top3 = set(expert_ids[:3])
        top3_overlap = len(expert_top3 & llm_top3) / len(expert_top3) if expert_top3 else 0.0
        total_top3_overlap += top3_overlap

        comparisons = []
        expert_scores_list = []
        llm_scores_list = []
        entry_inflations = 0

        for er in expert_rankings:
            ext_id = er["external_id"]
            expert_s = er.get("expert_scores", {})
            llm_r = llm_by_id.get(ext_id)

            if not llm_r:
                comparisons.append({
                    "external_id": ext_id,
                    "in_llm_results": False,
                    "notes": "Not returned by ranking API",
                })
                continue

            expert_overall = expert_s.get("overall", 0) / 100.0
            llm_overall = llm_r.get("score", 0)

            expert_scores_list.append(expert_overall)
            llm_scores_list.append(llm_overall)

            score_fields = ["skills_score", "experience_score", "education_score", "language_score"]
            field_comparisons = {}
            for sf in score_fields:
                e_val = expert_s.get(sf, 0)
                l_val = llm_r.get(sf, 0)
                diff = l_val - e_val
                if diff > 0.3:
                    entry_inflations += 1
                field_comparisons[sf] = {
                    "expert": round(e_val, 2),
                    "llm": round(l_val, 2),
                    "diff": round(diff, 2),
                }

            comparisons.append({
                "external_id": ext_id,
                "in_llm_results": True,
                "expert_overall": round(expert_overall, 3),
                "llm_overall": round(llm_overall, 3),
                "overall_diff": round(llm_overall - expert_overall, 3),
                "fields": field_comparisons,
            })

        inflation_cases += entry_inflations

        spearman = spearman_rank_correlation(expert_scores_list, llm_scores_list)
        if spearman is not None:
            total_spearman += spearman
            spearman_count += 1

        valid_count += 1

        symbol = "✓" if top3_overlap >= 0.67 else "△" if top3_overlap > 0 else "✗"
        sp_str = f"ρ={spearman:.2f}" if spearman is not None else "ρ=N/A"
        print(
            f"  [{i}/{len(golden)}] {symbol} \"{title[:40]}\" — "
            f"top-3 overlap={top3_overlap:.0%}, {sp_str}, "
            f"inflations={entry_inflations} [{took_ms}ms]"
        )

        results.append({
            "jd_title": title,
            "jd_index": jd_index,
            "top3_overlap": round(top3_overlap, 3),
            "spearman": spearman,
            "inflation_count": entry_inflations,
            "took_ms": took_ms,
            "comparisons": comparisons,
        })

    mean_top3 = total_top3_overlap / valid_count if valid_count else 0.0
    mean_spearman = total_spearman / spearman_count if spearman_count else None

    print(f"\n{'─'*60}")
    print(f"  Mean Top-3 Overlap:  {mean_top3:.1%}")
    if mean_spearman is not None:
        print(f"  Mean Spearman ρ:     {mean_spearman:.3f}")
    else:
        print("  Mean Spearman ρ:     N/A (need ≥3 candidates per JD)")
    print(f"  Score Inflations:    {inflation_cases} (LLM > expert by >0.3)")
    print(f"  Evaluated:           {valid_count}/{len(golden)}")
    print(f"{'─'*60}\n")

    return {
        "mode": "expert",
        "recall_size": recall_size,
        "golden_count": len(golden),
        "evaluated": valid_count,
        "mean_top3_overlap": round(mean_top3, 3),
        "mean_spearman": mean_spearman,
        "total_inflation_cases": inflation_cases,
        "per_jd": results,
    }


def save_report(report: dict, mode: str) -> Path:
    REPORT_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = REPORT_DIR / f"rank_eval_{mode}_{ts}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"  Report saved: {path}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank quality evaluation")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--api-key", required=True, help="API key (Bearer token, e.g. APP_API_KEY)")
    parser.add_argument("--collection-id", required=True)
    parser.add_argument("--mode", choices=["department", "expert"], default="department")
    parser.add_argument("--recall-size", type=int, default=10)
    parser.add_argument("--jd-count", type=int, default=0, help="Number of JDs (0=all, department mode only)")
    parser.add_argument("--cv-count", type=int, default=0, help="Number of CVs indexed (for dept mapping)")
    parser.add_argument("--golden-set", type=str, default=str(DATA_DIR / "golden_set.json"))
    args = parser.parse_args()

    client = RankEvalClient(args.base_url, args.api_key, timeout=120.0)

    if args.mode == "department":
        cvs = json.loads((DATA_DIR / "cvs.json").read_text())
        jds = json.loads((DATA_DIR / "jds.json").read_text())
        cv_count = args.cv_count or len(cvs)
        ext_to_dept = build_ext_id_to_dept(cvs, cv_count)
        jd_count = args.jd_count or len(jds)
        report = eval_department(client, args.collection_id, jds, ext_to_dept, args.recall_size, jd_count)
    else:
        golden_data = json.loads(Path(args.golden_set).read_text())
        golden = golden_data.get("rank_golden", [])
        if not golden:
            print("ERROR: No rank_golden entries in golden set file.", file=sys.stderr)
            sys.exit(1)
        jds = json.loads((DATA_DIR / "jds.json").read_text())
        report = eval_expert(client, args.collection_id, jds, golden, args.recall_size)

    report["timestamp"] = datetime.now(timezone.utc).isoformat()
    report["collection_id"] = args.collection_id
    save_report(report, args.mode)


if __name__ == "__main__":
    main()
