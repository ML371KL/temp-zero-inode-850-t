# -*- coding: utf-8 -*-
"""β_E акции T (МКПАО «Т-Технологии») по правилу семейства A-V1 — независимая перепроверка этапа 1 (ключ market).

Правило (A-V1, книга Сбера 1.3: «недельная полная доходность (цена + валовой дивиденд в экс-дату) против MCFTR,
окно 3 года»; сверка — окна 2 и 5 лет): недели — по последнему общему торговому дню ISO-недели; МНК; ст. ошибка —
Ньюи — Уэст, 4 лага; доходность через разрыв торгов > 10 календарных дней не считается.

Особенности T:
  * одна бумага — два кода ISS: TCSG (28.10.2019–27.11.2024) и T (с 28.11.2024), доска TQBR; склейка по дате;
  * дробление 1:10 (15.04.2026): торгов 13–16.04.2026 не было; цены до 17.04.2026 делятся на 10;
  * пауза торгов при редомициляции 16.02–15.03.2024: неделя через разрыв 15.02 → 18.03.2024 (32 дня) исключается;
  * дивиденды — лист решений ../dividends_public.csv (DPS после дробления, дата реестра); при расчётах T+1
    (с 31.07.2023) экс-дата = дата реестра; каждая экс-дата сверяется гэпом цены (блок [1]);
  * долларовые дивиденды на ГДР 2019–2021 в окна 2 / 3 / 5 лет не попадают (последний реестр — 26.03.2021).

Код написан заново (не копия листа Сбера и не копия research/code/t_val_beta.py); самопроверка — тот же код на
SBER с листом решений Сбера на окнах листа Сбера (до 29.09.2026) обязан дать 0,835 / 0,826 / 1,173 (блок [5]).
Только стандартная библиотека. Детерминированно. Запуск: python -B beta_t.py
Вывод: out/beta_out.txt, out/beta_results.csv, out/beta_summary.json, ../price_T_daily_split_adjusted.csv
"""
import csv, datetime as dt, json, math, os, sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
INP = os.path.join(HERE, "inputs", "stage1", "market", "beta", "inputs")
OUTD = os.path.join(HERE, "out")
DIVS_T = os.path.join(HERE, "inputs", "stage1", "market", "dividends_public.csv")
DIVS_SBER = os.path.join(INP, "sber_dividends_public.csv")      # копия публичного листа решений Сбера (для самопроверки кода)

END = "2026-10-06"                 # последний полный торговый день до даты работы 07.10.2026
SPLICE = "2024-11-28"              # первый день торгов под кодом T
SPLIT_FIRST_DAY = "2026-04-17"     # первый торговый день после дробления 1:10
SPLIT = 10.0
T1_SWITCH = "2023-07-31"           # расчёты T+1 на Мосбирже (последний день T+2 — 28.07.2023)
MAX_GAP_DAYS = 10
NW_LAGS = 4
ERP = 0.0557
PRICE_FIELD = "LEGALCLOSEPRICE"    # как в листе Сбера; CLOSE — вариант чувствительности
LOG = []


