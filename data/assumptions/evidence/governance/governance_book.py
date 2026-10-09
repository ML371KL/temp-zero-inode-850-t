# -*- coding: utf-8 -*-
"""Дисконт за управление: каналы книги против листа каналов этапа 1 (MODEL §8.2).

Лист каналов этапа 1 (пять каналов снизу вверх: сделки с крупнейшим акционером, программа мотивации, депозитарный блок,
ликвидность и листинг, холдинговый слой) читает десятки строк отчётности, ряды цен и снимки биржи; в репозиторий он
целиком не переносится: его выходы лежат малыми входами (inputs/stage1/calib/governance/out, sha256 — inputs/SOURCES.json).
Этот лист сверяет шаблон книги с выходами и повторяет арифметику ключа:
  * набор каналов, их имена, тексты оснований и значения — как в предложении листа; discount = Σ sign × value;
  * рублёвый канал переводится в долю V0 неподвижной точкой g = PV / (PV + M × N_div / 1000 − D): при PV = 0 доля равна
    нулю при любой медиане M, поэтому ключ от медианы выпуска не зависит (проверка ядра и витрины на нулевом центре оси);
  * верх диапазона первого канала (сделка раз в три года с передачей 12 млрд ₽) — внутри оси полосы 0–10 %;
  * запись сделок с акционером 2024–2026 годов в трёх линзах (учёт МСФО, прибыль на акцию, отклик цены в дни сделок):
    отклик цены суммарно положительный — передачи стоимости от миноритариев запись не показывает.
Сделка с «Точкой» (объявлена 01.10.2026) в дисконт не входит: до закрытия она вне книги — событие календаря и плашка
выпуска с числом (около −0,85 % прибыли на акцию до синергий).
Запуск из корня репозитория: python -B data/assumptions/evidence/governance/governance_book.py → out/governance_out.json
(код выхода 1 — расхождение с шаблоном книги).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
IN = HERE / "inputs" / "stage1" / "calib" / "governance" / "out"
OUT = HERE / "out"
sys.path.insert(0, str(HERE.parent))
import evlib  # noqa: E402

STEP = 0.0005                                             # шаг ключа канала: 0,05 п.п.


def fixed_point(pv_bn: float, median_rub: float, divisor_mln: float, declared_bn: float) -> float:
    """Доля V0 печатаемой медианы, которую съедает поток с приведённой стоимостью pv_bn."""
    return pv_bn / (pv_bn + median_rub * divisor_mln / 1000 - declared_bn)


def compute() -> dict:
    book = evlib.template()
    gov = book["valuation"]["governance"]
    sheet = json.loads((IN / "governance_out.json").read_text(encoding="utf-8"))
    proposal = yaml.safe_load((IN / "proposal.yaml").read_text(encoding="utf-8"))["valuation"]["governance"]
    cmp = evlib.Compare()
    cmp.eq("valuation.governance.discount", gov["discount"], proposal["discount"], 1e-12)
    cmp.eq("valuation.governance.components", gov["components"], proposal["components"])
    cmp.eq("discount = Σ sign × value", gov["discount"], sum(c["sign"] * c["value"] for c in gov["components"]), 1e-12)
    cmp.eq("набор каналов", [c["id"] for c in gov["components"]], list(sheet["channels"]))
    cmp.true("лист этапа 1 сошёлся со своими документами и предложением", not sheet["doc_mismatches"] and not sheet["book_mismatches"])
    base = sheet["base"]
    channels = {}
    for c in gov["components"]:
        ch = sheet["channels"][c["id"]]
        pv = float(ch.get("pv_bn") or 0.0)
        points = {m: fixed_point(pv, m, base["n_div_mln"], base["declared_dividend_bn"]) for m in (250.0, 350.0, 450.0)}
        key = round(points[350.0] / STEP) * STEP
        channels[c["id"]] = {"value_book": c["value"], "value_sheet": ch["value"], "pv_bn": pv, "range": ch.get("range"),
                             "share_of_v0_by_median": {str(int(m)): round(v, 6) for m, v in points.items()}, "key": key}
        cmp.eq(f"канал {c['id']}: значение", c["value"], ch["value"], 1e-12)
        cmp.eq(f"канал {c['id']}: ключ = неподвижная точка к шагу 0,05 п.п.", c["value"], key, 1e-12)
        cmp.true(f"канал {c['id']}: ключ не зависит от медианы", max(points.values()) - min(points.values()) < STEP / 2)
    axis = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["paths"] == ["valuation.governance.discount"])
    cmp.eq("ось дисконта", [axis["low"], axis["high"]], [sheet["axis"]["low"], sheet["axis"]["high"]], 1e-12)
    high = sheet["channels"]["related_party_deals"]["range"][1]
    cmp.true("верх диапазона первого канала внутри оси", axis["low"] <= high <= axis["high"])
    rev = next(a for a in book["valuation"]["reverse_dcf"]["axes"] if a["paths"] == ["valuation.governance.discount"])
    cmp.eq("строка обратного расчёта: диапазон = ось", rev["range"], [axis["low"], axis["high"]])
    cmp.eq("мост не несёт дисконта", book["bridge"]["governance_applies"], False)
    record = sheet["channels"]["related_party_deals"]["net_transfer_record"]
    cmp.true("запись сделок 2024–2026 годов: рынок встретил их ростом цены", record["market_lens_car01_bn"] > 0)
    return {
        "total": gov["discount"],
        "channels": channels,
        "base": {k: base[k] for k in ("n_div_mln", "n_out_mln", "treasury_mln", "declared_dividend_bn", "price_rub", "price_date")},
        "axis": {"low": axis["low"], "high": axis["high"], "mean_of_draw_at_center": sheet["axis"]["mean_of_draw_at_center"]},
        "deals_record_bn": record,
        "book_mismatches": cmp.mismatches,
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    res = compute()
    evlib.write_json(OUT / "governance_out.json", res)
    for cid, ch in res["channels"].items():
        print(f"{cid:22s} книга {ch['value_book']}, лист {ch['value_sheet']}, PV {ch['pv_bn']} млрд ₽, диапазон {ch['range']}")
    print("итого:", res["total"], "ось:", res["axis"], "запись сделок, млрд ₽:", res["deals_record_bn"])
    print("расхождения с шаблоном:", res["book_mismatches"] or "нет")
    return 1 if res["book_mismatches"] else 0


if __name__ == "__main__":
    sys.exit(main())
