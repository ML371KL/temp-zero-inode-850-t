# -*- coding: utf-8 -*-
"""Отчёт о прибыли: числа книги против листа калибровки и операционного базиса фактов (MODEL §4.6–§4.8, §5.7).

Запускается после run_all.py (читает его out/): предложение ключей, операционный базис кварталов, мосты упр. ↔ движок,
доли выплаты. Повторяет независимо по таблице операционного базиса (out/op_basis_quarterly.csv):
  * прибыль движка квартала якоря = операционной прибыли эмитента (52,06 млрд ₽); суммы 2025 года и 1-го полугодия 2026;
  * возврат процентов по долгу под пакет Яндекса = поправка эмитента «проценты по займам» / (1 − 0,25) и не больше всех
    процентов нефинансовых компаний (обязательный тест решения ведущего № 3, п. 8);
  * долю неконтролирующих акционеров и эффективную ставку налога на операционном базисе;
  * «прочее» — медиана квартала × 4; ключ 2026 года строки пакета;
  * долю выплаты к средней операционной прибыли четырёх кварталов (центр политики 0,26) и потолок выплат года.
Ключи, которые решения ведущего изменили против листа (доля выплаты и её ось; связи расходов и услуг с портфелем — по
свидетельствам трёх кварталов с чистой базой; корни расходов, спред услуг и «прочее» со стоимостью инструментов
капитала — выводятся на ядре; коридоры гейтов без автора), сверяются с решением и с записью вывода
(evidence/path/out/derive_out.json), а не с листом.
Запуск из корня репозитория: python -B data/assumptions/evidence/pnl/pnl_book.py → out/pnl_book_out.json
(код выхода 1 — расхождение с шаблоном книги).
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
sys.path.insert(0, str(HERE.parent))
import evlib  # noqa: E402

SAME_AS_SHEET = (
    "fees.growth_override", "volumes.link_base",
    "other.insurance_volume_link", "other.insurance_growth_vs_wages", "other.misc_quarter_shares",
    "other.fvtpl_bond_reval", "noncore.result_real", "noncore.price_base_year", "pnl.nci_share", "tax.statutory",
    "tax.effective_gap", "tax.one_off", "equity.other_movements", "dividends.policy.base_window_quarters",
    "checks.cir_range", "checks.bridge_drift_pp", "checks.roe_range", "checks.cor_range",
)
TAX = 0.25                                                    # ставка налога в выводе возврата процентов до налога
LINKS = {"opex.volume_link": 0.5, "fees.volume_link": 0.6}    # центры связей: середины диапазонов трёх кварталов с чистой базой
LINK_AXIS = {"low": {"opex.volume_link": 0.3, "fees.volume_link": 0.4}, "high": {"opex.volume_link": 0.7, "fees.volume_link": 0.8}}
WAGES = (0.08, 0.13)                                          # рост зарплат в окне трёх кварталов: 8–13 %
RECORD = HERE.parent / "path" / "out" / "derive_out.json"     # запись вывода на ядре
NONFIN_INTEREST = {"2Q2025": 3.4, "3Q2025": 4.9, "4Q2025": 5.9, "1Q2026": 6.5, "2Q2026": 6.9}   # все проценты по долгу
#   нефинансовых компаний группы, млрд ₽ за квартал (ряды эмитента, отчёт о прибыли, строка 83)


def compute() -> dict:
    book = evlib.template()
    sheet = yaml.safe_load((OUT / "book_keys_pnl_proposal.yaml").read_text(encoding="utf-8"))
    cmp = evlib.Compare()
    for path in SAME_AS_SHEET:
        cmp.eq(path, evlib.get(book, path), sheet[path], 1e-9)
    rows = {r["period"]: {k: (float(v) if v not in ("", None) and k != "period" else v) for k, v in r.items()}
            for r in evlib.read_csv(OUT / "op_basis_quarterly.csv")}
    anchor = rows["2Q2026"]
    y2025 = sum(rows[f"{q}Q2025"]["ni_shareholders"] for q in (1, 2, 3, 4))
    h1 = [rows["1Q2026"], rows["2Q2026"]]
    h1_sum = sum(r["ni_shareholders"] for r in h1)
    cmp.eq("прибыль движка квартала якоря = операционной прибыли эмитента", round(anchor["ni_shareholders"], 3),
           round(anchor["issuer_op_np"], 3), 5e-4)
    cmp.true("тождество «отчётная акционерам = операционная + блок инвестиции» во всех кварталах",
             all(abs(r["id_reported_eq_op_plus_block"]) < 5e-4 for r in rows.values()))
    interest = {}
    for p, total in NONFIN_INTEREST.items():
        back = -rows[p]["issuer_adj_interest_sh"] / (1 - TAX)
        interest[p] = {"returned_pretax": round(back, 3), "nonfin_interest_total": total}
        cmp.eq(f"возврат процентов {p} = строка пакета движка", round(rows[p]["noncore_net"], 3), round(back, 3), 2e-3)
        cmp.true(f"возврат процентов {p} не больше всех процентов нефинансовых компаний", back <= total + 1e-9)
    nci_h1 = sum(r["nci"] for r in h1) / sum(r["ni"] for r in h1)
    last4 = [rows[p] for p in ("3Q2025", "4Q2025", "1Q2026", "2Q2026")]
    nci_l4 = sum(r["nci"] for r in last4) / sum(r["ni"] for r in last4)
    cmp.eq("pnl.nci_share = доля 1-го полугодия 2026 года", book["pnl"]["nci_share"], round(nci_h1, 3), 5e-4)
    six = [rows[p] for p in ("1Q2025", "2Q2025", "3Q2025", "4Q2025", "1Q2026", "2Q2026")]
    etr6 = -sum(r["tax"] for r in six) / sum(r["pbt"] for r in six)
    cmp.eq("tax.effective_gap = эффективная ставка шести кварталов − 25 %", book["tax"]["effective_gap"],
           round(etr6 - TAX, 3), 5e-4)
    mtn = json.loads((OUT / "misc_tax_nci.json").read_text(encoding="utf-8"))
    rec = json.loads(RECORD.read_text(encoding="utf-8"))
    # связи с объёмом: центры — внутри диапазона трёх кварталов с чистой базой при росте зарплат 8–13 %
    rh = [r for r in evlib.read_csv(OUT / "link_history_recent.csv") if r["clean"] == "True"]
    mean = lambda k: statistics.mean(float(r[k]) for r in rh)  # noqa: E731
    implied = {name: sorted((mean(g) - w) / (mean("v_loans") - w) for w in WAGES)
               for name, g in (("opex.volume_link", "g_opex"), ("fees.volume_link", "g_fees"))}
    for path, centre in LINKS.items():
        cmp.eq(f"{path} — центр решения", evlib.get(book, path), centre, 1e-12)
        cmp.true(f"{path}: центр внутри диапазона трёх кварталов с чистой базой", implied[path][0] - 0.01 <= centre <= implied[path][1] + 0.01)
    bundle = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["kind"] == "bundle" and a["paths"][0] == "opex.volume_link")
    cmp.eq("ось-связка гибкости: концы — запись вывода", {e: bundle[e] for e in ("low", "high")},
           {e: rec["ends"]["bundle"][e] for e in ("low", "high")})
    cmp.true("ось-связка гибкости: связи на концах — 0,3 / 0,4 и 0,7 / 0,8",
             all(bundle[e][p] == v for e, d in LINK_AXIS.items() for p, v in d.items()))
    # «прочее»: уровень — медиана квартала × 4; из него по годам вычтена стоимость прироста инструментов капитала
    misc = book["other"]["misc_net_real"]
    years = sorted(k for k in misc if k != "LT")
    cmp.eq("уровень «прочего» записи вывода = медиана квартала × 4", rec["cost"]["level"], round(mtn["median_q"] * 4), 0.5)
    cmp.eq("other.misc_net_real = запись вывода", misc, rec["keys"]["other.misc_net_real"])
    cmp.true("other.misc_net_real: уровень минус растущая стоимость инструментов",
             all(a >= b for a, b in zip([rec["cost"]["level"]] + [misc[k] for k in years], [misc[k] for k in years])))
    cmp.eq("fees.growth_vs_wages = запись вывода", book["fees"]["growth_vs_wages"], rec["keys"]["fees.growth_vs_wages"])
    fg = rec["fees"]
    cmp.true("спред услуг: рост услуг кварталов года якоря идёт от факта (+15…+18 % г/г)",
             all(0.15 <= v <= 0.18 for v in fg["growth_by_quarter"].values()))
    nc = json.loads((OUT / "noncore_center.json").read_text(encoding="utf-8"))
    cmp.eq("noncore.result_real = траектория «долг под пакет постоянен в рублях»", book["noncore"]["result_real"], nc["traj_A"])
    axis = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["paths"][0].startswith("noncore.result_real"))
    cmp.eq("ось пакета Яндекса", [axis["low"], axis["high"]], [-nc["axis_shift_pretax"], nc["axis_shift_pretax"]])
    # доля выплаты
    div = evlib.read_csv(OUT / "dividend_payout.csv")
    shares = [float(r["payout_to_avg4"]) for r in div[1:]]          # шесть решений после покупки Росбанка
    payout = book["dividends"]["policy"]["payout"]["LT"]
    cmp.eq("dividends.policy.payout = среднее шести решений к базе четырёх кварталов", payout, round(statistics.mean(shares), 2), 1e-9)
    dax = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["paths"] == ["dividends.payout_deviation"])
    cmp.true("ось отклонения выплаты: доля 0,21–0,30 накрывает факт шести решений",
             payout + dax["low"] <= min(shares) and max(shares) <= payout + dax["high"] + 1e-9
             and abs(payout + dax["high"] - book["dividends"]["policy"]["cap"]) < 1e-9)
    # корни расходов: год выхода на LT — лист; четыре корня (год якоря, 2027–2030, 2031–2032, LT) выведены на ядре под
    # C/I модальной клетки с ограничением роста (лист path/derive_on_engine.py) — при связи книги; лист считал при связи 0,7
    og, og_sheet = book["opex"]["real_growth"], sheet["opex.real_growth"]
    cmp.eq("opex.real_growth.LT_from", og["LT_from"], og_sheet["LT_from"])
    cmp.eq("opex.real_growth = запись вывода", og, rec["keys"]["opex.real_growth"])
    mid = [og[str(y)] for y in (2027, 2028, 2029, 2030)]
    cmp.true("opex.real_growth: по одному корню на 2027–2030 и на 2031–2032", len(set(mid)) == 1 and og["2031"] == og["2032"])
    cmp.true("запись вывода: C/I того, что судит гейт, на целях (полугодие года якоря и годы гейта)",
             abs(rec["frozen_check"]["cir_anchor_half"] - rec["opex"]["goal_anchor_half"]) <= 5e-4
             and abs(rec["frozen_check"]["cir_lt_value"] - book["checks"]["cir_lt"]["target"]) <= 5e-4)
    cmp.eq("цель C/I — в ожидании слоя «рыночные ставки как есть»: корни выведены под то, что судит гейт",
           rec["opex"]["scope"], book["checks"]["cir_lt"].get("scope", "modal_cell"))
    oax = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["kind"] == "shift" and a["paths"][0].startswith("opex.real_growth"))
    cmp.eq("ось уровня расходов = запись вывода", [oax["low"], oax["high"]], [rec["ends"]["opex_axis"]["low"], rec["ends"]["opex_axis"]["high"]])
    # мосты
    bv = json.loads((OUT / "bridge_values.json").read_text(encoding="utf-8"))
    gates = book["checks"]["bridge_drift_pp"]
    cmp.true("коридор дрейфа моста: не уже 2,5σ моста", gates["cor"] >= bv["thr_cor"] - 1e-4 and gates["nim"] >= bv["thr_nim"] - 1e-4)
    cmp.eq("цель C/I: гейт долгосрочного C/I", book["checks"]["cir_lt"]["target"], 0.47)
    return {
        "anchor_quarter": {"ni_shareholders": round(anchor["ni_shareholders"], 3), "issuer_op_np": round(anchor["issuer_op_np"], 3),
                           "noncore_net": round(anchor["noncore_net"], 4), "tax": round(anchor["tax"], 4), "nci": round(anchor["nci"], 4)},
        "sums": {"op_np_2025": round(y2025, 3), "op_np_1h2026": round(h1_sum, 3)},
        "interest_returned": interest,
        "nci_share": {"h1_2026": round(nci_h1, 4), "last4": round(nci_l4, 4), "book": book["pnl"]["nci_share"]},
        "tax": {"etr_6q": round(etr6, 4), "gap_book": book["tax"]["effective_gap"]},
        "links": {"book": {p: evlib.get(book, p) for p in LINKS},
                  "implied_three_clean_quarters": {p: [round(v, 2) for v in r] for p, r in implied.items()}, "axis_ends": LINK_AXIS},
        "misc": {"median_q": round(mtn["median_q"], 3), "level": rec["cost"]["level"], "book_first_year": misc[years[0]],
                 "book_lt": misc["LT"], "instrument_cost_nominal": rec["cost"]["cost_nominal"],
                 "h1_2026_annualised": round(mtn["h1_2026"] * 2, 1)},
        "fees_spread": {"book": book["fees"]["growth_vs_wages"], "goal": fg["goal"], "growth_by_quarter": fg["growth_by_quarter"],
                        "without_spread": fg["without_spread"]},
        "payout": {"to_avg4": [round(s, 4) for s in shares], "mean": round(statistics.mean(shares), 4), "book": payout},
        "opex_roots": {"sheet_anchor_year": og_sheet["2026"], "book_anchor_year": og["2026"],
                       "sheet_2027_2030": og_sheet["2027"], "book_2027_2030": mid[0],
                       "sheet_2031_2032": og_sheet["2031"], "book_2031_2032": og["2031"],
                       "sheet_lt": og_sheet["LT"], "book_lt": og["LT"], "sheet_link": 0.7, "book_link": book["opex"]["volume_link"],
                       "derived_on_engine": True},
        "bridges": {"cor": round(bv["cor"], 6), "nim_anchor_composition": round(bv["nim_anchor"], 6),
                    "nim_window_mean": round(bv["nim_b9"], 6), "cir": round(bv["cir"], 6),
                    "thresholds_2_5_sigma": {"cor": bv["thr_cor"], "nim": bv["thr_nim"]}, "book_gates": gates},
        "book_mismatches": cmp.mismatches,
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    res = compute()
    evlib.write_json(OUT / "pnl_book_out.json", res)
    for k in ("anchor_quarter", "sums", "nci_share", "tax", "links", "misc", "fees_spread", "payout", "opex_roots", "bridges"):
        print(k, res[k])
    print("расхождения с шаблоном:", res["book_mismatches"] or "нет")
    return 1 if res["book_mismatches"] else 0


if __name__ == "__main__":
    sys.exit(main())
