"""Факты: тождества и сверки сумм (data/facts/SCHEMA.md §5; договор ключей, раздел 2).

Баланс якоря по книгам; проценты книг = ЧПД; строки ОПУ движка на операционном базисе; три прибыли;
нормативы формой ядра; акции; мосты упр. ↔ движок и РСБУ → МСФО; гайденс; календарь; аналоги.
Числа якоря 30.06.2026 названы там, где их называют решения проекта (прибыль движка 52,055; нормативы
12,93 и 9,40 %); остальное проверяется тождествами и не зависит от квартала.
"""

from __future__ import annotations

import datetime as dt
import json
import statistics
from pathlib import Path

import pytest

from tests.test_facts_schema import ASSET_BOOKS, BOOKS, LIABILITY_BOOKS, LOAN_BOOKS, anchor_period, has_text, year_quarters

pytestmark = pytest.mark.tact          # быстрые (≈1 с): тождества фактов идут в такте сервера

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "data" / "facts"
T_ANCHOR = "2026Q2"                    # якорь первой книги: числа решений проекта проверяются только на нём


def load(name: str) -> dict:
    return json.loads((FACTS / f"{name}.json").read_text(encoding="utf-8"))


def v(node) -> float:
    assert isinstance(node, dict) and node.get("v") is not None, node
    return float(node["v"])


def q_end(p: str) -> dt.date:
    y, k = int(p[:4]), int(p[-1])
    return dt.date(y, 3 * k, 31 if k in (1, 4) else 30)


def q_prev(p: str) -> str:
    y, k = int(p[:4]), int(p[-1])
    return f"{y - 1}Q4" if k == 1 else f"{y}Q{k - 1}"


def q_days(p: str) -> int:
    return (q_end(p) - q_end(q_prev(p))).days


def on_first_anchor() -> bool:
    return anchor_period() == T_ANCHOR


# ------------------------------------------------------------------ баланс

def test_balance_identity_by_books():
    b = load("balance")
    books = {k: v(n) for k, n in b["books"].items()}
    assets = sum(books[x] for x in ASSET_BOOKS) - v(b["allowance_ac"]) + v(b["other_assets"])
    assert abs(assets - v(b["total_assets"])) < 1e-6, "Σ книг активов − резерв + прочие активы ≠ активы"
    claims = (sum(books[x] for x in LIABILITY_BOOKS) + v(b["other_liabilities"]) + v(b["dividends_payable"])
              + v(b["equity"]["total"]))
    assert abs(claims - v(b["total_assets"])) < 0.15, "Σ книг пассивов + прочие обязательства + дивиденды + капитал ≠ активы"
    assert abs(v(b["total_liabilities"]) + v(b["equity"]["total"]) - v(b["total_assets"])) < 0.15
    if on_first_anchor():
        assert v(b["total_assets"]) == 6272.1 and abs(sum(books[x] for x in LOAN_BOOKS) - 3813.1) < 1e-6
        assert abs(v(b["other_assets"]) - 993.1) < 1e-6 and abs(v(b["other_liabilities"]) - 428.1) < 1e-6


def test_other_assets_parts_and_the_fixed_part():
    b = load("balance")
    parts = sum(v(n) for n in b["other_assets_parts"].values())
    assert abs(parts - v(b["other_assets"])) <= 0.35, "строки прочих активов не дают остаток баланса"
    fixed = b["other_assets_fixed_parts"]
    assert set(fixed) == {"yandex_stake", "associates"}
    assert abs(sum(v(n) for n in fixed.values()) - v(b["other_assets_fixed"])) < 1e-9
    assert 0 <= v(b["other_assets_fixed"]) <= v(b["other_assets"])
    assert v(fixed["yandex_stake"]) == v(b["securities"]["yandex_stake"])
    liab = sum(v(n) for n in b["other_liabilities_parts"].values())
    assert abs(liab - v(b["other_liabilities"]) - v(b["dividends_payable"])) <= 0.35
    assert v(b["other_liabilities_parts"]["retail_brokerage"]) == v(b["funds"]["retail_brokerage"])


def test_books_equal_their_reference_nodes():
    b = load("balance")
    books = {k: v(n) for k, n in b["books"].items()}
    sec, liq, funds, wh = b["securities"], b["liquidity"], b["funds"], b["wholesale"]
    assert abs(sum(v(sec[k]) for k in ("fvoci_debt", "fvoci_repo", "ac", "ac_repo", "fvtpl_bonds")) - books["securities"]) < 1e-6
    assert abs(sum(v(liq[k]) for k in ("cash", "mandatory_reserves", "due_from_banks")) - books["liquidity"]) < 1e-6
    assert liq["reverse_repo"]["v"] is None and "внутри" in liq["reverse_repo"]["calc"]
    assert v(funds["retail_current"]) == books["retail_current"] and v(funds["retail_term"]) == books["retail_term"]
    assert abs(v(funds["corp_business"]) + v(funds["sme"]) - books["corp_funds"]) < 1e-6
    assert abs(sum(v(wh[k]) for k in ("banks", "other_borrowed", "nonfin_debt", "perpetual_sub")) - books["wholesale"]) < 1e-6
    assert v(b["loans_fvtpl"]) + v(b["lease_gross"]) < books["corp_loans"]
    assert abs(v(b["iea"]) - sum(books[x] for x in ASSET_BOOKS)) < 1e-6


