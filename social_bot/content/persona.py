from __future__ import annotations

BLOCKED_PATTERNS = {
    "you'll never see us again",
    "otherwise you'll never",
}


def sanitize_caption(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    lowered = cleaned.lower()
    if any(pattern in lowered for pattern in BLOCKED_PATTERNS):
        raise ValueError("Caption contains manipulative or coercive retention language.")
    return cleaned


def sports_caption(event: dict) -> str:
    subject = event.get("subject", "that performance")
    severity = float(event.get("severity", 0))
    if severity >= 0.9:
        return f"{subject} just submitted a generational disasterclass 💀"
    if severity >= 0.6:
        return f"{subject} might be slightly cooked 😭"
    return f"{subject} having a very normal one, apparently"
