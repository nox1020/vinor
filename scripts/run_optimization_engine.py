from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    """Manual background run — outside request path."""
    from app import create_app
    from app.optimization.service import run_optimization

    app = create_app()
    with app.app_context():
        report = run_optimization()
        if report is None:
            print("optimization_disabled_or_failed")
            return 1
        data = report.to_dict()
        print(
            f"report_id={data.get('report_id')} "
            f"suggestions={data.get('optimization_count')} "
            f"duration_ms={data.get('optimization_duration_ms')} "
            f"estimated_gain={data.get('estimated_gain')} "
            f"cost_saving={data.get('cost_saving')} "
            f"applied={data.get('applied')}"
        )
        for s in (data.get("suggestions") or [])[:10]:
            print(
                f"  - [{s.get('priority')}] {s.get('area')}: {s.get('title')} "
                f"(conf={s.get('confidence')})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