def test_equity_components():
    e = load("balance")["equity"]
    parts = ("share_capital", "share_premium", "treasury_cost", "sbp_reserve", "retained_earnings", "fvoci_reserve", "other_reserves")
    assert abs(sum(v(e[k]) for k in parts) - v(e["bv_common"])) <= 0.25
    assert abs(v(e["bv_common"]) + v(e["nci"]) - v(e["total"])) <= 0.15
    assert v(e["at1"]) == 0.0 and "обязательство" in e["at1"]["calc"]
    assert v(e["treasury_cost"]) < 0
    assert v(e["fvoci_reserve"]) == v(load("capital")["fvoci_reserve"])


def test_dividends_payable_is_a_movement_and_declared_part_fits():
    b = load("balance")
    n = b["dividends_payable"]
    assert v(n) >= 0 and has_text(n.get("calc")) and has_text(n.get("src"))
    declared = b["dividends_payable_declared"]
    assert isinstance(declared, list)
    assert sum(v(x["amount"]) for x in declared) <= v(n) + 1e-9
    periods = [x["period"] for x in declared]
    assert len(periods) == len(set(periods)) and all(p <= anchor_period() for p in periods)
    if on_first_anchor():
        assert v(n) == 4.8 and declared == [], "остаток 4,8 — расчёт по движению; объявленных и не выплаченных нет"
        assert "14,771" in n["calc"] and "11,5" in n["calc"] and "21,5" in n["calc"]


def test_prev_year_end_loans_by_segment():
    b = load("balance")
    p = b["prev_year_end"]
    year_end = f"{int(anchor_period()[:4]) - 1}Q4"
    assert p["as_of"] == b["history"][year_end]["date"]
    assert abs(v(p["loans_corporate"]) + v(p["loans_retail"]) - v(b["history"][year_end]["loans"])) < 1e-6
    if on_first_anchor():
        assert abs(v(p["loans_corporate"]) - 729.2) < 1e-6 and abs(v(p["loans_retail"]) - 2753.2) < 1e-6


def test_balance_history():
    b = load("balance")
    h = b["history"]
    a = h[anchor_period()]
    books = {k: v(n) for k, n in b["books"].items()}
    assert a["date"] == b["as_of"]
    assert abs(v(a["loans"]) - sum(books[x] for x in LOAN_BOOKS)) < 1e-6
    assert abs(v(a["funds"]) - books["retail_current"] - books["retail_term"] - books["corp_funds"]) < 1e-6
    assert abs(v(a["iea"]) - v(b["iea"])) < 1e-6 and v(a["bv_common"]) == v(b["equity"]["bv_common"])
    assert v(a["total_assets"]) == v(b["total_assets"])
    for p, row in h.items():
        assert row["date"] == q_end(p).isoformat(), p
        assert v(row["loans_ac_gross"]) == v(row["loans"]), f"{p}: отдельной книги кредитов по СС нет"
        assert v(row["loans"]) < v(row["iea"]) < v(row["total_assets"]), p
        assert 0 < v(row["bv_common"]) < v(row["funds"]), p
    early = [p for p, row in h.items() if "с акциями и паями" in row["iea"]["calc"]]
    assert all(p < "2025Q4" for p in early), "оценка процентных активов — только до раздельного раскрытия долговых бумаг"
    for p in year_quarters(anchor_period()) + [q_prev(year_quarters(anchor_period())[0])]:
        assert p not in early, f"{p}: ядру нужны точные процентные активы"


# ------------------------------------------------------------------ книги ЧПД

def test_nii_books_close_equals_balance():
    b, nb = load("balance"), load("nii_books")
    assert nb["period"] == anchor_period() and nb["as_of"] == b["as_of"]
    assert v(nb["days"]) == q_days(anchor_period())
    prev = b["history"][q_prev(anchor_period())]
    opened = 0.0
    for name in BOOKS:
        row = nb["books"][name]
        assert v(row["balance_close"]) == v(b["books"][name]), name
        assert abs(v(row["balance_avg"]) - (v(row["balance_open"]) + v(row["balance_close"])) / 2) < 1e-6, name
        opened += v(row["balance_open"]) if name in LOAN_BOOKS else 0.0
    assert abs(opened - v(prev["loans"])) < 1e-6, "остатки кредитных книг на начало квартала ≠ истории баланса"


