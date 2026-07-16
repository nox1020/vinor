from __future__ import annotations

from app.memory.interfaces import MemoryItem, MemorySummarizer


class CompactMemorySummarizer(MemorySummarizer):
    """Budget-aware summarizer: compact lines, no duplication."""

    def summarize(self, items: list[MemoryItem], *, budget_chars: int) -> str:
        if not items:
            return ""
        budget = max(40, int(budget_chars or 280))
        lines: list[str] = []
        used = 0
        seen_vals: set[str] = set()
        for it in items:
            val = (it.value or "").strip()
            if not val:
                continue
            norm = val.lower()
            if norm in seen_vals:
                continue
            seen_vals.add(norm)
            line = f"- {val}"
            if used + len(line) + 1 > budget:
                break
            lines.append(line)
            used += len(line) + 1
        if not lines:
            return ""
        return "=== حافظه مرتبط کاربر ===\n" + "\n".join(lines)
