"""Pure verdict classification over gathered evidence. No I/O — fully unit-testable.

Thresholds are module constants so a later phase can make them configurable
without touching call sites.
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional

SHIPPED_PCT = 80.0      # >= this % of declared files satisfied -> shipped
PARTIAL_PCT = 20.0      # >= this % -> partial
BOXES_STALE_PCT = 50.0  # checked-box % below this on a shipped plan -> "boxes stale"
DEAD_DAYS = 60          # 0 files satisfied AND untouched beyond this -> dead
FOREIGN_RATIO = 0.7     # >= this fraction of declared paths outside repo -> foreign


@dataclass
class Verdict:
    label: str      # shipped | partial | dead | foreign | manifest-less
    glyph: str
    rationale: str


def classify(
    score,
    checkbox_done: int,
    checkbox_total: int,
    last_touched: Optional[date],
    today: date,
    dead_days: int = DEAD_DAYS,
) -> Verdict:
    if score.total == 0:
        return Verdict("manifest-less", "\U0001f47b",
                       "no file-manifest — needs LLM verdict (Phase 1b)")

    pct = score.pct
    files = f"{score.satisfied}/{score.total} declared files present"

    if pct >= SHIPPED_PCT:
        chk_pct = (checkbox_done / checkbox_total * 100.0) if checkbox_total else 0.0
        stale = " (boxes stale)" if chk_pct < BOXES_STALE_PCT else ""
        return Verdict("shipped", "✅", f"{files}{stale}")

    if pct >= PARTIAL_PCT:
        return Verdict("partial", "\U0001f7e1", files)

    if last_touched is not None and (today - last_touched).days > dead_days:
        age = (today - last_touched).days
        return Verdict("dead", "\U0001f480", f"{files}, untouched {age}d")

    return Verdict("partial", "\U0001f7e1", f"{files} (early)")