def test_nii_books_rates_and_total():
    nb = load("nii_books")
    days = v(nb["days"])
    inc = exp = iea = 0.0
    for name in BOOKS:
        row = nb["books"][name]
        assert v(row["interest_q"]) > 0, f"{name}: проценты — величиной"
        assert abs(v(row["rate_anchor"]) - v(row["interest_q"]) / v(row["balance_avg"]) * 365 / days) < 2e-6, name
        if name in ASSET_BOOKS:
            inc += v(row["interest_q"])
            iea += v(row["balance_avg"])
        else:
            exp += v(row["interest_q"])
    assert abs(inc - v(nb["interest_assets_q"])) < 1e-6 and abs(exp - v(nb["interest_liabilities_q"])) < 1e-6
    total = inc - exp - v(nb["dia_q"]) + v(nb["other_interest_net_q"])
    assert abs(total - v(nb["nii_q"])) <= 0.15, f"проценты книг {total:.3f} ≠ ЧПД {v(nb['nii_q'])}"
    assert abs(v(nb["iea_avg"]) - iea) < 1e-6
    assert abs(v(nb["nim_eng_q"]) - v(nb["nii_q"]) * 365 / days / iea) < 2e-6
    assert nb["rates_carry_residual"] is False
    q = load("pnl_quarterly")["quarters"][anchor_period()]
    assert v(nb["nii_q"]) == v(q["nii"]) and v(nb["dia_q"]) == v(q["dia"])
    b = load("balance")["books"]
    assert abs(v(nb["current_share_anchor"]) - v(b["retail_current"]) / (v(b["retail_current"]) + v(b["retail_term"]))) < 2e-6
    if on_first_anchor():
        assert (round(inc, 1), round(exp, 1), v(nb["dia_q"]), v(nb["other_interest_net_q"]), v(nb["nii_q"])) == \
            (278.8, 119.3, 4.6, 2.7, 157.6), "278,8 − 119,3 − 4,6 + 2,7 = 157,6"
        want = {"cards": 0.31969, "cash_loans": 0.27680, "auto": 0.19235, "mortgage": 0.17256, "sme_loans": 0.40964,
                "corp_loans": 0.14929, "securities": 0.11606, "liquidity": 0.13420, "retail_current": 0.05684,
                "retail_term": 0.13134, "corp_funds": 0.06596, "wholesale": 0.10801}
        for name, rate in want.items():
            assert abs(v(nb["books"][name]["rate_anchor"]) - rate) < 6e-6, name
        assert abs(v(nb["nim_eng_q"]) - 0.11552) < 6e-6 and abs(v(nb["current_share_anchor"]) - 0.34139) < 6e-6


def test_key_average_of_the_anchor_quarter():
    nb, q = load("nii_books"), load("pnl_quarterly")["quarters"]
    assert v(nb["key_avg_anchor_q"]) == v(q[anchor_period()]["key_avg"])
    assert "sha256" in nb["key_avg_anchor_q"]["src"]
    if on_first_anchor():
        assert abs(v(nb["key_avg_anchor_q"]) - 0.146181) < 1e-6


# ------------------------------------------------------------------ ОПУ: операционный базис и три прибыли

LINES = ("nii", "llp_debt_fa", "fees_net", "insurance_net", "noncore_net", "opex", "misc_net")


def test_pnl_identities():
    """Тождества 1–4 и 7 договора ключей — в каждом квартале ряда."""
    for p, r in load("pnl_quarterly")["quarters"].items():
        assert abs(sum(v(r[k]) for k in LINES) - v(r["pbt"])) < 2e-6, f"{p}: pbt ≠ сумме семи строк"
        assert abs(v(r["pbt"]) + v(r["tax"]) - v(r["ni"])) < 2e-6, f"{p}: ni ≠ pbt + tax"
        assert abs(v(r["ni"]) - v(r["ni_nci"]) - v(r["ni_shareholders"])) < 2e-6, f"{p}: ni_shareholders ≠ ni − ni_nci"
        rep, blk = r["reported"], r["investment_block"]
        for x, bx in (("pbt", "pbt"), ("tax", "tax"), ("ni", "ni"), ("ni_shareholders", "ni_shareholders"), ("ni_nci", "nci")):
            assert abs(v(rep[x]) - v(r[x]) - v(blk[bx])) < 5e-6, f"{p}: reported.{x} ≠ {x} + блок"
        assert abs(v(r["noncore_net"]) + v(blk["debt_interest"])) < 1e-9, f"{p}: noncore_net ≠ −debt_interest"
        assert abs(v(blk["debt_interest"])) <= v(blk["nonfin_interest"]) + 1e-9, f"{p}: проценты под пакет больше всех процентов"
        assert abs(v(blk["adj_stake_sh"]) + v(blk["adj_interest_sh"]) - v(blk["ni_shareholders"])) < 2e-6, p
        assert abs(v(blk["reval"]) + v(blk["dividends"]) + v(blk["debt_interest"]) - v(blk["pbt"])) < 2e-6, p
        assert v(r["opex"]) < 0 and v(r["llp_debt_fa"]) < 0 and v(r["tax"]) < 0 and v(r["dia"]) > 0, f"{p}: знаки"
        assert v(r["at1_coupon"]) == 0.0


def test_interest_under_the_stake_is_the_issuer_adjustment_grossed_up_by_tax_only():
    """Решение проекта: возврат процентов под пакет = поправка эмитента / (1 − 0,25), без деления на долю акционеров;
    неконтролирующая доля несёт только эффект пакета (доля группы 50,01 %)."""
    for p, r in load("pnl_quarterly")["quarters"].items():
        blk = r["investment_block"]
        assert abs(v(blk["debt_interest"]) - v(blk["adj_interest_sh"]) / 0.75) < 2e-6, p
        assert abs(v(blk["nci"]) - v(blk["adj_stake_sh"]) * (1 - 0.5001) / 0.5001) < 2e-6, p
    if on_first_anchor():
        q = load("pnl_quarterly")["quarters"]
        got = [round(v(q[p]["noncore_net"]), 2) for p in ("2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2")]
        assert got == [1.67, 3.54, 3.62, 3.61, 2.27]
        assert all(v(q[p]["investment_block"]["ni_shareholders"]) == 0.0 for p in q if p < "2025Q2"), "до покупки пакета блок нулевой"


