from __future__ import annotations

from app import create_app
from app.knowledge.rag.retriever import LandsRagRetriever


def main() -> int:
    app = create_app()
    with app.app_context():
        retriever = LandsRagRetriever()
        retriever.ensure_index()
        print("RAG index ready: lands.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

