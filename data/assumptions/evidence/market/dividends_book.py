# -*- coding: utf-8 -*-
"""Дивиденды, делитель и премия роста: числа книги против решений собраний и листов этапа 1 (MODEL §4.3, §5.2, §5.7, §8.4).

Источник дивидендов — документы эмитента и новость с датой у каждого решения (inputs/stage1/market/dividends_public.csv:
«История дивидендных выплат» эмитента, рекомендации совета директоров, протоколы собраний — с адресом и sha256); сверка
с брокерским календарём сделана на этапе 1 словами и в репозиторий не входит. Всё «на акцию» — после дробления 1:10
(15.04.2026); исходное значение решения — в графе dps_pre_split того же листа.
Лист повторяет:
  * календарь: лаги решения, реестра и выплаты в кварталах от квартала прибыли — карта книги равна последнему
    наблюдённому лагу по номеру квартала; реестр и выплата — два квартала;
  * долю выплаты к средней операционной прибыли четырёх кварталов (центр политики) и её ось;
  * тест истории: выплаты завершённого года не выше потолка политики от отчётной прибыли акционеров МСФО за год;
  * базу гайденса по дивиденду на акцию: сумма решений за кварталы 2025 года;
  * делитель: размещённые акции, акции в обращении, ожидаемый скачок оценки на экс-дату;
  * правило стартовой премии роста кредитов: среднее из прироста сверх сектора за 12 месяцев до якоря и за последнее
    полугодие в годовом выражении, корпоративная — не выше 20 п.п. (история премий — лист надстройки миров этапа 1).
Запуск из корня репозитория: python -B data/assumptions/evidence/market/dividends_book.py → out/dividends_book_out.json
(код выхода 1 — расхождение с шаблоном книги).
"""
from __future__ import annotations

import statistics
import sys
from datetime import date
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
IN = HERE / "inputs" / "stage1"
OUT = HERE / "out"
sys.path.insert(0, str(HERE.parent))
import evlib  # noqa: E402

SPLIT_DATE = "2026-04-15"                                   # дробление 1:10


def qidx(d: str) -> int:
    """Номер квартала даты ISO на сквозной шкале."""
    y, m = int(d[:4]), int(d[5:7])
    return y * 4 + (m - 1) // 3


def pidx(period: str) -> int:
    """Номер последнего квартала периода прибыли («2025Q3», «2024Q1-Q3»)."""
    year, last = int(period[:4]), int(period[-1])
    return year * 4 + last - 1