def test_three_profits_on_the_anchor():
    """Обязательный тест решений проекта: прибыль движка квартала якоря равна операционной прибыли эмитента;
    суммы года и полугодия; отчётная прибыль акционеров = операционная + блок пакета."""
    q = load("pnl_quarterly")["quarters"]
    a = q[anchor_period()]
    m = load("mgmt_quarterly")["quarters"][anchor_period()]
    exact = a["ni_shareholders"].get("estimated") is not True
    assert abs(v(a["ni_shareholders"]) - v(m["op_np_exact"] if m["op_np_exact"]["v"] is not None else m["op_np"])) <= (0.0005 if exact else 0.05)
    assert abs(v(a["ni_shareholders"]) - v(m["op_np"])) <= 0.05, "напечатанная операционная прибыль квартала"
    assert "PL!" in a["ni_shareholders"]["src"] or not exact, "канон — строка эмитента на листе PL справочника аналитика"
    if on_first_anchor():
        assert abs(v(a["ni_shareholders"]) - 52.06) <= 0.01 and abs(v(a["ni_shareholders"]) - 52.055169) < 1e-6
        assert abs(sum(v(q[f"2025Q{k}"]["ni_shareholders"]) for k in range(1, 5)) - 174.433) <= 0.001
        assert abs(sum(v(q[p]["ni_shareholders"]) for p in ("2026Q1", "2026Q2")) - 98.589) <= 0.001
        rep, blk = a["reported"], a["investment_block"]
        assert (v(rep["pbt"]), v(rep["tax"]), v(rep["ni"]), v(rep["ni_shareholders"]), v(rep["ni_nci"])) == (53.1, -13.6, 39.5, 44.3, -4.8)
        assert abs(v(blk["ni_shareholders"]) + 7.755) < 0.001 and (v(blk["reval"]), v(blk["dividends"])) == (-21.8, 4.3)
        assert abs(v(a["misc_net"]) - 4.5) < 1e-6 and abs(v(a["pbt"]) - 72.865) < 0.001 and abs(v(a["ni_nci"]) - 1.254) < 0.001


def test_reported_profit_of_the_dividend_years_is_the_ifrs_statement():
    """База проверки потолка политики — отчётная прибыль акционеров по МСФО (не операционная и не справочник)."""
    d, q = load("dividends"), load("pnl_quarterly")["quarters"]
    for y, rec in d["years"].items():
        quarters = [p for p in q if p.startswith(y)]
        s = sum(v(q[p]["reported"]["ni_shareholders"]) for p in quarters)
        if rec["complete"]:
            assert len(quarters) == 4 and abs(s - v(rec["ni_shareholders"])) <= 0.2, f"{y}: Σ кварталов {s:.3f}"
        else:
            assert rec["through"] == anchor_period() and abs(s - v(rec["ni_shareholders"])) <= 0.2, y
        assert "ifrs_fs" in rec["ni_shareholders"]["src"], f"{y}: источник — отчётность"
    if on_first_anchor():
        assert (v(d["years"]["2024"]["ni_shareholders"]), v(d["years"]["2025"]["ni_shareholders"])) == (122.397, 177.018)


# ------------------------------------------------------------------ капитал

def test_capital_slots_of_the_banking_group():
    c, b = load("capital"), load("balance")
    g = c["group_capital"]
    assert abs(v(g["base"]) + v(g["additional"]) + v(g["supplementary"]) - v(g["total"])) <= 0.002
    assert v(c["bank_base_capital"]) == v(g["base"]) and v(c["t2_recognized"]) == v(g["additional"])
    assert abs(v(c["basel"]["cet1"]) - (v(g["total"]) - v(c["t2_recognized"]))) < 1e-6
    assert abs(v(c["basel"]["rwa"]) - v(g["total"]) / v(c["n20_0"]["value"])) < 0.01
    assert abs(v(c["basel"]["total_ratio"]) - v(c["n20_0"]["value"])) < 1e-5
    assert c["n20_0"]["pre_dividend"] is False and c["n20_0"]["as_of"] == c["as_of"] == b["as_of"]
    assert v(c["at1"]["amount"]) == 0 and v(c["at1"]["coupon_annual"]) == 0 and v(c["at1"]["coupon_quarter"]) == 4
    assert v(c["n1_1_bank"]["value"]) < v(c["n20_2"]) < v(c["n20_0"]["value"])
    assert v(c["instruments_total"]) == v(b["wholesale"]["perpetual_sub"])
    last = c["history"][-1]
    assert last["period"] == anchor_period() and v(last["n20_0"]) == v(c["n20_0"]["value"]) and v(last["n20_1"]) == v(c["n1_1_bank"]["value"])
    assert [h["period"] for h in c["history"]] == sorted(h["period"] for h in c["history"])
    if on_first_anchor():
        assert (v(c["n20_0"]["value"]), v(c["n1_1_bank"]["value"]), v(c["n20_2"])) == (0.1293, 0.094, 0.1162)
        assert (v(g["total"]), v(g["base"]), v(g["additional"]), v(g["supplementary"])) == (683.648, 490.971, 123.182, 69.495)
        assert v(c["basel"]["cet1"]) == 560.466 and abs(v(c["basel"]["rwa"]) - 5287.3) < 0.05
        assert [round(v(h["n20_0"]), 4) for h in c["history"]] == [0.1005, 0.1215, 0.1165, 0.1181, 0.1246, 0.1299, 0.1293]
        assert c["n20_0"]["estimated"] is False and c["n1_1_bank"]["estimated"] is False


