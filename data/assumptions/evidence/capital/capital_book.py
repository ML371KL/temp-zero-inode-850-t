# -*- coding: utf-8 -*-
"""Капитал: числа книги против листа калибровки и фактов якоря (MODEL §4.11–§4.13).

Запускается после capital_calib.py (читает его out/book_keys_capital_proposal.yaml) и повторяет независимо:
  * вычеты якоря формой ядра: Ded20_0 = BVreg + инструменты − капитал группы; Ded11_0 = BVreg − E − базовый капитал;
    BVreg = BV − (1 − f) × фонд FVOCI; нормативы якоря той же формой — 12,93 и 9,40 %;
  * RWA из плотностей книги на остатках якоря против вменённых RWA группы (капитал / Н20.0);
  * долю инструментов капитала в RWA на шести датах формы 0409805 (центр траектории capital.n20.t2);
  * три чтения ряда Н20.0 для запаса менеджмента: над действующим минимумом, над минимумом 2028 года, над
    требованием с глиссадой книги при запасе 0 (по графику и «средняя группа»);
  * полы сценариев книги против таблицы листа;
  * спред субординированного инструмента к оптовому фондированию (instrument_spread.py): надбавка купонов действующих
    бессрочных инструментов к ключевой ставке их валюты минус долгосрочный спред книги оптового фондирования — стоимость
    прироста инструментов сверх якоря, которую лист вывода кладёт в траекторию «прочего».
Ключи, которые решения ведущего изменили против листа (запас и его ось, форма множителя кризиса, траектория
инструментов), сверяются с решением, а не с листом; траектория инструментов и её стоимость выводятся на ядре
(evidence/path) — здесь сверка с записью вывода.
Запуск из корня репозитория: python -B data/assumptions/evidence/capital/capital_book.py → out/capital_book_out.json
(код выхода 1 — расхождение с шаблоном книги).
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import json  # noqa: E402

import cc_common as C  # noqa: E402
import evlib  # noqa: E402
import instrument_spread  # noqa: E402

RECORD = HERE.parent / "path" / "out" / "derive_out.json"     # запись вывода на ядре

FLOORS_2025 = {1: 0.09, 2: 0.09, 3: 0.0925, 4: 0.0925}     # минимум Н20.0 с надбавками в 2025 году: 9,0 % до 01.07.2025,
#                                                            9,25 % после (разложение минимума в отчётности МСФО — график этапа 1)
BUFFER_DATES = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]
SAME_AS_SHEET = (                                           # ключи, которые книга берёт у листа без изменений
    "capital.minimum", "capital.n20.deductions_anchor", "capital.n20.fvoci_recognition", "capital.n20.gap_pp",
    "capital.n11.deductions_anchor", "capital.n11.gap_pp", "capital.n11.audit_cutoffs", "capital.rwa.density",
    "capital.rwa.density_drift_rate", "capital.rwa.density_drift_until", "capital.rwa.fx", "capital.recapitalization",
    "capital.mgmt_buffer", "oci.fvoci_share", "oci.fvoci_duration", "oci.fvoci_maturity",
    "oci.fvoci_tenor", "oci.fvtpl_bond_share", "oci.fvtpl_bond_duration", "joint.reg_prob_given_regime",
)


def floor20(book: dict, s: str, year: int, quarter: int) -> float:
    if year <= 2025:
        return FLOORS_2025[quarter]
    cap = book["capital"]
    sc = cap["reg_scenarios"][s]
    return cap["minimum"]["n20_0"] + sum(evlib.year_value(sc[k], year) for k in ("conservation", "sifi", "ccyb"))


def glide_req(book: dict, s: str, date: str, buffer: float = 0.0) -> float:
    """Требование Н20.0 с глиссадой книги на дату конца квартала."""
    gc = book["capital"]["growth_constraint"]
    H, delta = int(gc["lookahead_quarters"]), float(gc["glide_pp_per_quarter"])
    t = int(date[:4]) * 4 + int(date[5:7]) // 3 - 1
    return max(floor20(book, s, (t + h) // 4, (t + h) % 4 + 1) + buffer - h * delta for h in range(H + 1))


def compute() -> dict:
    book = evlib.template()
    cap = book["capital"]
    sheet = yaml.safe_load((HERE / "out" / "book_keys_capital_proposal.yaml").read_text(encoding="utf-8"))
    cmp = evlib.Compare()
    for path in SAME_AS_SHEET:
        cmp.eq(path, evlib.get(book, path), evlib.get(sheet, path), 1e-9)
    # правило роста: поля листа, кроме навёрстывания — лист предлагал 0,25, книга несёт 0 (решение ведущего № 5, п. 5:
    # без памяти о разрыве доля прироста квартала зависит только от состояния, перенос якоря точен во всех клетках)
    gc_book, gc_sheet = dict(cap["growth_constraint"]), dict(evlib.get(sheet, "capital.growth_constraint"))
    cmp.eq("capital.growth_constraint.catch_up_rate (решение ведущего № 5)", gc_book.pop("catch_up_rate"), 0.0, 1e-12)
    gc_sheet.pop("catch_up_rate")
    cmp.eq("capital.growth_constraint (без навёрстывания)", gc_book, gc_sheet, 1e-9)
    # полы сценариев: книга (форма договора ключей) против листа (явные ключи лет)
    for s in cap["reg_scenarios"]["ids"]:
        for y in range(2026, 2032):
            for k in ("conservation", "sifi", "ccyb"):
                cmp.eq(f"capital.reg_scenarios.{s}.{k} {y}", evlib.year_value(cap["reg_scenarios"][s][k], y),
                       evlib.year_value(sheet["capital"]["reg_scenarios"][s][k], y), 1e-9)
            cmp.eq(f"capital.reg_scenarios.{s}.deduction_pp {y}",
                   evlib.year_value(cap["reg_scenarios"][s]["deduction_pp"]["n20_0"], y),
                   evlib.year_value(sheet["capital"]["reg_scenarios"][s]["deduction_pp"]["n20_0"], y), 1e-9)
    # якорь формой ядра
    f = cap["n20"]["fvoci_recognition"]
    bvreg = C.BV[C.ANCH] - (1 - f) * C.RFV[C.ANCH]
    t2_anchor = C.AT1[C.ANCH]
    ded20 = bvreg + t2_anchor - C.KTOT[C.ANCH]
    ded11 = bvreg - C.EOP[C.ANCH] - C.CET1[C.ANCH]
    rwa0 = C.RWA0[C.ANCH]
    n20 = (bvreg - cap["n20"]["deductions_anchor"] + t2_anchor) / rwa0 + cap["n20"]["gap_pp"]
    n11 = (bvreg - C.EOP[C.ANCH] - cap["n11"]["deductions_anchor"]) / rwa0 + cap["n11"]["gap_pp"]
    cmp.eq("capital.n20.deductions_anchor (пересчёт)", cap["n20"]["deductions_anchor"], round(ded20, 3), 5e-4)
    cmp.eq("capital.n11.deductions_anchor (пересчёт)", cap["n11"]["deductions_anchor"], round(ded11, 3), 5e-4)
    cmp.eq("Н20.0 якоря формой ядра", round(n20, 4), C.N200[C.ANCH] / 100, 5e-5)
    cmp.eq("Н20.1 якоря формой ядра", round(n11, 4), C.N201[C.ANCH] / 100, 5e-5)
    # RWA из плотностей книги
    ab = {r["book"]: float(r["bal_2026-06-30"]) for r in C.rows("stage1/ifrs/anchor_books.csv") if r.get("bal_2026-06-30")
          and C.isnum(r["bal_2026-06-30"])}
    dens = cap["rwa"]["density"]
    books = [b for b in dens if b in ab]
    loans = sum(ab[b] for b in books if b not in ("securities", "liquidity"))
    total_assets, allowance, fixed = 6272.1, 353.4, 205.5      # МСФО 6М2026, с. 6; прим. 17; пакет Яндекса и ассоциированные
    other = total_assets - (loans - allowance) - ab["securities"] - ab["liquidity"]
    rwa_model = sum(dens[b] * ab[b] for b in books) + dens["other_assets"] * (other - fixed) + dens["other_assets_fixed"] * fixed
    cmp.eq("RWA из плотностей книги против вменённых RWA группы", round(rwa_model, 1), round(rwa0, 1), 0.5)
    # инструменты капитала: уровень якоря и доля в RWA
    t2 = cap["n20"]["t2"]
    share = {d: C.AT1[d] / C.RWA0[d] for d in BUFFER_DATES}
    keys = [k for k in t2 if k not in ("LT", "LT_from")]
    vals = [float(t2[k]) for k in keys]
    cmp.true("capital.n20.t2: траектория не убывает и начинается не ниже уровня якоря",
             all(b >= a for a, b in zip(vals, vals[1:])) and vals[0] >= t2_anchor - 5e-4)
    cmp.true("capital.n20.t2: ключ квартала якоря равен факту",
             keys[0] == book["meta"]["anchor_period"] and abs(vals[0] - t2_anchor) <= 5e-4)
    cmp.true("capital.n20.t2: доля якоря 2,2–2,5 % RWA", 0.022 <= share[C.ANCH] <= 0.025)
    # стоимость прироста инструментов: спред к оптовому фондированию и запись вывода на ядре
    spread = instrument_spread.spread_to_wholesale(evlib.get(book, "nii.books.wholesale.spread.LT"))
    rec = json.loads(RECORD.read_text(encoding="utf-8"))
    cmp.eq("capital.n20.t2 = запись вывода", t2, rec["keys"]["capital.n20.t2"])
    cmp.eq("спред инструмента к оптовому фондированию = спред записи вывода", spread["to_wholesale"],
           rec["cost"]["spread"]["to_wholesale"], 1e-12)
    external = instrument_spread.external_share(book["meta"]["facts_date"])
    cmp.eq("внешняя доля инструментов на якоре = доля записи вывода", external["share"], rec["cost"]["external"]["share"], 1e-12)
    cmp.eq("бессрочные займы МСФО листа моста = факт якоря", external["external"],
           json.loads((HERE.parents[2] / "facts" / "capital.json").read_text(encoding="utf-8"))["instruments_total"]["v"]
           if (HERE.parents[2] / "facts" / "capital.json").exists() else external["external"], 1e-9)
    cmp.eq("спред на прирост = спред к оптовому фондированию × внешняя доля", rec["cost"]["spread_on_increment"],
           round(spread["to_wholesale"] * external["share"], 6), 1e-9)
    costs = list(rec["cost"]["cost_nominal"].values())
    cmp.true("стоимость прироста инструментов растёт вместе с приростом", all(b >= a for a, b in zip(costs, costs[1:])))
    # множитель кризиса: форма договора ключей
    mult = book["regimes"]["crisis"]["rwa_density_mult"]
    shock = int(book["meta"]["anchor_period"][:4]) + book["regimes"]["crisis"]["shock_year_offset"]
    cmp.eq("regimes.crisis.rwa_density_mult: год шока", mult[str(shock)], sheet["regimes"]["crisis"]["rwa_density_mult"][str(shock)])
    cmp.true("regimes.crisis.rwa_density_mult: ключ года якоря равен 1", mult.get(book["meta"]["anchor_period"][:4]) == 1.0)
    # три чтения ряда Н20.0
    readings = {}
    for d in BUFFER_DATES:
        n = C.N200[d] / 100
        floor_now = floor20(book, "schedule", int(d[:4]), int(d[5:7]) // 3)
        readings[d] = {
            "n20_0": round(n, 4),
            "over_current_minimum": round(n - floor_now, 4),
            "over_minimum_2028": round(n - floor20(book, "schedule", 2028, 1), 4),
            "over_glide_requirement": {s: round(n - glide_req(book, s, d), 4) for s in ("schedule", "mid")},
        }
    low3 = min(min(r["over_glide_requirement"].values()) for r in readings.values())
    buf = cap["mgmt_buffer"]["n20_0"]
    cmp.true("запас книги не выше третьего чтения ряда (над требованием с глиссадой)", buf <= low3 + 1e-9)
    axis = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["paths"][0] == "capital.mgmt_buffer.n20_0")
    max_at_anchor = {s: round(C.N200[C.ANCH] / 100 - glide_req(book, s, "2026-09-30"), 4) for s in ("schedule", "mid")}
    return {
        "anchor": {"bv": C.BV[C.ANCH], "fvoci_reserve": C.RFV[C.ANCH], "bvreg": round(bvreg, 3),
                   "e_unaudited": round(C.EOP[C.ANCH], 3), "group_capital": C.KTOT[C.ANCH], "cet1": C.CET1[C.ANCH],
                   "instruments": t2_anchor, "tier2": C.T2[C.ANCH], "rwa_implied": round(rwa0, 1),
                   "ded20": round(ded20, 3), "ded11": round(ded11, 3), "n20_model": round(n20, 5), "n11_model": round(n11, 5),
                   "ded20_share_of_rwa": round(ded20 / rwa0, 4)},
        "rwa_from_densities": {"model": round(rwa_model, 1), "implied": round(rwa0, 1), "other_assets": round(other, 1),
                               "other_assets_growing": round(other - fixed, 1)},
        "instruments_to_rwa": {d: round(v, 4) for d, v in share.items()},
        "t2_trajectory": {"first_key": keys[0], "first": vals[0], "last": vals[-1], "derived_on_engine": True},
        "instrument_spread": {**spread, "external_share": external, "spread_on_increment": rec["cost"]["spread_on_increment"],
                              "cost_nominal_by_year": rec["cost"]["cost_nominal"],
                              "increment_year_end": rec["cost"]["increment_year_end"]},
        "buffer_readings": readings,
        "buffer": {"book": buf, "axis": [axis["low"], axis["high"]], "third_reading_min": round(low3, 4),
                   "max_without_breach_2026Q3": max_at_anchor},
        "book_mismatches": cmp.mismatches,
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    res = compute()
    evlib.write_json(HERE / "out" / "capital_book_out.json", res)
    a = res["anchor"]
    print(f"якорь: Ded20_0 {a['ded20']}, Ded11_0 {a['ded11']}; Н20.0 {100 * a['n20_model']:.3f} %, Н20.1 {100 * a['n11_model']:.3f} %")
    print("RWA из плотностей:", res["rwa_from_densities"])
    print("инструменты к RWA:", res["instruments_to_rwa"])
    sp = res["instrument_spread"]
    print(f"спред инструмента к оптовому фондированию: {100 * sp['to_wholesale']:.2f} п.п. = надбавка к ключевой "
          f"{100 * sp['margin_to_key']:.2f} п.п. − спред оптового фондирования {100 * sp['wholesale_lt_spread']:+.2f} п.п.")
    for d, r in res["buffer_readings"].items():
        print(d, "Н20.0", r["n20_0"], "чтения:", r["over_current_minimum"], r["over_minimum_2028"], r["over_glide_requirement"])
    print("запас:", res["buffer"])
    print("расхождения с шаблоном:", res["book_mismatches"] or "нет")
    return 1 if res["book_mismatches"] else 0


if __name__ == "__main__":
    sys.exit(main())
