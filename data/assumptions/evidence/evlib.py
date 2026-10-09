# -*- coding: utf-8 -*-
"""Общие помощники доказательных листов книги: книга-шаблон, запись JSON, sha256. Только stdlib и PyYAML."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

EVIDENCE = Path(__file__).resolve().parent
BOOK_DIR = EVIDENCE.parent                                   # data/assumptions
TEMPLATE = BOOK_DIR / "assumptions_template.yaml"
RECORD = BOOK_DIR / "worlds_source.json"


def template() -> dict:
    """Шаблон книги (значения без миров и надстройки)."""
    return yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))


def record() -> dict:
    """Запись миров семейства (байтовая копия)."""
    return json.loads(RECORD.read_bytes().decode("utf-8"))


def get(d: dict, dotted: str):
    """Значение по точечному пути."""
    for part in dotted.split("."):
        d = d[part]
    return d


def dumps(obj) -> str:
    """Детерминированный JSON выхода листа (UTF-8, отступ 1, LF в конце)."""
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(obj), encoding="utf-8", newline="\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def year_value(traj, year: int) -> float:
    """Значение траектории книги в году по ключам года (MODEL §0.4: ключ года, интерполяция, сход к LT к LT_from,
    плоско назад до первого ключа; квартальные и полугодовые ключи не читаются)."""
    if not isinstance(traj, dict):
        return float(traj)
    pts = sorted((int(k), float(v)) for k, v in traj.items() if str(k).isdigit())
    if str(year) in traj:
        return float(traj[str(year)])
    if not pts:
        return float(traj["LT"])
    if year < pts[0][0]:
        return pts[0][1]
    for (y0, v0), (y1, v1) in zip(pts, pts[1:]):
        if y0 < year < y1:
            return v0 + (v1 - v0) * (year - y0) / (y1 - y0)
    last_y, last_v = pts[-1]
    if "LT" not in traj:
        return last_v
    lt, lt_from = float(traj["LT"]), traj.get("LT_from")
    if lt_from is None or int(lt_from) <= last_y + 1 or year >= int(lt_from):
        return lt
    return last_v + (lt - last_v) * (year - last_y) / (int(lt_from) - last_y)


def read_csv(path: Path) -> list[dict]:
    """Лист CSV как список словарей (UTF-8, с BOM или без)."""
    import csv
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def close(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(float(a) - float(b)) <= tol


class Compare:
    """Сверка чисел листа с книгой: список расхождений для выхода листа и кода возврата."""

    def __init__(self) -> None:
        self.mismatches: list[str] = []

    def eq(self, what: str, book, sheet, tol: float = 1e-9) -> None:
        ok = close(book, sheet, tol) if isinstance(book, (int, float)) and isinstance(sheet, (int, float)) \
            and not isinstance(book, bool) else book == sheet
        if not ok:
            self.mismatches.append(f"{what}: книга {book!r} против листа {sheet!r}")

    def true(self, what: str, cond: bool) -> None:
        if not cond:
            self.mismatches.append(what)