def test_core_form_reproduces_the_ratios_of_the_anchor():
    """Н20.0 и Н20.1 формой ядра на ключах листа капитала: K20 = BVreg − вычеты + инструменты; K11 = BVreg − прибыль
    после отсечки аудита − вычеты; дивиденд к выплате в регуляторный капитал якоря не возвращается."""
    c, b, q = load("capital"), load("balance"), load("pnl_quarterly")["quarters"]
    if c["n20_0"]["estimated"]:
        pytest.skip("нормативы якоря — оценка до выхода формы")
    chk = c["core_form_check"]
    k = {name: v(n) for name, n in chk["keys"].items() if isinstance(n, dict)}
    cutoffs = [int(x) for x in chk["keys"]["audit_cutoffs"].split(",")]
    total, (y, n) = 0.0, (int(anchor_period()[:4]), int(anchor_period()[-1]))
    while True:
        total += v(q[f"{y}Q{n}"]["ni_shareholders"])
        y, n = (y - 1, 4) if n == 1 else (y, n - 1)
        if n in cutoffs:
            break
    assert abs(total - v(chk["unaudited_profit"])) < 1e-6
    bvreg = v(b["equity"]["bv_common"]) - (1 - k["fvoci_recognition"]) * v(c["fvoci_reserve"])
    n20 = (bvreg - k["deductions_n20"] + v(c["at1"]["amount"]) + v(c["t2_recognized"])) / v(c["basel"]["rwa"]) + k["gap_n20"]
    n11 = (bvreg - max(total, 0.0) - k["deductions_n11"]) / v(c["basel"]["rwa"]) + k["gap_n11"]
    assert abs(n20 - v(chk["n20_0"])) < 2e-6 and abs(n11 - v(chk["n20_1"])) < 2e-6
    assert abs(n20 - v(c["n20_0"]["value"])) <= 5e-5, f"Н20.0 формой ядра {n20:.5f}"
    assert abs(n11 - v(c["n1_1_bank"]["value"])) <= 5e-5, f"Н20.1 формой ядра {n11:.5f}"
    if on_first_anchor():
        assert round(n20, 4) == 0.1293 and round(n11, 4) == 0.0940
        assert (k["deductions_n20"], k["gap_n20"], cutoffs) == (197.99, 0.0, [3, 4]) and abs(total - 98.589) < 0.001


def test_curve_and_reference_blocks():
    c = load("capital")
    curve = [v(c["ofz_curve_anchor"][t]) for t in ("1", "3", "5", "10")]
    assert all(0.02 < x < 0.4 for x in curve) and c["ofz_curve_anchor"]["as_of"] == c["as_of"]
    ids = [i["id"] for i in c["instruments"]]
    assert len(ids) == len(set(ids)) == 3
    assert sorted(i["call_from"] for i in c["instruments"] if i["call_from"]) == ["2026-12-20", "2027-09-15"] or not on_first_anchor()
    for i in c["instruments"]:
        assert 0 < v(i["rate"]) < 0.3 and v(i["amount_rub"]) > 0
    bi = c["basel_ifrs"]
    assert abs(v(bi["cet1"]) / v(bi["rwa"]) - v(bi["cet1_ratio"])) < 0.001


# ------------------------------------------------------------------ акции

def test_shares_arithmetic():
    s = load("shares")
    assert abs(v(s["issued_total"]) - v(s["treasury_ordinary"]) - v(s["outstanding_total"])) < 1e-6
    assert v(s["issued_ordinary"]) == v(s["issued_total"]) and v(s["outstanding_ordinary"]) == v(s["outstanding_total"])
    assert v(s["economic_treasury"]) == 0.0 and has_text(s["economic_treasury"]["calc"])
    assert abs(v(s["issued_total"]) - v(s["voting"]) - v(s["depositary_block"])) < 1e-4, "блок без голосов = размещённые − голосующие"
    assert list(s["by_ticker"].values()) == [{"class": "ordinary"}]
    if on_first_anchor():
        assert (v(s["issued_total"]), v(s["treasury_ordinary"]), v(s["outstanding_total"])) == (2682.74786, 132.8, 2549.94786)
        assert (v(s["depositary_block"]), v(s["voting"]), v(s["motivation_program"])) == (245.74614, 2437.00172, 177.337)


def test_corporate_actions_carry_the_split():
    acts = load("shares")["corporate_actions"]
    assert [a["date"] for a in acts] == sorted(a["date"] for a in acts)
    assert {a["kind"] for a in acts} <= {"split", "issue", "buyback_program", "deal", "event"}
    for a in acts:
        assert has_text(a["title"]) and "sha256" in a["src"], a["date"]
    splits = [a for a in acts if a["kind"] == "split"]
    assert len(splits) == 1
    sp = splits[0]
    assert v(sp["factor"]) == 10 and sp["date"] == "2026-04-15" and sp["first_trade_date"] == "2026-04-17"
    issues = [a for a in acts if a["kind"] == "issue"]
    assert all(v(a["shares_after"]) > v(a["shares_before"]) for a in issues)
    assert v(issues[-1]["shares_after"]) == v(load("shares")["issued_total"]), "последний выпуск даёт нынешнее число акций"


