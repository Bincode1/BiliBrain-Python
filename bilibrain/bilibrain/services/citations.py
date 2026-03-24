from __future__ import annotations

import re


def normalize_answer_citations(text: str) -> str:
    payload = str(text or "")
    if not payload:
        return ""

    payload = re.sub(
        r"[（(]\s*资料\s*((?:\[\d+\]\s*(?:[、，,]\s*\[\d+\]\s*)*))[\s）)]",
        lambda match: "".join(f"【{index}】" for index in re.findall(r"\d+", match.group(1) or "")) or match.group(0),
        payload,
    )
    payload = re.sub(
        r"((?:\[\d+\]\s*(?:[、，,]\s*|\s+)?){2,})",
        lambda match: "".join(f"【{index}】" for index in re.findall(r"\d+", match.group(1) or "")) or match.group(0),
        payload,
    )
    payload = re.sub(r"资料\s*\[(\d+)\]", r"【\1】", payload)
    payload = re.sub(r"资料\s*(\d+)", r"【\1】", payload)
    payload = re.sub(r"\[(\d+)\]", r"【\1】", payload)
    return payload