def compute() -> dict:
    book = evlib.template()
    div_book = book["dividends"]
    cmp = evlib.Compare()
    rows = evlib.read_csv(IN / "market/dividends_public.csv")
    cmp.true("у каждого решения — документ эмитента с sha256 и новость с датой",
             all(r["issuer_doc_url"] and len(r["issuer_doc_sha256"]) == 64 and r["news_url"] and r["news_published"] for r in rows))
    cmp.true("DPS после дробления = DPS решения / коэффициент; у решений после дробления коэффициент 1",
             all(abs(float(r["dps"]) * float(r["split_factor"]) - float(r["dps_pre_split"])) < 1e-9 if r["dps_pre_split"]
                 else (float(r["split_factor"]) == 1 and r["decided_date"] > SPLIT_DATE) for r in rows))
    # --- календарь
    lags = []
    for r in rows:
        p = pidx(r["fiscal_period"])
        lags.append({"period": r["fiscal_period"], "h": int(r["fiscal_period"][-1]), "dps": float(r["dps"]),
                     "decision": qidx(r["decided_date"]) - p, "record": qidx(r["record_date"][:10]) - p,
                     "payment": qidx(r["pay_deadline_nominee"]) - p, "decided": r["decided_date"], "record_date": r["record_date"][:10]})
    cal = div_book["calendar"]
    last_by_h = {}
    for x in lags:
        last_by_h[str(x["h"])] = x["decision"]
    cmp.eq("dividends.calendar.decision_lag_quarters = последний наблюдённый лаг по номеру квартала",
           cal["decision_lag_quarters"], last_by_h)
    quarterly = [x for x in lags if "-" not in x["period"]]     # решения за один квартал (после 9 месяцев 2024 года)
    cmp.true("реестр — два квартала после квартала прибыли во всех решениях за квартал",
             all(x["record"] == cal["reg_deduction_lag_quarters"] for x in quarterly))
    cmp.true("выплата — два квартала после квартала прибыли во всех решениях за квартал",
             all(x["payment"] == cal["payment_lag_quarters"] for x in quarterly))
    cmp.true("календарь квартальный, пробных проходов вперёд нет",
             cal["frequency"] == "quarterly" and cal["checkpoints_ahead"] == 0
             and all(cal[k] is None for k in ("agm_quarter", "reg_deduction_quarter", "payment_quarter", "checkpoints")))
    # --- доля выплаты и потолок
    opb = {r["period"]: r for r in evlib.read_csv(IN / "calib/pnl/op_basis_quarterly.csv")}

    def op(period: str) -> float:                             # '2025Q3' → операционная прибыль акционеров квартала
        return float(opb[f"{period[-1]}Q{period[:4]}"]["ni_shareholders"])

    def reported(period: str) -> float:
        return float(opb[f"{period[-1]}Q{period[:4]}"]["ni_sh_reported"])

    issued = float(next(r for r in reversed(evlib.read_csv(IN / "market/shares_history.csv"))
                        if r["date"] == "2026-06-30")["issued"]) / 1e6
    hist = next(r for r in evlib.read_csv(IN / "market/shares_history.csv") if r["date"] == "2026-06-30" and r["treasury"])
    treasury, outstanding = float(hist["treasury"]) / 1e6, float(hist["outstanding"]) / 1e6
    W = div_book["policy"]["base_window_quarters"]
    shares = {}
    for x in quarterly[1:]:                                   # шесть решений с полной базой четырёх кварталов после Росбанка
        y, h = int(x["period"][:4]), x["h"]
        t = y * 4 + h - 1
        base = statistics.mean(op(f"{(t - k) // 4}Q{(t - k) % 4 + 1}") for k in range(W))
        shares[x["period"]] = x["dps"] * issued / 1000 / base
    payout = div_book["policy"]["payout"]["LT"]
    cmp.eq("dividends.policy.payout = среднее шести решений", payout, round(statistics.mean(shares.values()), 2), 1e-9)
    cap = div_book["policy"]["cap"]
    cap_check = {}
    for year in ("2024", "2025"):
        pool = sum(float(r["dps"]) for r in rows if r["fiscal_period"].startswith(year)) * issued / 1000
        profit = sum(reported(f"{year}Q{q}") for q in (1, 2, 3, 4))
        cap_check[year] = {"pool_bn": round(pool, 3), "reported_profit_bn": round(profit, 3), "share": round(pool / profit, 4)}
        cmp.true(f"выплаты {year} года не выше потолка политики", pool <= cap * profit + 1e-9)
    cmp.eq("тест истории — потолок", div_book["policy"]["history_test"], "cap")
    dps_2025 = sum(float(r["dps"]) for r in rows if r["fiscal_period"].startswith("2025"))
    # --- делитель
    val = book["valuation"]
    cmp.eq("делитель — размещённые акции", val["shares_basis"], "issued")
    ratio = outstanding / issued
    declared = next(r for r in rows if r["fiscal_period"] == "2026Q2")
    jump = -float(declared["dps"]) * ratio
    ax = next(a for a in val["uncertainty"]["axes"] if a["paths"] == ["valuation.share_count_adj"])
    cmp.true("ось числа акций накрывает акции в обращении", ax["low"] <= ratio - 1 + 1e-4 and ax["high"] > 0)
    # --- премия роста кредитов: правило
    history = yaml.safe_load((IN / "worlds/bank_overlay_draft.yaml").read_text(encoding="utf-8"))["t_premium"]["history"]
    prem = {(g, str(period)): float(row["premium_pp"]) / 100 for g, rows in history.items() for period, row in rows.items()
            if isinstance(row.get("premium_pp"), (int, float))}
    rule = {}
    for g in ("corporate", "mortgage", "retail_other"):
        v = (prem[(g, "12 мес. до 30.06.2026")] + prem[(g, "1П2026, в годовом выражении")]) / 2
        rule[g] = round(min(v, 0.20) if g == "corporate" else v, 4)
        start = book["volumes"]["loan_share_drift"][g]
        cmp.true(f"премия роста {g}: старт книги в пределах 1,5 п.п. от правила",
                 abs(start["2026"] - rule[g]) <= 0.015 + 1e-9 and start["2026"] == start["2027"] and start["LT"] == 0.0)
    cmp.true("премия сходит к нулю к 2032 году, после 2031 года не действует",
             all(book["volumes"]["loan_share_drift"][g]["LT_from"] == 2032 for g in rule) and book["volumes"]["share_drift_until"] == 2031)
    return {
        "lags": lags,
        "calendar_book": {k: cal[k] for k in ("decision_lag_quarters", "reg_deduction_lag_quarters", "payment_lag_quarters")},
        "payout_to_avg4": {k: round(v, 4) for k, v in shares.items()},
        "payout_mean": round(statistics.mean(shares.values()), 4), "payout_book": payout,
        "cap_check": cap_check, "dps_2025": round(dps_2025, 2), "dps_guidance_threshold": round(dps_2025 * 1.2, 2),
        "shares": {"issued_mln": issued, "treasury_mln": treasury, "outstanding_mln": outstanding,
                   "outstanding_to_issued": round(ratio, 6), "exdate_jump_for_declared": round(jump, 3),
                   "declared_dps": float(declared["dps"]), "record_date": declared["record_date"][:10]},
        "loan_premium_rule": rule,
        "book_mismatches": cmp.mismatches,
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    res = compute()
    evlib.write_json(OUT / "dividends_book_out.json", res)
    for x in res["lags"]:
        print(x["period"], "DPS", x["dps"], "лаги решения / реестра / выплаты:", x["decision"], x["record"], x["payment"])
    for k in ("payout_to_avg4", "payout_mean", "cap_check", "dps_2025", "dps_guidance_threshold", "shares", "loan_premium_rule"):
        print(k, res[k])
    print("расхождения с шаблоном:", res["book_mismatches"] or "нет")
    return 1 if res["book_mismatches"] else 0


if __name__ == "__main__":
    sys.exit(main())
