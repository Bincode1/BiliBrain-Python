from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BenchmarkRow:
    id: str
    query: str
    reference: str
    scope_mode: str | None = None
    folder_id: int | None = None
    bvid: str | None = None
    expected_route_mode: str | None = None
    expected_source_bvids: tuple[str, ...] = ()
    strategy_name: str | None = None


def load_benchmark_rows(path: str | Path) -> list[BenchmarkRow]:
    csv_path = Path(path)
    rows: list[BenchmarkRow] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            query = str(row.get("query") or row.get("user_input") or "").strip()
            reference = str(row.get("reference") or "").strip()
            if not query or not reference:
                continue
            expected_source_bvids = tuple(
                part.strip()
                for part in str(row.get("expected_source_bvids") or "").replace("|", ",").split(",")
                if part.strip()
            )
            rows.append(
                BenchmarkRow(
                    id=str(row.get("id") or f"row-{index}").strip(),
                    query=query,
                    reference=reference,
                    scope_mode=str(row.get("scope_mode") or "").strip() or None,
                    folder_id=_int_or_none(row.get("folder_id")),
                    bvid=str(row.get("bvid") or "").strip() or None,
                    expected_route_mode=str(row.get("expected_route_mode") or "").strip() or None,
                    expected_source_bvids=expected_source_bvids,
                    strategy_name=str(row.get("strategy_name") or "").strip() or None,
                )
            )
    return rows


def _int_or_none(value: object) -> int | None:
    payload = str(value or "").strip()
    return int(payload) if payload else None