# ------------------------------------------------------------------ мосты

def test_bridge_values_are_window_means():
    b = load("bridge_mgmt_ifrs")
    for x in ("cor", "cir"):
        lo, hi = b[x]["window"]
        gaps = [v(h["gap"]) for h in b[x]["history"] if lo <= h["period"] <= hi]
        assert len(gaps) == v(b[x]["n"])
        assert abs(statistics.fmean(gaps) - v(b[x]["value"])) < 2e-6, x
        assert abs(statistics.stdev(gaps) - v(b[x]["sd"])) < 2e-6, x
    lo, hi = b["nim"]["window"]
    g4 = [v(h["gap_x4"]) for h in b["nim"]["history"] if lo <= h["period"] <= hi]
    assert len(g4) == v(b["nim"]["n"]) == len(year_quarters(anchor_period()))
    assert abs(statistics.fmean(g4) - v(b["nim"]["value"])) < 2e-6, "мост ЧПМ — среднее gap_x4 отчётных кварталов года якоря"
    for x in ("cor", "nim", "cir"):
        for h in b[x]["history"]:
            assert abs(v(h["engine"]) - v(h["mgmt"]) - v(h["gap"])) < 2e-6, f"{x} {h['period']}"
    lo, hi = b["cor"]["window"]
    books = [v(h["gap_books"]) for h in b["cor"]["history"] if lo <= h["period"] <= hi]
    assert abs(statistics.fmean(books) - v(b["cor"]["value_books"])) < 2e-6, "вариант на знаменателе движка — среднее gap_books"
    assert v(b["cor"]["value"]) in (v(b["cor"]["value_ac_only"]), v(b["cor"]["value_books"])), "мост CoR — один из двух знаменателей"
    assert abs(v(b["cor"]["value"]) - v(b["cor"]["value_books"])) < 0.0003, "знаменатели расходятся на кредиты по справедливой стоимости"
    if on_first_anchor():
        assert (v(b["cor"]["value"]), v(b["nim"]["value"]), v(b["cir"]["value"])) == (-0.002527, -0.001219, 0.015672)
        assert v(b["cor"]["value_ac_only"]) == -0.002449 and v(b["cor"]["value_books"]) == -0.002527
        assert v(b["cor"]["n"]) == v(b["cir"]["n"]) == 7 and b["cor"]["window"] == ["2024Q4", "2026Q2"]


def test_bridge_gate_reads_a_small_drift_on_the_anchor():
    """Гейт дрейфа моста сравнивает последнюю разность истории со значением моста: на якоре дрейф меньше порогов
    книги (0,2 п.п. для CoR, 0,3 п.п. для ЧПМ)."""
    b = load("bridge_mgmt_ifrs")
    for x, limit in (("cor", 0.002), ("nim", 0.003)):
        last = b[x]["history"][-1]
        assert last["period"] == anchor_period()
        assert abs(v(last["gap"]) - v(b[x]["value"])) < limit, x


def test_bridge_engine_definitions():
    """Значения движка в истории моста воспроизводятся из строк ОПУ и истории баланса: CoR — резервы к средним кредитам
    (знаменатель моста — без кредитов по справедливой стоимости или сумма кредитных книг; вариант на сумме книг — всегда
    рядом); ЧПМ — ЧПД к средним процентным активам движка; C/I — расходы к доходам на операционном базисе."""
    b, q, h = load("bridge_mgmt_ifrs"), load("pnl_quarterly")["quarters"], load("balance")["history"]
    for row in b["cir"]["history"]:
        p = row["period"]
        income = sum(v(q[p][k]) for k in ("nii", "fees_net", "insurance_net", "misc_net"))
        assert abs(-v(q[p]["opex"]) / income - v(row["engine"])) < 2e-6, f"cir {p}"
    checked = 0
    for row in b["cor"]["history"]:
        p = row["period"]
        if p in h and q_prev(p) in h:
            avg = (v(h[p]["loans"]) + v(h[q_prev(p)]["loans"])) / 2
            ac = avg - (v(h[p]["loans_fvtpl"]) + v(h[q_prev(p)]["loans_fvtpl"])) / 2
            by_books = v(b["cor"]["value"]) == v(b["cor"]["value_books"]) != v(b["cor"]["value_ac_only"])
            llp = -v(q[p]["llp_debt_fa"]) * 365 / q_days(p)
            assert abs(llp / avg - v(row["engine_books"])) < 2e-6, f"cor {p}: знаменатель движка"
            assert abs(llp / (avg if by_books else ac) - v(row["engine"])) < 2e-6, f"cor {p}"
            assert abs(v(row["engine_books"]) - v(row["mgmt"]) - v(row["gap_books"])) < 2e-6
            checked += 1
    for row in b["nim"]["history"]:
        p = row["period"]
        if p in h and q_prev(p) in h:
            avg = (v(h[p]["iea"]) + v(h[q_prev(p)]["iea"])) / 2
            assert abs(v(q[p]["nii"]) * 365 / q_days(p) / avg - v(row["engine"])) < 2e-6, f"nim {p}"
            assert abs(v(q[p]["nii"]) * 4 / avg - v(row["engine_x4"])) < 2e-6, f"nim x4 {p}"
            assert abs(v(row["engine_x4"]) - v(row["mgmt"]) - v(row["gap_x4"])) < 2e-6
            checked += 1
    assert checked >= 2 * len(year_quarters(anchor_period())), "отчётные кварталы года якоря проверены"
    a = anchor_period()
    assert abs(v(b["nim"]["history"][-1]["engine"]) - v(load("nii_books")["nim_eng_q"])) < 2e-6, f"ЧПМ движка {a}"


