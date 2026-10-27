"""How a verdict looks in a chat. Plain text works everywhere (Telegram, Discord, WhatsApp)."""

from __future__ import annotations

from .agent import Report

BADGE = {"scam": "🔴", "likely_scam": "🟠", "not_sure": "🟡", "looks_safe": "🟢"}
WHY = {"en": "Why", "pcm": "Why"}


def chat_text(report: Report, max_len: int = 3500) -> str:
    v = report.verdict
    by_id = {e.id: e for e in report.evidence}
    # number sources in the order reasons cite them; findings from the same source and link share a number
    sources: list[tuple[str, str]] = []
    num: dict[str, int] = {}
    for r in v.reasons:
        for i in r.evidence:
            if i in by_id and i not in num:
                key = (by_id[i].source, by_id[i].url)
                if key not in sources:
                    sources.append(key)
                num[i] = sources.index(key) + 1

    lines = [f"{BADGE.get(v.verdict, '🟡')} {v.headline}", "", "Why:"]
    for k, r in enumerate(v.reasons, 1):
        refs = "".join(f"[{n}]" for n in dict.fromkeys(num[i] for i in r.evidence if i in num))
        lines.append(f"{k}. {r.text} {refs}".rstrip())
    lines += ["", v.advice]
    if sources:
        lines += ["", "Sources:"]
        for n, (source, url) in enumerate(sources, 1):
            lines.append(f"[{n}] {source}" + (f": {url}" if url else ""))
    text = "\n".join(lines)
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def detail_text(report: Report) -> str:
    """Everything the agent found, for the CLI and for judges."""
    v = report.verdict
    lines = [chat_text(report), "", f"--- all findings ({len(report.evidence)}) via {v.reasoner} in {report.seconds:.1f}s ---"]
    for e in report.evidence:
        lines.append(f"{e.id} [{e.signal}/{e.weight}] {e.source}: {e.finding}" + (f" <{e.url}>" if e.url else ""))
    for n in v.notes:
        lines.append(f"note: {n}")
    from . import zetaris
    lines += ["--- agent trace ---", f"data layer: {zetaris.loaded_from}", *v.trace]
    return "\n".join(lines)
