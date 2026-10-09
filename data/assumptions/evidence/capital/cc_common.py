# -*- coding: utf-8 -*-
"""Общие входы и помощники листа калибровки капитала Т (этап 1б, ключ calib-capital).

Все пути - относительные от каталога inputs/ листа (те же, что в папке передачи этапа 1). Единицы: млрд руб.; нормативы - проценты.
Форма ядра - MODEL.md Сбера, раздел 4.11 (model/capital.py):
  BVreg = BV + DPreg - (1 - f) * R
  K20 = BVreg - Ded20_0 * RWA / RWA_0 + AT1 + T2;   N20 = K20 / RWA + gap20 - ded_pp20
  K11 = BVreg - max(E, 0) - Ded11_0 * RWA / RWA_0;  N11 = K11 / RWA + gap11 - ded_pp11
"""
from __future__ import annotations
import csv, io, statistics as st
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE / "inputs"                      # малые входы: те же относительные пути, что в папке передачи
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

_buf = io.StringIO()


def P(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    _buf.write(s + "\n")


def flush(name):
    (OUT / name).write_text(_buf.getvalue(), encoding="utf-8", newline="\n")


def rows(rel, comment=False):
    with open(ROOT / rel, encoding="utf-8") as f:
        if comment:
            f = io.StringIO("".join(l for l in f if not l.startswith("#")))
        return list(csv.DictReader(f))


def wcsv(name, header, data):
    with open(OUT / name, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        for r in data:
            w.writerow(r)


def f2(x, n=2):
    return ("%+." + str(n) + "f") % x


def fmt(x, n=1):
    return ("%." + str(n) + "f") % x


def isnum(s):
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------- входы
F805 = {r["period_end"]: r for r in rows("stage1/ras/group_f805.csv")}
N20N1 = {r["period_end"]: r for r in rows("stage1/ras/group_n20_vs_bank_n1.csv")}
BR = {r["id"]: r for r in rows("stage1/ras/bridge_ifrs_to_group_capital.csv")}
IQ = rows("stage1/ifrs/ifrs_quarterly.csv")
IH = rows("stage1/ifrs/ifrs_history.csv")
TQ = rows("research/facts/t_quarterly.csv")
TCAP = rows("research/facts/t_capital.csv")
F123 = {r["form_date"]: r for r in rows("stage1/ras/cbr_f123_wide.csv")}
F135 = {r["form_date"]: r for r in rows("stage1/ras/cbr_f135_wide.csv")}
SCHED = yaml.safe_load(open(ROOT / "stage1/regulation/schedule.yaml", encoding="utf-8"))
ZC = rows("stage1/calib/capital/inputs/zcyc_quarter_ends_2024_2026.csv", comment=True)


def ih(metric):
    return {r["period"]: float(r["value"]) for r in IH if r["metric"] == metric and isnum(r["value"])}


def iq(metric):
    return {r["period"]: float(r["value"]) for r in IQ if r["metric"] == metric and isnum(r["value"])}


def tq(metric):
    return {r["period_end"]: float(r["value"]) for r in TQ if r["metric"] == metric and isnum(r["value"])}


def tcap(metric):
    return {r["date"]: float(r["value"]) for r in TCAP if r["metric"] == metric and isnum(r["value"])}


DATES = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]
QLAB = {"2025-03-31": "1Q2025", "2025-06-30": "2Q2025", "2025-09-30": "3Q2025", "2025-12-31": "4Q2025",
        "2026-03-31": "1Q2026", "2026-06-30": "2Q2026"}
ANCH = "2026-06-30"

BV = ih("eq_shareholders")                 # МСФО группы: капитал акционеров (отчётность)
RFV = ih("orf_fvoci")                      # фонд переоценки FVOCI после налога
OPCAP = ih("op_capital")                   # операционный капитал эмитента (Databook ROE_operating)
OPNI = iq("op_np")                         # операционная прибыль акционеров за квартал (Databook PL!37 / PL!107)
RNI = iq("np_shareholders")                # отчётная прибыль акционеров за квартал
DIVQ = iq("eqf_dividends__shareholders")   # дивиденды, объявленные в квартале (отчёт об изменениях капитала), знак минус


def g805(d, k):
    return float(F805[d][k]) / 1e6


CET1 = {d: g805(d, "cet1_th") for d in F805}
AT1 = {d: g805(d, "at1_th") for d in F805}
T2 = {d: g805(d, "tier2_th") for d in F805}
KTOT = {d: g805(d, "capital_total_th") for d in F805}
N200 = {d: float(F805[d]["n20_0_pct"]) for d in F805}
N201 = {d: float(F805[d]["n20_1_pct"]) for d in F805}
N202 = {d: float(F805[d]["n20_2_pct"]) for d in F805}
RWA0 = {d: g805(d, "rwa_implied_n20_0_th") for d in F805}   # вменённые RWA по Н20.0 [Р: капитал / норматив]
RWA1 = {d: g805(d, "rwa_implied_n20_1_th") for d in F805}
GP_YTD = {d: float(BR["B6"][d]) for d in DATES}              # прибыль банковской группы с начала года, ф. 0409803


def e_unaudited(d, series, cutoffs=(3, 4)):
    """E по календарю аудитов ядра: сумма прибыли кварталов после последней отсечки, строго предшествующей q."""
    y, m = int(d[:4]), int(d[5:7])
    q = m // 3
    tot, h, yy = 0.0, q, y
    while True:
        tot += series["%dQ%d" % (h, yy)]
        h -= 1
        if h == 0:
            h, yy = 4, yy - 1
        if h in cutoffs:
            return tot


EOP = {d: e_unaudited(d, OPNI) for d in DATES}
ERP = {d: e_unaudited(d, RNI) for d in DATES}

# ---------------------------------------------------------------- параметры якоря (часть 1.2)
F_REC = 0.64          # capital.n20.fvoci_recognition [В] - доля ОФЗ в долговом портфеле FVOCI якоря (часть 6)
DPREG0 = 0.0          # объявленный, но не вычтенный из регуляторного капитала дивиденд на якоре: 0 (отчёт, раздел 1)
T2_INSTR = AT1[ANCH]  # capital.n20.t2: регуляторные инструменты группы без прибыли = добавочный капитал группы (ф. 805, стр. 105)
R0 = RWA0[ANCH]
BVREG0 = BV[ANCH] + DPREG0 - (1 - F_REC) * RFV[ANCH]
DED20_0 = BVREG0 + T2_INSTR - KTOT[ANCH]          # при gap20 = 0 якорь воспроизводится точно
GAP20 = 0.0
E0 = EOP[ANCH]
GAP11 = N201[ANCH] / 100 - CET1[ANCH] / R0        # поправка на различие знаменателей Н20.1 и Н20.0
DED11_0 = BVREG0 - E0 - CET1[ANCH]
PI0 = T2[ANCH] / EOP[ANCH]                        # доля операционной прибыли МСФО в счёте регулятора на якоре


def stats(e, skip_first=False, skip_last=True):
    x = e[(1 if skip_first else 0):(len(e) - 1 if skip_last else len(e))]
    return "среднее %+.2f, СКО %.2f, макс. |ошибка| %.2f (n = %d)" % (st.mean(x), st.pstdev(x), max(abs(v) for v in x), len(x))