def test_bridge_history_uses_exact_management_values():
    """В истории моста — точные значения справочника аналитика, а пока их нет — напечатанные."""
    b, m = load("bridge_mgmt_ifrs"), load("mgmt_quarterly")["quarters"]
    for x in ("cor", "nim", "cir"):
        for h in b[x]["history"]:
            row = m[h["period"]]
            want = row[x + "_exact"] if row[x + "_exact"]["v"] is not None else row[x]
            assert v(h["mgmt"]) == v(want), f"{x} {h['period']}"


def test_bridge_ras_nii():
    r, q = load("bridge_ras_ifrs"), load("pnl_quarterly")["quarters"]
    n = r["nii"]
    assert n["method"] == "prev_quarter" and n["window"] == [anchor_period(), anchor_period()]
    for row in n["quarters"]:
        assert v(row["ifrs"]) == v(q[row["period"]]["nii"])
        assert abs(v(row["ifrs"]) / v(row["ras"]) - v(row["ratio"])) < 2e-6
    assert n["quarters"][-1]["period"] == anchor_period() and v(n["value"]) == v(n["quarters"][-1]["ratio"])
    for row in r["quarters"]:
        assert v(row["ifrs_ni_sh"]) == v(q[row["period"]]["ni_shareholders"]), "справочный ряд — операционная прибыль"
        assert abs(v(row["ifrs_ni_sh"]) / v(row["ras_ni"]) - v(row["ratio"])) < 2e-6
    if on_first_anchor():
        got = [round(v(x["ratio"]), 2) for x in n["quarters"] if x["period"] >= "2025Q1"]
        assert got == [1.67, 1.57, 1.48, 1.46, 1.45, 1.40]
        ratios = [v(x["ratio"]) for x in r["quarters"] if x["period"] >= "2025Q1"]
        assert round(min(ratios), 2) == 0.85 and round(max(ratios), 1) == 6.6


# ------------------------------------------------------------------ гайденс

def test_guidance_items():
    g, q, d = load("guidance"), load("pnl_quarterly")["quarters"], load("dividends")
    year = g["year"]
    assert year == int(anchor_period()[:4])
    it = g["items"]
    for k, kind in (("op_np_growth", "min"), ("dps_growth", "min"), ("roe_target", "point")):
        n = it[k]
        assert n["kind"] == kind and n["scope"] == "group" and has_text(n["text"]) and has_text(n["event"]), k
        assert dt.date.fromisoformat(n["date"]) <= dt.date.fromisoformat(g["as_of"]) or k == "roe_target"
    assert it["roe_target"]["tol"] == 0.005 and "операционному капиталу" in it["roe_target"]["scope_note"]
    base = sum(h["dps"]["v"] for h in d["history"] if h["year"] == year - 1)
    bound = f"{base * (1 + v(it['dps_growth'])):.2f}".replace(".", ",")
    assert bound in it["dps_growth"]["scope_note"] and "строгая" in it["dps_growth"]["scope_note"]
    ni = sum(v(q[f"{year - 1}Q{k}"]["ni_shareholders"]) for k in range(1, 5))
    assert f"{ni:.3f}".replace(".", ",") in it["op_np_growth"]["calc"]
    keys = {h["key"] for h in g["history"]}
    assert keys <= set(it) and {"op_np_growth", "dps_growth"} <= keys
    assert [h["date"] for h in g["history"]] == sorted(h["date"] for h in g["history"])
    if on_first_anchor():
        assert (v(it["op_np_growth"]), v(it["dps_growth"]), v(it["roe_target"])) == (0.2, 0.2, 0.3)
        assert g["as_of"] == "2026-08-11" and "17,88" in it["dps_growth"]["scope_note"] and "14,90" in it["dps_growth"]["scope_note"]
        dates = sorted({h["date"] for h in g["history"] if h["key"] == "op_np_growth"})
        assert dates == ["2026-03-19", "2026-05-21", "2026-08-11"], "исходный гайденс и два подтверждения"


# ------------------------------------------------------------------ календарь

KINDS = {"ifrs", "databook", "dividend_decision", "record", "form805", "ops_release", "cbr_rate", "cbr_forecast",
         "call_option", "deal", "regulation"}


def test_calendar_events():
    c = load("calendar")
    ids = [e["id"] for e in c["events"]]
    assert len(ids) == len(set(ids))
    assert [e["date"] for e in c["events"]] == sorted(e["date"] for e in c["events"])
    for e in c["events"]:
        assert e["kind"] in KINDS, e["id"]
        assert has_text(e["title"]) and "sha256" in e["src"], e["id"]
        assert isinstance(e["confirmed"], bool) and e["precision"] in ("day", "window"), e["id"]
        if e.get("estimated") or e["precision"] == "window":
            assert e.get("estimated") is True and e["confirmed"] is False and e["precision"] == "window", e["id"]
            assert e["earliest"] <= e["date"] <= e["latest"], e["id"]
        else:
            assert "earliest" not in e and "latest" not in e, e["id"]
        if e["kind"] in ("ifrs", "databook", "dividend_decision", "record", "form805"):
            assert e["covers"] and len(e["covers"]) == 6 and e["covers"][4] == "Q", e["id"]
        elif e["kind"] == "ops_release":
            assert e["covers"][4] == "M", e["id"]
        else:
            assert e["covers"] is None, e["id"]
        if e["kind"] == "deal":
            assert e["in_book"] is False
        else:
            assert "in_book" not in e


