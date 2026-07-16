from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    from app import create_app
    from app.business_ai.service import run_business_ai
    from app.self_improvement.service import run_self_improvement
    from app.self_learning.service import run_self_learning

    app = create_app()
    with app.app_context():
        lr = run_self_learning()
        ir = run_self_improvement()
        br = run_business_ai()
        print(
            f"learning_patterns={len((lr.to_dict() if lr else {}).get('patterns') or [])} "
            f"improvement={len((ir.to_dict() if ir else {}).get('suggestions') or [])} "
            f"business_ai={'ok' if br else 'none'} applied=False"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