def out(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    LOG.append(s)


def years_back(date, n):
    y, m, d = map(int, date.split("-"))
    return f"{y - n:04d}-{m:02d}-{d:02d}"


# ---------------------------------------------------------------- данные
def read_csv(name):
    with open(os.path.join(INP, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def t_series(field=PRICE_FIELD):
    """Сквозной дневной ряд T после дробления: [{date, secid, raw, raw_close, factor, px, close, ...}]; дни без сделок выброшены."""
    rows = []
    for sec, keep in (("TCSG", lambda x: x < SPLICE), ("T", lambda x: x >= SPLICE)):
        for r in read_csv(f"prices_{sec}.csv"):
            if not keep(r["TRADEDATE"]) or float(r["NUMTRADES"] or 0) <= 0:
                continue
            k = SPLIT if r["TRADEDATE"] < SPLIT_FIRST_DAY else 1.0
            rows.append(dict(date=r["TRADEDATE"], secid=sec, legal_raw=float(r["LEGALCLOSEPRICE"]), close_raw=float(r["CLOSE"]),
                             factor=k, px=float(r[field]) / k, close=float(r["CLOSE"]) / k, legal=float(r["LEGALCLOSEPRICE"]) / k,
                             numtrades=int(float(r["NUMTRADES"])), value=float(r["VALUE"]), volume_raw=float(r["VOLUME"]),
                             volume=float(r["VOLUME"]) * k))
    rows.sort(key=lambda z: z["date"])
    assert len({z["date"] for z in rows}) == len(rows)
    return rows


def simple_series(name, field, need_trades=False):
    res = {}
    for r in read_csv(name):
        if need_trades and float(r.get("NUMTRADES") or 0) <= 0:
            continue
        v = r.get(field) or r.get("CLOSE")
        if v not in (None, ""):
            res[r["TRADEDATE"]] = float(v)
    return res


def ex_map(divs, dates, shift=0):
    """divs: [(record_date, dps)] → {экс-дата: DPS}, протокол сверки. T+1: экс = реестр (или первый торговый день после него);
    T+2 (до 31.07.2023): экс = последний торговый день не позже реестра минус 1."""
    idx = {x: i for i, x in enumerate(dates)}
    res, info = {}, []
    for rec, dps in divs:
        if rec <= dates[0] or rec > dates[-1]:
            continue
        le = [x for x in dates if x <= rec]
        i_rec = idx[le[-1]]
        settle = 2 if rec < T1_SWITCH else 1
        i_last = i_rec - settle if le[-1] == rec else i_rec - settle + 1
        i_ex = i_last + 1 + shift
        ex = dates[i_ex]
        res[ex] = res.get(ex, 0.0) + dps
        info.append(dict(record=rec, last_cum=dates[i_last], ex=ex, dps=dps, settle=settle))
    return res, info


def total_return(px, ex):
    """Индекс полной доходности: дивиденд прибавляется к цене в экс-дату и реинвестируется."""
    dates = sorted(px)
    tr, level = {}, 1.0
    for i, x in enumerate(dates):
        if i:
            level *= (px[x] + ex.get(x, 0.0)) / px[dates[i - 1]]
        tr[x] = level
    return tr


# ---------------------------------------------------------------- доходности и регрессия
def weekly(a, b, weekday=None, monthly=False):
    """Доходности a и b между последними общими торговыми днями соседних ISO-недель (или недель, кончающихся в weekday; или месяцев)."""
    common = sorted(set(a) & set(b))
    last = {}
    for x in common:
        dd = dt.date.fromisoformat(x)
        if monthly:
            key = (dd.year, dd.month)
        elif weekday is None:
            key = dd.isocalendar()[:2]
        else:
            key = (dd + dt.timedelta(days=(weekday - dd.weekday()) % 7)).toordinal()
        last[key] = x                      # дни идут по возрастанию → остаётся последний
    ends = sorted(last.values())
    res = []
    for p, q in zip(ends, ends[1:]):
        res.append(dict(start=p, end=q, gap=(dt.date.fromisoformat(q) - dt.date.fromisoformat(p)).days,
                        y=a[q] / a[p] - 1.0, x=b[q] / b[p] - 1.0))
    return res


def regress(rows, d0, d1, max_gap=MAX_GAP_DAYS, lags=NW_LAGS):
    """МНК y = α + β·x по неделям с концом в (d0; d1] без разрывов; ст. ошибка β — Ньюи — Уэст (Бартлетт, lags), поправка n/(n−2)."""
    s = [r for r in rows if d0 < r["end"] <= d1 and r["gap"] <= max_gap]
    n = len(s)
    if n < 12:
        return None
    xs, ys = [r["x"] for r in s], [r["y"] for r in s]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    beta = sxy / sxx
    alpha = my - beta * mx
    u = [y - alpha - beta * x for x, y in zip(xs, ys)]
    ssr = sum(e * e for e in u)
    se_ols = math.sqrt(ssr / (n - 2) / sxx)
    # HAC для наклона: Var(β) = (n/(n−2)) · Σ_l w_l Σ_t z_t z_{t−l} / sxx², z_t = (x_t − x̄)·u_t
    z = [(x - mx) * e for x, e in zip(xs, u)]
    acc = sum(v * v for v in z)
    for l in range(1, lags + 1):
        w = 1.0 - l / (lags + 1.0)
        acc += 2.0 * w * sum(z[t] * z[t - l] for t in range(l, n))
    se_hac = math.sqrt(max(acc, 0.0) * n / (n - 2)) / sxx
    # устойчивость: наибольший сдвиг β при исключении одной недели
    infl = []
    for i in range(n):
        x2, y2 = xs[:i] + xs[i + 1:], ys[:i] + ys[i + 1:]
        m1, m2 = sum(x2) / (n - 1), sum(y2) / (n - 1)
        b2 = sum((p - m1) * (q - m2) for p, q in zip(x2, y2)) / sum((p - m1) ** 2 for p in x2)
        infl.append((b2 - beta, s[i]["end"]))
    infl.sort(key=lambda t: -abs(t[0]))
    return dict(n=n, beta=beta, alpha=alpha, se_ols=se_ols, se_hac=se_hac, r2=1 - ssr / syy, rho=sxy / math.sqrt(sxx * syy),
                vol_s=math.sqrt(syy / (n - 1) * 52), vol_m=math.sqrt(sxx / (n - 1) * 52), first=s[0]["end"], last=s[-1]["end"],
                skipped=[(r["start"], r["end"], r["gap"]) for r in rows if d0 < r["end"] <= d1 and r["gap"] > max_gap], infl=infl[:3])


# ---------------------------------------------------------------- расчёт
def main():
    os.makedirs(OUTD, exist_ok=True)
    mc = simple_series("prices_MCFTR.csv", "CLOSE")
    im = simple_series("prices_IMOEX.csv", "CLOSE")
    fn = simple_series("prices_MOEXFN.csv", "CLOSE")
    ser = t_series()
    px = {z["date"]: z["px"] for z in ser if z["date"] <= END}
    px_close = {z["date"]: z["close"] for z in ser if z["date"] <= END}
    dates = sorted(px)
    divs = sorted((r["record_date"], float(r["dps"])) for r in csv.DictReader(open(DIVS_T, encoding="utf-8")) if r["currency"] == "RUB")
    out("=" * 118)
    out(f"β_E АКЦИИ T ПО ПРАВИЛУ A-V1 (независимая перепроверка). Рынок: MCFTR (полная доходность, брутто). Конец окон: {END}")
    out(f"Цены: MOEX ISS, TQBR, {PRICE_FIELD}; TCSG до 27.11.2024 + T с 28.11.2024; до 17.04.2026 ÷ 10; дни без сделок исключены")
    out(f"Ряд: {dates[0]} … {dates[-1]}, {len(dates)} торговых дней; дивиденды — {os.path.basename(DIVS_T)} ({len(divs)} решений в рублях)")
    out("=" * 118)

    # сквозной ряд цены для карточки цены и сборщика (вся история кода с 28.10.2019; 5 лет — строки с 2021-10-06)
    with open(os.path.join(OUTD, "price_T_daily_split_adjusted.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["date", "secid_iss", "close", "legal_close", "split_factor", "close_raw", "legal_close_raw", "numtrades", "value_rub",
                    "volume_shares_post_split", "in_5y_window"])
        for z in ser:
            w.writerow([z["date"], z["secid"], round(z["close"], 4), round(z["legal"], 4), int(z["factor"]), z["close_raw"], z["legal_raw"],
                        z["numtrades"], z["value"], int(round(z["volume"])), int(z["date"] > years_back(END, 5))])

    out("\n[0] Стыки ряда")
    for a, b, lab in (("2024-02-15", "2024-03-18", "пауза редомициляции"), ("2024-11-27", "2024-11-28", "смена кода TCSG → T"),
                      ("2026-04-10", "2026-04-17", "дробление 1:10")):
        gap = (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days
        mret = mc[b] / mc[a] - 1
        out(f"  {lab:22s}: {a} {px[a]:8.2f} → {b} {px[b]:8.2f}  ({px[b] / px[a] - 1:+.2%}; MCFTR {mret:+.2%}); разрыв {gap} дн. "
            f"{'— неделя исключается' if gap > MAX_GAP_DAYS else '— неделя считается'}")
    nontrade = [r["TRADEDATE"] for r in read_csv("prices_T.csv") + read_csv("prices_TCSG.csv") if float(r["NUMTRADES"] or 0) <= 0]
    out(f"  дни без сделок в выгрузке ISS (исключены): {len(nontrade)}; 2024: {min(x for x in nontrade if x[:4] == '2024')}…{max(x for x in nontrade if x[:4] == '2024')}; "
        f"2026: {', '.join(x for x in nontrade if x[:4] == '2026')}")

    ex, info = ex_map(divs, dates)
    out("\n[1] Сверка экс-дат (T+1: экс = дата реестра). Гэп цены ≈ −дивиденд; полная доходность дня ≈ рынку")
    for z in info:
        i = dates.index(z["ex"])
        prev = px[dates[i - 1]]
        m_prev = max(x for x in mc if x < z["ex"])
        win = dates[max(1, i - 2):i + 3]
        rel = {x: (px[x] / px[dates[dates.index(x) - 1]]) / (mc[x] / mc[max(y for y in mc if y < x)]) - 1 for x in win if x in mc}
        worst = min(rel, key=rel.get)
        out(f"  реестр {z['record']}  посл. день с див. {z['last_cum']}  экс {z['ex']}  DPS {z['dps']:5.2f} = {z['dps'] / prev:6.2%} | цена {px[z['ex']] / prev - 1:+7.2%}  "
            f"полная {(px[z['ex']] + z['dps']) / prev - 1:+7.2%}  MCFTR {mc[z['ex']] / mc[m_prev] - 1:+7.2%}  "
            f"{'OK: наибольшее отставание от рынка в окне ±2 дня — в экс-дату' if worst == z['ex'] else 'наибольшее отставание от рынка в окне ±2 дня — ' + worst}")

    tr = total_return(px, ex)
    tr_close = total_return(px_close, ex)
    tr_p1 = total_return(px, ex_map(divs, dates, +1)[0])
    tr_m1 = total_return(px, ex_map(divs, dates, -1)[0])
    main_rows = weekly(tr, mc)
    variants = {
        "ПРАВИЛО: TR→MCFTR, недели ISO": main_rows,
        "TR→MCFTR, недели по средам": weekly(tr, mc, weekday=2),
        "TR→MCFTR, месяцы": weekly(tr, mc, monthly=True),
        "TR (CLOSE вместо LEGALCLOSE)→MCFTR": weekly(tr_close, mc),
        "цена→MCFTR (без дивидендов)": weekly(px, mc),
        "цена→IMOEX": weekly(px, im),
        "TR→MOEXFN (ценовой отраслевой)": weekly(tr, fn),
        "ловушка: экс-дата +1 день": weekly(tr_p1, mc),
        "ловушка: экс-дата −1 день": weekly(tr_m1, mc),
        "без поправки на паузу (разрывы не исключены)": main_rows,
    }
    windows = [("2 года", years_back(END, 2), END), ("3 года", years_back(END, 3), END), ("5 лет", years_back(END, 5), END)]
    ref = [("4 года", years_back(END, 4), END), ("после редомициляции (с 18.03.2024)", "2024-03-18", END),
           ("код T (с 28.11.2024)", "2024-11-28", END), ("после дробления (с 17.04.2026)", "2026-04-17", END)]
    res, csv_rows = {}, []
    for lab, d0, d1 in windows + ref:
        for vn, rows in variants.items():
            kw = {}
            if vn.startswith("TR→MCFTR, месяцы"):
                kw = dict(max_gap=45, lags=2)
            if vn.startswith("без поправки"):
                kw = dict(max_gap=10 ** 6)
            st = regress(rows, d0, d1, **kw)
            if st is None:
                continue
            if "месяцы" in vn:
                st["vol_s"] *= math.sqrt(12 / 52)
                st["vol_m"] *= math.sqrt(12 / 52)
            res[(lab, vn)] = st
            csv_rows.append(dict(ticker="T", window=lab, window_from=d0, window_to=d1, variant=vn,
                                 **{k: (round(v, 5) if isinstance(v, float) else v) for k, v in st.items() if k not in ("infl", "skipped")}))
    out("\n[2] Беты (ст. ош. — Ньюи — Уэст, 4 лага; месяцы — 2 лага); σ — годовая волатильность")
    out(f"  {'окно':36s} {'вариант':46s} {'n':>4s} {'β':>6s} {'se':>6s} {'R²':>5s} {'ρ':>5s} {'σ_T':>5s} {'σ_m':>5s}  период")
    for (lab, vn), r in res.items():
        out(f"  {lab:36s} {vn:46s} {r['n']:4d} {r['beta']:6.3f} {r['se_hac']:6.3f} {r['r2']:5.2f} {r['rho']:5.2f} {r['vol_s']:5.2f} {r['vol_m']:5.2f}  {r['first']}…{r['last']}")
    MAIN = "ПРАВИЛО: TR→MCFTR, недели ISO"
    out("\n[3] Устойчивость правила: исключённые недели (разрыв > 10 дней) и наибольшее влияние одной недели")
    for lab, _, _ in windows:
        r = res[(lab, MAIN)]
        out(f"  {lab:7s}: исключено {r['skipped']}; влияние: " + ", ".join(f"{e} {dlt:+.3f}" for dlt, e in r["infl"]))
    out("\n[4] ИТОГ ПО ПРАВИЛУ A-V1 (T, недели, полная доходность к MCFTR)")
    rule = {lab: res[(lab, MAIN)] for lab, _, _ in windows}
    for lab, r in rule.items():
        out(f"  {lab:7s}: β_E {r['beta']:.3f} (ст. ош. {r['se_hac']:.3f}; МНК {r['se_ols']:.3f}; n {r['n']}; R² {r['r2']:.2f}; α {r['alpha'] * 52:+.1%} в год)")
    c = rule["3 года"]
    ci = (c["beta"] - 1.96 * c["se_hac"], c["beta"] + 1.96 * c["se_hac"])
    lo, hi = min(r["beta"] for r in rule.values()), max(r["beta"] for r in rule.values())
    rng = (math.floor(ci[0] * 20) / 20, math.ceil(ci[1] * 20) / 20)
    out(f"  ЦЕНТР (окно 3 года): β_E = {c['beta']:.3f} → в книгу {round(c['beta'], 2):.2f}; 95 % интервал {ci[0]:.2f}–{ci[1]:.2f}")
    out(f"  Диапазон по A-V1 (95 % интервал центра, округлённый наружу до 0,05): {rng[0]:.2f}–{rng[1]:.2f}; разброс окон 2–5 лет: {lo:.3f}–{hi:.3f}")
    out(f"  Премия β_E × ERP {ERP:.2%} = {c['beta'] * ERP * 100:.2f} п.п. (при β 1,04 — {1.04 * ERP * 100:.2f}; по оси 0,95–1,15: {0.95 * ERP * 100:.2f}–{1.15 * ERP * 100:.2f})")

    # [5] самопроверка кода на Сбере (окна листа Сбера, конец 29.09.2026)
    out("\n[5] Самопроверка кода: SBER, лист решений Сбера, окна до 29.09.2026 (лист Сбера: 0,835 / 0,826 / 1,173)")
    sb = simple_series("prices_SBER.csv", PRICE_FIELD, need_trades=True)
    sb = {k: v for k, v in sb.items() if k <= "2026-09-29"}
    sd = sorted((r["record_date"], float(r["dps_ordinary"])) for r in csv.DictReader(open(DIVS_SBER, encoding="utf-8")) if r["record_date"])
    sb_tr = total_return(sb, ex_map(sd, sorted(sb))[0])
    sb_rows = weekly(sb_tr, {k: v for k, v in mc.items() if k <= "2026-09-29"})
    selfcheck = {}
    for lab, n in (("2 года", 2), ("3 года", 3), ("5 лет", 5)):
        r = regress(sb_rows, years_back("2026-09-29", n), "2026-09-29")
        selfcheck[lab] = round(r["beta"], 4)
        out(f"  {lab:7s}: β {r['beta']:.3f} (ст. ош. {r['se_hac']:.3f}, n {r['n']}, R² {r['r2']:.2f})")
    # Сбер на окнах T (сопоставление)
    sb2 = simple_series("prices_SBER.csv", PRICE_FIELD, need_trades=True)
    sb2_rows = weekly(total_return(sb2, ex_map(sd, sorted(sb2))[0]), mc)
    out("  Сбер на окнах T (до 06.10.2026): " + ", ".join(f"{lab} {regress(sb2_rows, d0, d1)['beta']:.3f}" for lab, d0, d1 in windows))

    summary = dict(
        rule="A-V1: недели ISO, полная доходность (валовой DPS в экс-дату) к MCFTR, МНК, Ньюи — Уэст 4 лага; центр — окно 3 года",
        ticker="T", end=END, price_field=PRICE_FIELD, splice=dict(TCSG_until="2024-11-27", T_from=SPLICE),
        split=dict(ratio="1:10", first_trading_day_after=SPLIT_FIRST_DAY, no_trading="2026-04-13…2026-04-16"),
        pause_excluded="2024-02-16…2024-03-15 (неделя через разрыв 15.02 → 18.03.2024)",
        beta_E_center=round(c["beta"], 4), beta_E_center_book=round(c["beta"], 2), se_hac_center=round(c["se_hac"], 4),
        ci95=[round(ci[0], 3), round(ci[1], 3)], range_A_V1=list(rng), range_windows=[round(lo, 4), round(hi, 4)],
        windows={lab: dict(beta=round(r["beta"], 4), se_hac=round(r["se_hac"], 4), se_ols=round(r["se_ols"], 4), n=r["n"], r2=round(r["r2"], 3),
                           first=r["first"], last=r["last"]) for lab, r in rule.items()},
        sensitivity_3y={vn: round(res[("3 года", vn)]["beta"], 4) for vn in variants},
        reference={lab: round(res[(lab, MAIN)]["beta"], 4) for lab, _, _ in ref if (lab, MAIN) in res},
        selfcheck_sber_to_2026_09_29=selfcheck, selfcheck_expected={"2 года": 0.835, "3 года": 0.826, "5 лет": 1.173},
        erp=ERP, premium_pp=round(c["beta"] * ERP * 100, 3),
        inputs=dict(prices="MOEX ISS history TQBR / index (fetch_iss.py; inputs/SOURCES.json — адреса и sha256)",
                    dividends="../dividends_public.csv — решения собраний: DPS после дробления и дата реестра"))
    with open(os.path.join(OUTD, "beta_summary.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUTD, "beta_results.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(csv_rows)
    with open(os.path.join(OUTD, "beta_out.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(LOG) + "\n")


if __name__ == "__main__":
    main()
