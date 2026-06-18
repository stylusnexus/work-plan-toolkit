"""Deterministic, offline track suggestions for untracked issues (#373).

The LLM path (`auto-triage` → a Claude session writes the answers) is the
higher-quality source, but it only produces suggestions when an agent is driving.
This module is the no-LLM fallback: it scores each untracked issue against each
candidate track using only signals already in hand (no network, no model), so the
VS Code Suggested bucket works standalone.

It emits the SAME v2 answer entries the LLM path does
(`{issue, verdict, track, runner_up, confidence, margin, rationale}`) so the
viewer and `auto-triage --apply` consume it unchanged — abstain-first, with a
grounded rationale naming the concrete signal that matched.

Signals (all local, all explainable):
  * milestone match  — issue.milestone == track.milestone_alignment (strong)
  * track-label match — issue labels ∩ the track's reconcile labels
                        (github.labels, else the default `track/<slug>`) (strong)
  * keyword overlap  — issue-title tokens ∩ the track's slug/name/scope tokens
                       (medium; capped)

Confidence here is a heuristic score, NOT a calibrated probability — the answer
doc is stamped `source: "heuristic"` so the viewer can flag it as lower-trust.
"""
import re

# Weights are deliberately simple and sum-clamped to 1.0. Tuned so a single
# strong signal alone stays below the default suggest bar (0.3 < 0.4/0.5), i.e.
# one weak coincidence won't auto-suggest, but a strong signal does clear it.
_W_MILESTONE = 0.5
_W_LABEL = 0.4
_W_KEYWORD_EACH = 0.1
_W_KEYWORD_CAP = 0.3

# Short / structural words that carry no track-matching signal.
_STOPWORDS = frozenset((
    "the", "a", "an", "and", "or", "to", "of", "for", "in", "on", "with", "is",
    "add", "fix", "update", "support", "make", "use", "new", "issue", "bug",
    "feat", "feature", "error", "when", "after", "before", "via", "from", "into",
))


def _tokens(text):
    """Lowercase alphanumeric tokens of length ≥ 3, minus stopwords."""
    if not text:
        return set()
    return {
        t for t in re.split(r"[^a-z0-9]+", str(text).lower())
        if len(t) >= 3 and t not in _STOPWORDS
    }


def _track_labels(track):
    """A track's effective reconcile labels (lowercased): github.labels if set,
    else the default `track/<slug>` — mirrors reconcile's resolution (#373)."""
    labels = (track.get("labels") or [])
    if labels:
        return {str(x).lower() for x in labels}
    slug = track.get("slug") or ""
    return {f"track/{slug}".lower()} if slug else set()


def score_suggestions(untracked, tracks, *, min_score=0.3, margin_gap=0.15):
    """Score each untracked issue against the candidate tracks and return v2
    suggestion entries (abstain-first).

    `untracked`: [{"number", "title", "milestone": {"title"} | None,
                   "labels": [{"name"}]}] (the auto-triage batch shape).
    `tracks`:    [{"slug", "name", "milestone", "scope", "labels": [..]}].
    `min_score`: a track must clear this for a non-abstain suggestion.
    `margin_gap`: top must beat the runner-up by at least this for margin "clear".
    """
    out = []
    for iss in untracked:
        try:
            num = int(iss.get("number"))
        except (TypeError, ValueError):
            continue

        title_tokens = _tokens(iss.get("title"))
        ms = iss.get("milestone") or {}
        iss_ms = ms.get("title") if isinstance(ms, dict) else None
        iss_labels = {str(lb.get("name", "")).lower()
                      for lb in (iss.get("labels") or []) if isinstance(lb, dict)}

        scored = []  # (score, slug, rationale-parts)
        for t in tracks:
            slug = t.get("slug")
            if not slug:
                continue
            score = 0.0
            reasons = []

            t_ms = t.get("milestone")
            if iss_ms and t_ms and iss_ms == t_ms:
                score += _W_MILESTONE
                reasons.append(f"milestone {iss_ms}")

            shared_labels = iss_labels & _track_labels(t)
            if shared_labels:
                score += _W_LABEL
                reasons.append("label " + ", ".join(sorted(shared_labels)))

            t_kw = _tokens(slug) | _tokens(t.get("name")) | _tokens(t.get("scope"))
            shared_kw = title_tokens & t_kw
            if shared_kw:
                score += min(_W_KEYWORD_CAP, _W_KEYWORD_EACH * len(shared_kw))
                reasons.append("keyword " + ", ".join(sorted(shared_kw)))

            if score > 0:
                scored.append((round(min(score, 1.0), 2), slug, reasons))

        scored.sort(key=lambda x: x[0], reverse=True)

        if not scored or scored[0][0] < min_score:
            out.append({
                "issue": num,
                "verdict": "abstain",
                "rationale": "no track clears the heuristic bar",
            })
            continue

        top = scored[0]
        runner = scored[1] if len(scored) > 1 else None
        clear = runner is None or (top[0] - runner[0]) >= margin_gap
        out.append({
            "issue": num,
            "verdict": "suggest",
            "track": top[1],
            **({"runner_up": runner[1]} if runner else {}),
            "confidence": top[0],
            "margin": "clear" if clear else "narrow",
            "rationale": "; ".join(top[2]),
        })
    return out
