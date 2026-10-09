# -*- coding: utf-8 -*-
"""Малые входы доказательных листов книги из листов этапа 1 ($BANK_HANDOFF_DIR) → evidence/<область>/inputs/.

Входы кладутся под теми же относительными путями, что в папке передачи (inputs/stage1/ifrs/ifrs_quarterly.csv …),
поэтому перенесённые скрипты этапа 1 меняют только корень путей. Большие листы сокращаются до строк, которые читают
скрипты области: строка остаётся, если значения её столбцов-ключей (metric, period, code …) встречаются как строковые
литералы в коде области (разбор ast) либо подходят под названный у листа шаблон; столбцы с происхождением (doc, page,
sha256) не трогаются. Правильность отбора проверяется воспроизведением: скрипт области на малых входах даёт те же
числа, что на полных листах (README области; архивный тест `tests/test_book_evidence.py`).
Первичка (PDF, XLSX) в репозиторий не кладётся — только ссылкой и sha256 внутри листов. Ответы брокерского API в
репозиторий не кладутся вовсе — ни файлом, ни выпиской полей: дивиденды — лист решений собраний с документом эмитента
и новостью с датой у каждой строки.

Запуск из корня репозитория (нужна папка передачи):
  BANK_HANDOFF_DIR=<папка> python data/assumptions/evidence/extract_inputs.py [область ...] [--check]
--check — сравнить с лежащими входами, ничего не писать (выход 1 при расхождении).
Рядом с входами пишется inputs/SOURCES.json: путь, sha256 полного листа, sha256 малого входа, строк оставлено / всего.
Файл входов, которого опись больше не называет, удаляется (--check — расхождение).
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

ALL = None                                        # взять лист целиком


def by(*cols: str, rx: str | None = None) -> tuple:
    """Отбор строк: значения этих столбцов — литералы кода области (или подходят под шаблон `rx` первого столбца)."""
    return (cols, re.compile(rx) if rx else None)


# область → (скрипты области, {относительный путь в папке передачи: отбор})
AREAS: dict[str, tuple[tuple[str, ...], dict[str, tuple | None]]] = {
    "regulation": (("floors.py",), {
        "stage1/regulation/schedule.yaml": ALL,
        "stage1/calib/capital/out/p3_floors.csv": ALL,
    }),
    "capital": (("cc_common.py", "p1_bridge.py", "p2_rwa.py", "p3467_misc.py", "p5_growth_trial.py", "make_keys.py",
                 "capital_book.py"), {
        "stage1/ras/group_f805.csv": ALL,
        "stage1/ras/group_n20_vs_bank_n1.csv": ALL,
        "stage1/ras/bridge_ifrs_to_group_capital.csv": ALL,
        "stage1/ras/pnl_ifrs_vs_group_vs_bank_quarterly.csv": ALL,
        "stage1/ras/cbr_f123_wide.csv": ALL,
        "stage1/ras/cbr_f135_wide.csv": ALL,
        "stage1/ras/cbr_f101_agg.csv": by("row_kind", "code"),
        "stage1/ifrs/ifrs_quarterly.csv": by("metric"),
        "stage1/ifrs/ifrs_history.csv": by("metric"),
        "stage1/ifrs/anchor_books.csv": ALL,
        "stage1/mgmt/mgmt_kpi.csv": by("period"),
        "stage1/regulation/schedule.yaml": ALL,
        "stage1/worlds/bank_overlay_draft.yaml": ALL,
        "stage1/calib/capital/inputs/zcyc_quarter_ends_2024_2026.csv": ALL,
        "research/facts/t_quarterly.csv": by("metric"),
        "research/facts/t_capital.csv": ALL,
    }),
    "pnl": (("pnl_lib.py", "s1_op_basis.py", "s2_bridge.py", "s3_volume_cir.py", "s4_div_equity.py", "s5_proposal.py",
             "pnl_book.py"), {
        "stage1/ifrs/ifrs_quarterly.csv": by("metric"),
        "stage1/ifrs/ifrs_history.csv": by("metric"),
        "stage1/ifrs/three_profits.csv": ALL,
        "stage1/ifrs/anchor_books.csv": ALL,
        "stage1/mgmt/mgmt_kpi.csv": by("metric"),
        "stage1/mgmt/guidance.csv": ALL,
        "stage1/market/dividends_public.csv": ALL,
        "stage1/regimes/season_sigma.json": ALL,
        "stage1/worlds/world_paths_quarterly.csv": ALL,
        "stage1/calib/pnl/inputs/yandex_dividends.csv": ALL,
        "stage1/calib/pnl/inputs/lead_decisions.yaml": ALL,
        "research/facts/t_quarterly.csv": by("metric"),
        "research/facts/cbr_key_rate_quarterly.csv": ALL,
    }),
    "nii": (("nii_book.py",), {
        "stage1/ifrs/anchor_books.csv": ALL,
        "stage1/worlds/world_paths_quarterly.csv": ALL,
        "stage1/calib/nii/out/nii_book_proposal.yaml": ALL,
        "stage1/calib/nii/out/transmission_out.json": ALL,
        "stage1/calib/nii/out/nim_path.csv": ALL,
        "stage1/calib/nii/out/spread_history.csv": ALL,
        "stage1/calib/nii/out/results.json": ALL,
        "stage1/calib/nii/out/rates_panel.csv": by("basis", "series"),
        "stage1/mgmt/mgmt_kpi.csv": by("metric"),
        "stage1/ifrs/ifrs_history.csv": by("metric"),
        "research/facts/cbr_key_rate_quarterly.csv": ALL,
    }),
    "regimes": (("regimes_book.py",), {
        "stage1/regimes/cor_by_state.csv": ALL,
        "stage1/regimes/kappa.json": ALL,
        "stage1/regimes/season_sigma.json": ALL,
        "stage1/regimes/paths_check.json": ALL,
        "stage1/regimes/proforma_annual.csv": ALL,
        "stage1/regimes/segments.csv": ALL,
        "stage1/worlds/world_paths_quarterly.csv": ALL,
    }),
    "market": (("beta_t.py", "dividends_book.py"), {
        "stage1/market/beta/inputs/prices_T.csv": ALL,
        "stage1/market/beta/inputs/prices_TCSG.csv": ALL,
        "stage1/market/beta/inputs/prices_MCFTR.csv": ALL,
        "stage1/market/beta/inputs/prices_IMOEX.csv": ALL,
        "stage1/market/beta/inputs/prices_MOEXFN.csv": ALL,
        "stage1/market/beta/inputs/prices_SBER.csv": ALL,
        "stage1/market/beta/inputs/sber_dividends_public.csv": ALL,
        "stage1/market/beta/inputs/SOURCES.json": ALL,
        "stage1/market/dividends_public.csv": ALL,
        "stage1/market/dividends_lags.csv": ALL,
        "stage1/market/shares_history.csv": ALL,
        "stage1/worlds/bank_overlay_draft.yaml": ALL,
        "stage1/calib/pnl/op_basis_quarterly.csv": ALL,
    }),
    "governance": (("governance_book.py",), {
        "stage1/calib/governance/out/governance_out.json": ALL,
        "stage1/calib/governance/out/proposal.yaml": ALL,
        "stage1/calib/governance/out/deals_table.csv": ALL,
        "stage1/calib/governance/out/event_study.csv": ALL,
    }),
}

TEXT_SUFFIXES = (".csv", ".yaml", ".yml", ".json", ".md", ".txt")


def literals(paths: list[Path]) -> set[str]:
    """Все строковые литералы кода (включая части f-строк)."""
    out: set[str] = set()
    for p in paths:
        if not p.exists():
            continue
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.add(node.value)
    return out


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# Абсолютные пути машины автора листа и имена локальных папок → относительные пути (публичный репозиторий).
# Имён папок здесь нет — только их вид: папка передачи любой панели кончается на «-handoff» (перед ней могут стоять
# каталоги рабочего места), рабочая копия — каталог прямо перед «data/assumptions/». Путь режется с начала:
# остаётся путь от корня папки передачи или от корня репозитория.
_SEP = r"[\\/]"
_ABS = re.compile(r"[A-Za-z]:" + _SEP + r"[^\s'\",;|)]*?" + _SEP + r"(?=(?:primary|research|stage1|data)" + _SEP + ")")
_NAME = r"[\w.-]+"
_START = r"(?<![\w.\\/-])"                        # начало пути: перед именем нет ни имени, ни разделителя
_LOCAL = (
    re.compile(_START + "(?:" + _NAME + _SEP + ")*" + _NAME + "-handoff" + _SEP),
    re.compile(_START + _NAME + _SEP + "(?=data" + _SEP + "assumptions" + _SEP + ")"),
)


def sanitize(body: bytes, name: str) -> bytes:
    """Убрать префиксы абсолютных путей и имена локальных папок (остаётся путь от корня листов этапа 1)."""
    if not name.endswith(TEXT_SUFFIXES):
        return body
    text = body.decode("utf-8")
    clean = _ABS.sub("", text)
    for local in _LOCAL:
        clean = local.sub("", clean)
    return body if clean == text else clean.encode("utf-8")


def extract_file(src: Path, spec: tuple | None, lits: set[str]) -> tuple[bytes, int, int]:
    """(байты малого входа, строк оставлено, строк всего). Лист без отбора — байт в байт (переводы строк — LF)."""
    raw = src.read_bytes()
    if spec is None:
        body = raw.replace(b"\r\n", b"\n")
        n = body.count(b"\n")
        return body, n, n
    cols, rx = spec
    text = raw.decode("utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8")
    rd = csv.reader(io.StringIO(text, newline=""))
    head = next(rd)
    idx = [head.index(c) for c in cols]
    rows = list(rd)
    keep = [r for r in rows if all(r[i] in lits for i in idx) or (rx is not None and rx.search(r[idx[0]]))]
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(head)
    w.writerows(keep)
    body = buf.getvalue().encode("utf-8")
    if raw.startswith(b"\xef\xbb\xbf"):
        body = b"\xef\xbb\xbf" + body
    return body, len(keep), len(rows)


def extract_area(area: str, handoff: Path) -> dict[str, bytes]:
    """{путь внутри evidence/<область>/inputs: байты} плюс SOURCES.json."""
    scripts, files = AREAS[area]
    lits = literals([HERE / area / s for s in scripts])
    out: dict[str, bytes] = {}
    sources = []
    for rel, spec in files.items():
        src = handoff / rel
        body, kept, total = extract_file(src, spec, lits)
        body = sanitize(body, rel)
        out[rel] = body
        how = "весь лист" if spec is None else f"строки, где {' и '.join(spec[0])} — литерал кода области"
        sources.append({"path": rel, "sha256_full": _sha(src.read_bytes()), "sha256_input": _sha(body),
                        "filter": how, "rows_kept": kept, "rows_total": total})
    out["SOURCES.json"] = (json.dumps({"area": area, "root": "$BANK_HANDOFF_DIR", "files": sources},
                                      ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="малые входы доказательных листов")
    ap.add_argument("areas", nargs="*", help=f"области (по умолчанию все: {', '.join(AREAS)})")
    ap.add_argument("--check", action="store_true", help="сравнить с лежащими входами")
    a = ap.parse_args(argv)
    root = os.environ.get("BANK_HANDOFF_DIR")
    if not root:
        print("нет BANK_HANDOFF_DIR — входы извлекать не из чего")
        return 1
    bad = 0
    for area in a.areas or list(AREAS):
        files = extract_area(area, Path(root))
        base = HERE / area / "inputs"
        stale = [q for q in sorted(base.rglob("*")) if q.is_file() and q.relative_to(base).as_posix() not in files]
        for q in stale:                           # вход, которого опись больше не называет
            if a.check:
                print("ЛИШНИЙ ФАЙЛ:", area, q.relative_to(base).as_posix())
                bad += 1
            else:
                q.unlink()
        for rel, body in files.items():
            dst = base / rel
            if a.check:
                if not dst.exists() or dst.read_bytes() != body:
                    print("РАСХОЖДЕНИЕ:", area, rel)
                    bad += 1
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(body)
        print(area, "—", "сверено" if a.check else "записано", len(files), "файлов")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
