from collections.abc import Iterable


def split_text(text: str, max_len: int = 4096, max_parts: int = 3) -> list[str]:
    parts = []
    remaining = text
    while remaining and len(parts) < max_parts:
        part = remaining[:max_len]
        parts.append(part)
        remaining = remaining[max_len:]
    if remaining:
        parts[-1] = parts[-1] + "\n(…обрезано)"
    return parts


def summarize_placeholder(text: str) -> str:
    if len(text) <= 400:
        return text
    return text[:400] + "…"


def iter_chunks(items: Iterable[str], max_len: int = 4096) -> list[str]:
    return split_text("\n".join(items), max_len=max_len)
