#!/usr/bin/env python3
"""
Benchmark POST /api/search latency using questions from glaive_rag_v1.json.

Measures end-to-end HTTP latency (client-side) and reports p50, p90, p99, etc.

Example:
  python scripts/benchmark_search_latency.py --limit 200
  python scripts/benchmark_search_latency.py --sample 1000 --output-dir benchmark_results
  python scripts/benchmark_search_latency.py --api-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class QueryResult:
    index: int
    question: str
    latency_ms: float
    status_code: int
    ok: bool
    chunk_count: int
    error: str | None = None


@dataclass
class LatencyStats:
    count: int
    success_count: int
    error_count: int
    min_ms: float
    max_ms: float
    mean_ms: float
    median_ms: float
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    stdev_ms: float | None


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (p / 100.0) * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    weight = rank - low
    return sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight


def detect_outlier_indices(
    latencies_ms: list[float],
    *,
    method: str = "tail",
    iqr_multiplier: float = 3.0,
    tail_percentile: float = 98.0,
) -> tuple[set[int], dict]:
    """Return indices of slow-request outliers (values above the computed fence)."""
    meta: dict = {
        "method": method,
        "iqr_multiplier": iqr_multiplier,
        "tail_percentile": tail_percentile,
    }

    if method == "none" or not latencies_ms:
        meta["upper_fence_ms"] = None
        return set(), meta

    if len(latencies_ms) < 4:
        meta["note"] = "fewer than 4 samples; outlier detection skipped"
        meta["upper_fence_ms"] = None
        return set(), meta

    ordered = sorted(latencies_ms)

    if method == "tail":
        upper_fence = _percentile(ordered, tail_percentile)
        meta["upper_fence_ms"] = round(upper_fence, 2)
    elif method == "iqr":
        q1 = _percentile(ordered, 25)
        q3 = _percentile(ordered, 75)
        iqr = q3 - q1
        upper_fence = q3 + iqr_multiplier * iqr
        meta.update(
            {
                "q1_ms": round(q1, 2),
                "q3_ms": round(q3, 2),
                "iqr_ms": round(iqr, 2),
                "upper_fence_ms": round(upper_fence, 2),
            }
        )
    else:
        raise ValueError(f"Unknown outlier method: {method}")

    outliers = {i for i, value in enumerate(latencies_ms) if value > upper_fence}
    return outliers, meta


def compute_stats(latencies_ms: list[float], *, total: int, errors: int) -> LatencyStats:
    if not latencies_ms:
        return LatencyStats(
            count=total,
            success_count=0,
            error_count=errors,
            min_ms=float("nan"),
            max_ms=float("nan"),
            mean_ms=float("nan"),
            median_ms=float("nan"),
            p50_ms=float("nan"),
            p90_ms=float("nan"),
            p95_ms=float("nan"),
            p99_ms=float("nan"),
            stdev_ms=None,
        )

    ordered = sorted(latencies_ms)
    return LatencyStats(
        count=total,
        success_count=len(latencies_ms),
        error_count=errors,
        min_ms=ordered[0],
        max_ms=ordered[-1],
        mean_ms=statistics.mean(ordered),
        median_ms=statistics.median(ordered),
        p50_ms=_percentile(ordered, 50),
        p90_ms=_percentile(ordered, 90),
        p95_ms=_percentile(ordered, 95),
        p99_ms=_percentile(ordered, 99),
        stdev_ms=statistics.stdev(ordered) if len(ordered) > 1 else 0.0,
    )


def load_questions(json_path: Path) -> list[str]:
    with json_path.open(encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array in {json_path}")

    questions: list[str] = []
    for index, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ValueError(f"Entry {index} is not an object")
        question = entry.get("question")
        if not question or not str(question).strip():
            raise ValueError(f"Entry {index} missing non-empty 'question'")
        questions.append(str(question).strip())
    return questions


def search_request(
    api_url: str,
    query: str,
    timeout_s: float,
) -> tuple[float, int, bool, int, str | None]:
    payload = json.dumps({"query": query}).encode("utf-8")
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/api/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read().decode("utf-8")
            latency_ms = (time.perf_counter() - start) * 1000
            status = response.status
            if status != 200:
                return latency_ms, status, False, 0, body[:500]

            parsed = json.loads(body)
            chunks = parsed.get("chunks", [])
            chunk_count = len(chunks) if isinstance(chunks, list) else 0
            return latency_ms, status, True, chunk_count, None
    except urllib.error.HTTPError as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        return latency_ms, exc.code, False, 0, detail or str(exc)
    except urllib.error.URLError as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return latency_ms, 0, False, 0, str(exc.reason)


def select_questions(
    questions: list[str],
    *,
    limit: int | None,
    sample: int | None,
    start_index: int,
    shuffle: bool,
    seed: int | None,
) -> list[tuple[int, str]]:
    indexed = list(enumerate(questions))

    if sample is not None:
        if sample > len(indexed):
            raise ValueError(f"--sample {sample} exceeds dataset size {len(indexed)}")
        rng = random.Random(seed)
        indexed = rng.sample(indexed, sample)
    elif limit is not None:
        indexed = indexed[start_index : start_index + limit]
    else:
        indexed = indexed[start_index:]

    if shuffle:
        rng = random.Random(seed)
        rng.shuffle(indexed)

    return indexed


def write_csv(
    path: Path,
    results: list[QueryResult],
    outlier_indices: set[int],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "index",
                "latency_ms",
                "is_outlier",
                "ok",
                "status_code",
                "chunk_count",
                "error",
                "question",
            ],
        )
        writer.writeheader()
        for row_index, row in enumerate(results):
            writer.writerow(
                {
                    "index": row.index,
                    "latency_ms": round(row.latency_ms, 2),
                    "is_outlier": row.ok and row_index in outlier_indices,
                    "ok": row.ok,
                    "status_code": row.status_code,
                    "chunk_count": row.chunk_count,
                    "error": row.error or "",
                    "question": row.question,
                }
            )


def _format_stats_block(stats: dict, title: str) -> list[str]:
    lines = [title, f"  min:    {stats['min_ms']:.2f}", f"  mean:   {stats['mean_ms']:.2f}"]
    lines.append(f"  median: {stats['median_ms']:.2f}")
    lines.append(f"  p50:    {stats['p50_ms']:.2f}")
    lines.append(f"  p90:    {stats['p90_ms']:.2f}")
    lines.append(f"  p95:    {stats['p95_ms']:.2f}")
    lines.append(f"  p99:    {stats['p99_ms']:.2f}")
    lines.append(f"  max:    {stats['max_ms']:.2f}")
    if stats.get("stdev_ms") is not None:
        lines.append(f"  stdev:  {stats['stdev_ms']:.2f}")
    return lines


def write_summary(path: Path, report: dict) -> None:
    stats: dict = report["stats"]
    raw_stats: dict = report["stats_raw"]
    outliers: dict = report["outliers"]

    lines = [
        "Enterprise RAG — Search latency benchmark",
        "=" * 44,
        f"Generated: {report['generated_at']}",
        f"API: {report['api_url']}",
        f"Dataset: {report['json_path']}",
        f"Queries run: {stats['count']} (success: {stats['success_count']}, errors: {stats['error_count']})",
        "",
    ]
    lines.extend(
        _format_stats_block(
            stats,
            f"Latency (ms) — excluding {outliers['count']} outlier(s) "
            f"(>{outliers.get('upper_fence_ms', 'n/a')} ms, {outliers['method']} method)",
        )
    )
    lines.append("")
    lines.extend(_format_stats_block(raw_stats, "Latency (ms) — all successful requests (raw)"))

    if outliers["count"]:
        lines.append("")
        lines.append("Outliers excluded from primary stats:")
        for item in outliers["items"]:
            preview = item["question"][:80] + ("…" if len(item["question"]) > 80 else "")
            lines.append(
                f"  idx={item['index']}  {item['latency_ms']:.2f} ms  {preview}"
            )

    lines.extend(
        [
            "",
            f"Total benchmark duration: {report['total_duration_s']:.1f}s",
            f"Throughput: {report['queries_per_second']:.2f} queries/s",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_summary(report: dict) -> None:
    stats = report["stats"]
    raw_stats = report["stats_raw"]
    outliers = report["outliers"]

    print()
    print("=" * 60)
    print("SEARCH LATENCY BENCHMARK")
    print("=" * 60)
    print(f"API URL:     {report['api_url']}")
    print(
        f"Queries:     {stats['count']} total | {stats['success_count']} ok | "
        f"{stats['error_count']} failed | {outliers['count']} outlier(s) excluded"
    )
    print(f"Duration:    {report['total_duration_s']:.1f}s ({report['queries_per_second']:.2f} q/s)")
    print()
    print(
        f"Latency (ms) — trimmed (outliers > {outliers.get('upper_fence_ms', 'n/a')} ms excluded)"
    )
    print(f"  p50:  {stats['p50_ms']:>10.2f}")
    print(f"  p90:  {stats['p90_ms']:>10.2f}")
    print(f"  p99:  {stats['p99_ms']:>10.2f}")
    print(f"  min:  {stats['min_ms']:>10.2f}")
    print(f"  max:  {stats['max_ms']:>10.2f}")
    print(f"  mean: {stats['mean_ms']:>10.2f}")
    print()
    print("Latency (ms) — raw (all successful)")
    print(f"  p50:  {raw_stats['p50_ms']:>10.2f}")
    print(f"  p90:  {raw_stats['p90_ms']:>10.2f}")
    print(f"  p99:  {raw_stats['p99_ms']:>10.2f}")
    print(f"  max:  {raw_stats['max_ms']:>10.2f}")
    if outliers["count"]:
        print()
        print("Outliers:")
        for item in outliers["items"]:
            print(f"  idx={item['index']}  {item['latency_ms']:>10.2f} ms")
    print("=" * 60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark /api/search latency from glaive_rag_v1.json questions.",
    )
    parser.add_argument(
        "--json-path",
        type=Path,
        default=Path("glaive_rag_v1.json"),
        help="Path to glaive_rag_v1.json (default: glaive_rag_v1.json)",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="FastAPI base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run first N questions (after --start-index)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Random sample of N questions (overrides --limit)",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="Start offset in dataset (default: 0)",
    )
    parser.add_argument(
        "--shuffle",
        action="store_true",
        help="Shuffle selected questions before running",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for --sample / --shuffle (default: 42)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Per-request timeout in seconds (default: 120)",
    )
    parser.add_argument(
        "--warmup",
        action="store_true",
        help="Send one warmup request before measuring",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmark_results"),
        help="Directory for report files (default: benchmark_results)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation when running full dataset (>1000 queries)",
    )
    parser.add_argument(
        "--outlier-method",
        choices=("tail", "iqr", "none"),
        default="tail",
        help=(
            "Outlier detection: tail=above p98 (default, ~2%% slowest), "
            "iqr=above Q3+k*IQR, none=disabled"
        ),
    )
    parser.add_argument(
        "--outlier-percentile",
        type=float,
        default=98.0,
        help="For --outlier-method tail: fence at this percentile (default: 98)",
    )
    parser.add_argument(
        "--outlier-iqr-multiplier",
        type=float,
        default=3.0,
        help="For --outlier-method iqr: upper fence = Q3 + k*IQR (default: 3.0)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.json_path.is_file():
        print(f"Error: JSON file not found: {args.json_path}", file=sys.stderr)
        return 1

    print(f"Loading questions from {args.json_path}...")
    questions = load_questions(args.json_path)
    print(f"Loaded {len(questions)} questions.")

    selected = select_questions(
        questions,
        limit=args.limit,
        sample=args.sample,
        start_index=args.start_index,
        shuffle=args.shuffle,
        seed=args.seed,
    )

    if not selected:
        print("No queries selected.", file=sys.stderr)
        return 1

    if len(selected) > 1000 and args.limit is None and args.sample is None:
        print(
            f"Warning: running all {len(selected)} queries may take many hours.",
            file=sys.stderr,
        )
        if not args.yes:
            reply = input("Continue? [y/N]: ").strip().lower()
            if reply not in ("y", "yes"):
                print("Aborted.")
                return 0
    elif args.limit is None and args.sample is None:
        print(
            "Tip: use --limit N or --sample N for faster runs "
            f"(dataset has {len(questions)} questions).",
        )

    if args.warmup:
        print("Warmup request...")
        search_request(args.api_url, selected[0][1], args.timeout)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = args.output_dir / f"search_benchmark_{timestamp}"

    results: list[QueryResult] = []
    benchmark_start = time.perf_counter()

    for run_idx, (dataset_index, question) in enumerate(selected, start=1):
        latency_ms, status, ok, chunk_count, error = search_request(
            args.api_url,
            question,
            args.timeout,
        )
        results.append(
            QueryResult(
                index=dataset_index,
                question=question,
                latency_ms=latency_ms,
                status_code=status,
                ok=ok,
                chunk_count=chunk_count,
                error=error,
            )
        )

        status_label = "ok" if ok else "ERR"
        print(
            f"[{run_idx}/{len(selected)}] idx={dataset_index} "
            f"{latency_ms:8.1f}ms {status_label} chunks={chunk_count}",
            flush=True,
        )

        if not ok:
            print(f"  error: {error}", flush=True)

    total_duration_s = time.perf_counter() - benchmark_start
    success_results = [r for r in results if r.ok]
    success_latencies = [r.latency_ms for r in success_results]
    error_count = sum(1 for r in results if not r.ok)

    outlier_local_indices, outlier_meta = detect_outlier_indices(
        success_latencies,
        method=args.outlier_method,
        iqr_multiplier=args.outlier_iqr_multiplier,
        tail_percentile=args.outlier_percentile,
    )

    # Map local success-list indices back to positions in full results list.
    success_positions = [i for i, r in enumerate(results) if r.ok]
    outlier_result_indices = {
        success_positions[i] for i in outlier_local_indices
    }

    trimmed_latencies = [
        latency
        for i, latency in enumerate(success_latencies)
        if i not in outlier_local_indices
    ]

    outlier_items = [
        {
            "index": success_results[i].index,
            "latency_ms": round(success_results[i].latency_ms, 2),
            "question": success_results[i].question,
        }
        for i in sorted(outlier_local_indices)
    ]

    stats_raw = compute_stats(
        success_latencies, total=len(results), errors=error_count
    )
    stats = compute_stats(
        trimmed_latencies, total=len(results), errors=error_count
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "api_url": args.api_url,
        "json_path": str(args.json_path.resolve()),
        "config": {
            "limit": args.limit,
            "sample": args.sample,
            "start_index": args.start_index,
            "shuffle": args.shuffle,
            "seed": args.seed,
            "warmup": args.warmup,
            "timeout_s": args.timeout,
            "outlier_method": args.outlier_method,
            "outlier_percentile": args.outlier_percentile,
            "outlier_iqr_multiplier": args.outlier_iqr_multiplier,
        },
        "dataset_size": len(questions),
        "queries_run": len(results),
        "total_duration_s": round(total_duration_s, 3),
        "queries_per_second": round(len(results) / total_duration_s, 3)
        if total_duration_s > 0
        else 0.0,
        "stats": asdict(stats),
        "stats_raw": asdict(stats_raw),
        "outliers": {
            "count": len(outlier_items),
            "items": outlier_items,
            **outlier_meta,
        },
        "results": [
            {
                **asdict(r),
                "is_outlier": i in outlier_result_indices,
            }
            for i, r in enumerate(results)
        ],
    }

    json_path = Path(f"{prefix}.json")
    csv_path = Path(f"{prefix}.csv")
    summary_path = Path(f"{prefix}_summary.txt")

    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_csv(csv_path, results, outlier_result_indices)
    write_summary(summary_path, report)

    print_summary(report)
    print()
    print(f"Wrote: {json_path}")
    print(f"Wrote: {csv_path}")
    print(f"Wrote: {summary_path}")

    return 0 if error_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
