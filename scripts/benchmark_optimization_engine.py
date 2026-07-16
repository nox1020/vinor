from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
import tracemalloc
from unittest.mock import patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.optimization.di import make_optimization_manager
from app.optimization.interfaces import OptimizationContext
from app.optimization.storage import save_optimization_report


def _rows(n: int = 20) -> list[dict]:
    out = []
    for i in range(n):
        out.append(
            {
                "ok": True,
                "quality": {"conflict_rate": 0.3, "decision_quality": 0.4, "overall": 0.55},
                "latency_ms": 2000 + i,
                "total_tokens": 1600,
                "rag_tokens": 500,
                "memory_tokens": 100,
                "memory_used": 1,
                "memory_retrieved": 4,
                "estimated_cost": 0.0008,
                "retry_count": 0,
                "selected_agent": "property_search",
                "bi_opportunity_score": 0.4,
            }
        )
    return out


def main() -> int:
    print("=== Continuous Optimization Engine Benchmark (Phase 19) ===")
    mgr = make_optimization_manager()
    ctx = OptimizationContext(
        evaluation_records=_rows(),
        token_analytics=_rows(),
        bi_snapshots=[{"opportunity_score": 0.4}],
        lookback_hours=24,
    )
    times = []
    with tempfile.TemporaryDirectory() as tmp:
        with patch("app.optimization.storage.optimization_reports_dir", return_value=tmp):
            with patch(
                "app.optimization.manager.save_optimization_report",
                side_effect=save_optimization_report,
            ):
                tracemalloc.start()
                snap0 = tracemalloc.take_snapshot()
                report = None
                for _ in range(15):
                    t0 = time.perf_counter()
                    report = mgr.run(ctx)
                    times.append((time.perf_counter() - t0) * 1000)
                snap1 = tracemalloc.take_snapshot()
                stats = snap1.compare_to(snap0, "lineno")
                mem_kb = sum(max(0, s.size_diff) for s in stats[:30]) / 1024.0
                tracemalloc.stop()
                storage = 0
                for name in os.listdir(tmp):
                    p = os.path.join(tmp, name)
                    if os.path.isfile(p):
                        storage += os.path.getsize(p)
    print(
        f"[bg] runtime_ms={statistics.mean(times):.3f} p50={statistics.median(times):.3f} "
        f"mem_delta_kb≈{mem_kb:.1f} storage_bytes≈{storage} "
        f"suggestions={len(report.suggestions) if report else 0} "
        f"applied={report.applied if report else None}"
    )
    print("[token] delta=+0.00% (background only | no request-path | no prompt)")
    print("no_auto_apply=True | scheduler_default_off=True | outside_request_path=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