def test_calendar_carries_the_events_the_book_waits_for():
    c = load("calendar")
    by_id = {e["id"]: e for e in c["events"]}
    kinds = {k: [e for e in c["events"] if e["kind"] == k] for k in KINDS}
    nxt = anchor_period()
    y, k = int(nxt[:4]), int(nxt[-1])
    nxt = f"{y + 1}Q1" if k == 4 else f"{y}Q{k + 1}"
    closing = [e for e in kinds["ifrs"] if e["covers"] == nxt]
    assert len(closing) == 1, "МСФО, закрывающее первый прогнозный квартал"
    seed = load("dividends")["register_seed"]
    for r in seed:
        if r["status"] == "declared":
            rec = [e for e in kinds["record"] if e["covers"] == r["period"]]
            assert len(rec) == 1 and rec[0]["date"] == r["record_date"] and rec[0]["confirmed"], r["period"]
    assert len(kinds["cbr_rate"]) + len(kinds["cbr_forecast"]) >= 8
    assert len(kinds["ops_release"]) >= 12 and len(kinds["form805"]) >= 2 and len(kinds["databook"]) >= 2
    assert len(kinds["dividend_decision"]) >= 3 and len(kinds["call_option"]) == 2 and len(kinds["deal"]) == 1
    last = max(dt.date.fromisoformat(e["date"]) for e in c["events"])
    assert (last - dt.date.fromisoformat(c["as_of"])).days >= 365, "календарь — не меньше чем на 12 месяцев вперёд"
    if on_first_anchor():
        assert by_id["record-2026Q2"]["date"] == "2026-10-12" and by_id["regulation-2026-10-15"]["date"] == "2026-10-15"
        assert by_id["ifrs-2026Q3"]["date"] == "2026-11-19" and (by_id["ifrs-2026Q3"]["earliest"], by_id["ifrs-2026Q3"]["latest"]) == ("2026-11-01", "2026-11-30")
        assert by_id["ifrs-2026Q4"]["date"] == "2027-03-18" and by_id["ifrs-2026Q4"]["estimated"] is True
        assert by_id["call-2026-12-20"]["kind"] == by_id["call-2027-09-15"]["kind"] == "call_option"
        assert by_id["cbr-2026-10-23"]["kind"] == "cbr_forecast" and by_id["cbr-2026-12-18"]["kind"] == "cbr_rate"
        assert (by_id["ops-2026M09"]["earliest"], by_id["ops-2026M09"]["latest"]) == ("2026-10-17", "2026-10-29")
        assert by_id["deal-tochka"]["in_book"] is False and by_id["deal-tochka"]["latest"] == "2026-12-31"
        calls = {i["call_from"] for i in load("capital")["instruments"] if i["call_from"]}
        assert calls == {e["date"] for e in kinds["call_option"]}, "право отзыва — те же даты, что у инструментов капитала"


def test_form805_windows_follow_the_observed_lag():
    """Форма 0409805 появляется между 41-м и 73-м днём после квартала (годовая — до 92-го дня)."""
    for e in load("calendar")["events"]:
        if e["kind"] == "form805":
            end = q_end(e["covers"])
            lo, hi = ((dt.date.fromisoformat(e[k]) - end).days for k in ("earliest", "latest"))
            assert (lo, hi) == ((45, 92) if e["covers"].endswith("Q4") else (41, 73)), e["id"]


@pytest.mark.deadline
def test_calendar_is_ahead_of_today():
    """Срок записи данных: закрывающее МСФО первого прогнозного квартала ещё впереди или книга уже перезаякорена."""
    c = load("calendar")
    today = dt.date.today()
    ahead = [e for e in c["events"] if dt.date.fromisoformat(e.get("latest") or e["date"]) >= today]
    assert len(ahead) >= 6, "календарь событий исчерпан — продлить"


# ------------------------------------------------------------------ аналоги

def test_peers():
    p = load("peers")
    tickers = [b["ticker"] for b in p["banks"]]
    assert p["subject_ticker"] == "T" and "T" not in tickers and "SBER" in tickers
    assert len(tickers) == len(set(tickers)) >= 4
    for b in p["banks"]:
        for k in ("bv", "ni_ltm", "shares_outstanding", "dps_ltm"):
            assert v(b[k]) > 0, f"{b['ticker']}.{k}"
        assert 0.03 < v(b["capital_ratio"]["value"]) < 0.4 and has_text(b["capital_ratio"]["name"]), b["ticker"]
        roe = v(b["ni_ltm"]) / ((v(b["bv"]) + v(b["bv_prev"])) / 2)
        assert abs(roe - v(b["roe_ltm"])) < 0.002, f"{b['ticker']}: ROE"
        assert v(b["shares_outstanding"]) <= v(b["shares_issued"]) + 1e-6, b["ticker"]
        assert has_text(b["name"]) and has_text(b["basis"]) and "sha256" in b["src"]
