# -*- coding: utf-8 -*-
"""Часть 5. Проба правила «дивиденд по политике, рост - остаток» (LEAD-DECISIONS-2 §5) на квартальной арифметике.

Свой простой счёт, НЕ ядро: шесть кредитных книг, балансирующие активы, грубый ОПУ от уровней книги, капитал в форме ядра.
Назначение - проверка здравости правила и параметров до кода; числа - порядки, не печать.
"""
import yaml
from cc_common import *
import p2_rwa
import p3467_misc

BOOKS = p2_rwa.BOOKS
SECTOR = {"cards": "retail_other", "cash_loans": "retail_other", "auto": "retail_other", "mortgage": "mortgage", "sme_loans": "corporate", "corp_loans": "corporate"}
QUARTERS = [(2026, 3), (2026, 4)] + [(y, q) for y in range(2027, 2033) for q in (1, 2, 3, 4)]
YEARS = list(range(2026, 2033))
OVER = yaml.safe_load(open(ROOT / "stage1/worlds/bank_overlay_draft.yaml", encoding="utf-8"))
G_T = {"N": 0.055, "H": 0.070, "M": 0.113}          # рост после 2033: инфляция мира (4,0 / 5,5 / 9,8) + 1,5 % [worlds/README.md; реальный рост терминала книги]
PREM0 = {"retail_other": 0.12, "mortgage": 0.03, "corporate": 0.20}     # LEAD-2 §6 п. 2: 2026-2027, линейно к 0 к 2032
FUNDS_PREM = {int(k): v / 100 for k, v in OVER["funds"]["start_premium_pp"].items()}   # черновик надстройки (stage1/worlds)
LAG = {1: 2, 2: 2, 3: 1, 4: 2}                        # dividends.calendar.decision_lag_quarters (LEAD-2 §3 п. 1)
NOUT_SHARE = 2549.9 / 2682.7                         # дивиденд уходит из капитала по акциям в обращении

# --- грубый ОПУ: калибровка на 2К2026 (stage1/mgmt/mgmt_kpi.csv) --------------------------------
MK = {}
for r in rows("stage1/mgmt/mgmt_kpi.csv"):
    if r["period"] == "2026Q2" and isnum(r["value"]):
        MK[r["metric"]] = float(r["value"])
TAU, NCI = 0.24, 0.023                               # эффективная ставка налога ~24 %; доля НДУ в операционной прибыли 2,3 % (rev-finance §4.1)
BRIDGE_COR = -0.00231                                # CoR движка = упр. - 0,231 п.п. (stage1/mgmt, мост)
S_BAL = 0.02                                         # маржа на средствах, не выданных в кредиты из-за капитала [В]
NIM_PATH = {"anchor": MK["nim_exact"] / 100, "target": 0.1075, "year": 2030}
CI_PATH = {"anchor": MK["cir_exact"] / 100, "target": 0.47, "year": 2030}
COR_NORM = {2026: 0.049, 2027: 0.050, 2028: 0.052, 2029: 0.054, 2030: 0.055}     # режим «нормализация», упр. базис (LEAD-2 §8 п. 1)
HIST_NI = [OPNI["3Q2025"], OPNI["4Q2025"], OPNI["1Q2026"], OPNI["2Q2026"]]
REGISTER = {(2026, 3): 4.60 * 2549.9 / 1000, (2026, 4): 4.70 * 2549.9 / 1000}    # объявленные: за 1К2026 (вычет в 3К) и 2К2026 (в 4К), млрд руб.


def lin(path, y, q):
    t = (y + q / 4) - 2026.5
    T = (path["year"] + 1.0) - 2026.5
    w = min(1.0, max(0.0, t / T))
    return path["anchor"] + (path["target"] - path["anchor"]) * w


def sector_growth(world, sector, y):
    g = OVER["sector"]["worlds"][world]["credit_growth"][sector]
    if y <= 2029:
        return float(g[str(y)])
    g29 = float(g["2029"])
    return g29 + (G_T[world] - g29) * min(1.0, (y - 2029) / 4)


def funds_growth(world, y):
    g = OVER["sector"]["worlds"][world]["funds_growth"]["retail"]
    base = float(g[str(y)]) if y <= 2029 else float(g["2029"]) + (G_T[world] - float(g["2029"])) * min(1.0, (y - 2029) / 4)
    return (1 + base) * (1 + FUNDS_PREM.get(y, 0.0)) - 1


def premium(sector, y):
    return PREM0[sector] * (1.0 if y <= 2027 else max(0.0, (2032 - y) / 5))


def pot_growth(world, b, y, prem_shift=0.0):
    s = SECTOR[b]
    p = premium(s, y)
    if p > 0 or prem_shift < 0:
        p = max(0.0, p + prem_shift) if s == "mortgage" else p + prem_shift * (1.0 if y <= 2027 else max(0.0, (2032 - y) / 5))
    return (1 + sector_growth(world, s, y)) * (1 + p) - 1


DEFAULT = dict(buffer=0.015, delta=0.0025, H=8, catch_up=0.25, order="dividend_first", enabled=True, payout=0.25,
               drift=0.01, drift_until=2027, dn_path=None, t2_shift=0.0, levels_now=False, prem_shift=0.0, lam_min=0.0, cor_shift=0.0)


def simulate(world, scen, **kw):
    p = dict(DEFAULT); p.update(kw)
    dens, _, bk0, comp, _, _, _ = ANCHOR
    scen_t = SCEN_T[scen]
    E = {b: bk0[b] for b in BOOKS}; Ep = dict(E)
    L0 = sum(E.values())
    alr = 353.4 / L0                                    # резерв / валовые кредиты якоря (Databook Credit!19)
    oa_ratio = bk0["other_assets"] / L0
    fixed = bk0["other_assets_fixed"]
    F = tq("bs.customer_accounts")[ANCH]
    wh = 671.3 / F                                      # оптовое фондирование / средства клиентов (stage1/ifrs/anchor_books.csv)
    liab = tq("bs.total_liabilities")[ANCH]
    ol_ratio = (liab - F - 671.3) / L0
    nci_eq = tq("bs.nci")[ANCH]
    la0 = bk0["securities"] + bk0["liquidity"]; s_sec = bk0["securities"] / la0
    bv = BV[ANCH]
    adjR = -(1 - F_REC) * RFV[ANCH]
    t2 = T2_INSTR + p["t2_shift"] * R0
    a_iea = MK["iea_avg"] / ((tq("loans.gross.total")["2026-03-31"] + L0) / 2)
    lavg0 = (tq("loans.gross.total")["2026-03-31"] + L0) / 2
    cor0 = MK["cor_total_exact"] / 100 + BRIDGE_COR
    pbt0 = OPNI["2Q2026"] / (1 - TAU) / (1 - NCI)
    rev0 = (pbt0 + cor0 * lavg0 / 4) / (1 - CI_PATH["anchor"])
    n_nonint = (rev0 * 4 - NIM_PATH["anchor"] * a_iea * lavg0) / lavg0      # непроцентный доход на рубль кредитов (связь с объёмом = 1)
    ni_hist = list(HIST_NI)
    ni_year = {2026: [OPNI["1Q2026"], OPNI["2Q2026"]]}
    pending = dict(REGISTER)                             # (год, квартал вычета) -> сумма
    out = []
    dn = 1.0
    cum_div = 0.0

    def floors(y):
        v = scen_t[min(y, 2031)]
        add = (v["conservation"] + v["sifi"] + v["ccyb"]) / 100
        return 0.08 + add, 0.045 + add, v["deduction_pp"] / 100

    def req_star(i):
        r20 = r11 = -1.0
        for h in range(0, p["H"] + 1):
            j = min(i + h, len(QUARTERS) - 1)
            yy = QUARTERS[j][0] if i + h < len(QUARTERS) else QUARTERS[-1][0] + (i + h - len(QUARTERS)) // 4 + 1
            f20, f11, _ = floors(yy)
            r20 = max(r20, f20 + p["buffer"] - h * p["delta"]); r11 = max(r11, f11 + p["buffer"] - h * p["delta"])
        return r20, r11

    for i, (y, q) in enumerate(QUARTERS):
        if p["dn_path"] is not None:
            dn = p["dn_path"].get("%dQ%d" % (y, q), dn)
        elif y <= p["drift_until"]:
            dn *= (1 + p["drift"]) ** 0.25
        m = {b: (1 + pot_growth(world, b, y, p["prem_shift"])) ** 0.25 - 1 for b in BOOKS}
        Ep_new = {b: Ep[b] * (1 + m[b]) for b in BOOKS}
        F_new = F * (1 + funds_growth(world, y)) ** 0.25
        nim = NIM_PATH["target"] if p["levels_now"] else lin(NIM_PATH, y, q)
        ci = CI_PATH["target"] if p["levels_now"] else lin(CI_PATH, y, q)
        cor = (COR_NORM[min(y, 2030)] if not p["levels_now"] else 0.055) + BRIDGE_COR + p["cor_shift"]
        f20, f11, dedpp = floors(y)
        r20, r11 = req_star(i)
        pool = pending.get((y, q), 0.0)
        Lold = sum(E.values()); Lp_avg = (sum(Ep.values()) + sum(Ep_new.values())) / 2

        def step(lam, mu, div):
            En = {}
            for b in BOOKS:
                gap = max(0.0, Ep_new[b] / (E[b] * (1 + m[b])) - 1)
                En[b] = E[b] * (1 + lam * m[b] + mu * p["catch_up"] / 4 * gap)
            Ln = sum(En.values()); Lavg = (Lold + Ln) / 2
            rev = (nim * a_iea * Lavg + n_nonint * Lavg + S_BAL * max(0.0, Lp_avg - Lavg)) / 4
            ni = (rev * (1 - ci) - cor * Lavg / 4) * (1 - TAU) * (1 - NCI)
            bvn = bv + ni - div
            oa = oa_ratio * Ln
            la = F_new * (1 + wh) + ol_ratio * Ln + bvn + nci_eq - (Ln * (1 - alr) + oa + fixed)
            rwa = (sum(dens[b] * En[b] for b in BOOKS) + dens["securities"] * s_sec * la + dens["liquidity"] * (1 - s_sec) * la + dens["other_assets"] * oa) * dn
            k20 = bvn + adjR - DED20_0 * rwa / R0 + t2
            k11s = bvn + adjR - DED11_0 * rwa / R0
            n20 = k20 / rwa - dedpp
            n11s = k11s / rwa + GAP11 - dedpp
            ey = ni_year.get(y, [])
            e_un = ni if q in (1, 4) else sum(ey) + ni           # отсечки [3, 4]: К1 - К1; К2 - 6М; К3 - 9М; К4 - К4
            n11 = (k11s - max(e_un, 0.0)) / rwa + GAP11 - dedpp
            h = min((n20 - r20) * rwa, (n11s - r11) * rwa)
            return dict(En=En, Ln=Ln, ni=ni, bv=bvn, rwa=rwa, n20=n20, n11=n11, n11s=n11s, h=h, la=la, bind=("n20" if (n20 - r20) <= (n11s - r11) else "n11"))

        lam, mu, div, cut, gap_flag = 1.0, 0.0, pool, 0.0, False
        if not p["enabled"]:
            res = step(1.0, 0.0, div)
        else:
            if p["order"] == "growth_first" and pool > 0:
                h1 = step(1.0, 0.0, 0.0)["h"]
                div = max(0.0, min(pool, h1))
                cut = pool - div
            res = step(1.0, 0.0, div)
            if res["h"] < 0:
                r0 = step(p["lam_min"], 0.0, div)
                if r0["h"] < 0:
                    lam = p["lam_min"]
                    if p["order"] == "dividend_first" and div > 0:
                        need = -r0["h"]
                        newdiv = max(0.0, div - need)
                        cut = pool - newdiv; div = newdiv
                    res = step(lam, 0.0, div)
                    gap_flag = res["h"] < -1e-6
                else:
                    lo, hi = p["lam_min"], 1.0
                    for _ in range(50):
                        mid = (lo + hi) / 2
                        if step(mid, 0.0, div)["h"] >= 0: lo = mid
                        else: hi = mid
                    lam = lo; res = step(lam, 0.0, div)
            elif p["catch_up"] > 0 and any(Ep_new[b] > E[b] * (1 + m[b]) * 1.0001 for b in BOOKS):
                if step(1.0, 1.0, div)["h"] >= 0:
                    mu = 1.0
                else:
                    lo, hi = 0.0, 1.0
                    for _ in range(50):
                        mid = (lo + hi) / 2
                        if step(1.0, mid, div)["h"] >= 0: lo = mid
                        else: hi = mid
                    mu = lo
                res = step(1.0, mu, div)
        # принять квартал
        rwa_prev = out[-1]["rwa"] if out else R0
        rec = dict(y=y, q=q, lam=lam, mu=mu, n20=res["n20"], n11=res["n11"], n11s=res["n11s"], req20=r20, req11=r11, floor20=f20, floor11=f11, rwa=res["rwa"],
                   rwa_growth=res["rwa"] / rwa_prev - 1, L=res["Ln"], Lpot=sum(Ep_new.values()), ni=res["ni"], bv=res["bv"], div=div, pool=pool, cut=cut,
                   gap=gap_flag, below_floor=(res["n20"] < f20 - 1e-9 or res["n11"] < f11 - 1e-9), bind=res["bind"], dn=dn, ld=res["Ln"] / F_new, la=res["la"])
        out.append(rec)
        E = res["En"]; Ep = Ep_new; F = F_new; bv = res["bv"]; cum_div += div
        ni_hist.append(res["ni"]); ni_year.setdefault(y, []).append(res["ni"])
        # решение о дивиденде за квартал прибыли (y, q): вычет через LAG[q] кварталов
        base = sum(ni_hist[-4:]) / 4
        j = i + LAG[q]
        if j < len(QUARTERS) and not (y == 2026 and q <= 2):
            key = QUARTERS[j]
            pending[key] = pending.get(key, 0.0) + p["payout"] * base * NOUT_SHARE
    return out


def by_year(out):
    res = {}
    prev_L, prev_rwa, prev_Lp = None, None, None
    L_start = tq("loans.gross.total")[ANCH]
    for y in YEARS:
        qs = [r for r in out if r["y"] == y]
        n = len(qs)
        ann = 4 / n
        L0_ = prev_L if prev_L else L_start
        Lp0 = prev_Lp if prev_Lp else L_start
        rw0 = prev_rwa if prev_rwa else R0
        res[y] = dict(n20_end=qs[-1]["n20"], n20_min=min(r["n20"] for r in qs), req20_end=qs[-1]["req20"], n11_min=min(r["n11"] for r in qs), n11s_end=qs[-1]["n11s"],
                      floor20=qs[-1]["floor20"], floor11=qs[-1]["floor11"],
                      lam=sum(r["lam"] for r in qs) / n, loans=(qs[-1]["L"] / L0_) ** ann - 1, loans_pot=(qs[-1]["Lpot"] / Lp0) ** ann - 1, rwa=(qs[-1]["rwa"] / rw0) ** ann - 1,
                      cut=sum(r["cut"] for r in qs), div=sum(r["div"] for r in qs), ni=sum(r["ni"] for r in qs), gap=any(r["gap"] for r in qs),
                      below=any(r["below_floor"] for r in qs), level=qs[-1]["L"] / qs[-1]["Lpot"], bv=qs[-1]["bv"], ld=qs[-1]["ld"])
        prev_L, prev_rwa, prev_Lp = qs[-1]["L"], qs[-1]["rwa"], qs[-1]["Lpot"]
    return res


def pct(x, n=1):
    return ("%." + str(n) + "f") % (100 * x)


def run():
    global ANCHOR, SCEN_T
    ANCHOR = p2_rwa.anchor_densities(False)
    SCEN_T = p3467_misc.scen_table()
    P("")
    P("=" * 110)
    P("ЧАСТЬ 5. ПРОБА ПРАВИЛА «ДИВИДЕНД ПО ПОЛИТИКЕ, РОСТ - ОСТАТОК» (свой квартальный счёт, не ядро; режим «нормализация»)")
    P("=" * 110)
    P("Входы: книги и плотности якоря - часть 2; капитал - форма ядра с параметрами части 1 (Ded20_0 %.1f, t2 %.1f, Ded11_0 %.1f, gap11 %+.4f);" % (DED20_0, T2_INSTR, DED11_0, GAP11))
    P("  рост сектора - stage1/worlds/bank_overlay_draft.yaml (2026-2029, далее сход к росту терминала мира к 2033); премия Т 12 / 3 / 20 п.п. в 2026-2027, к 0 к 2032;")
    P("  средства клиентов - рост сектора x премия черновика надстройки %s;" % {k: round(v * 100, 1) for k, v in FUNDS_PREM.items()})
    P("  ОПУ [Р, грубо]: ЧПМ %.2f -> 10,75 %% к 2030 (линейно), C/I %.1f -> 47 %%, CoR режима «нормализация» 4,9 / 5,0 / 5,2 / 5,4 / 5,5 %% (упр. базис, мост -0,231 п.п.);"
      % (100 * NIM_PATH["anchor"], 100 * CI_PATH["anchor"]))
    P("  непроцентный доход и расходы растут с кредитами (связь 1); налог 24 %%, НДУ 2,3 %%; калибровка: операционная прибыль 2К2026 = %.2f." % OPNI["2Q2026"])
    P("  дивиденд: 25 %% средней операционной прибыли четырёх кварталов x акции в обращении / размещённые; вычет через 2 / 2 / 1 / 2 квартала; реестр: 3К2026 %.1f, 4К2026 %.1f."
      % (REGISTER[(2026, 3)], REGISTER[(2026, 4)]))
    P("  правило: запас 1,5 п.п.; требование с глиссадой H = 8, delta = 0,25 п.п.; навёрстывание 0,25 в год; дрейф плотности +1 % в год до 2027; Н20.1 в ограничении - с прибылью периода.")
    base = simulate("H", "schedule", enabled=False)
    P("")
    P("5.0. Потенциальный рост (без ограничения), мир H: кредиты %s; операционный ROE (прибыль года / средний капитал) %s"
      % (" / ".join("%d: %s" % (y, pct(by_year(base)[y]["loans_pot"])) for y in YEARS),
         " / ".join("%d: %s" % (y, pct(by_year(base)[y]["ni"] * (2 if y == 2026 else 1) / ((by_year(base)[y]["bv"] + (by_year(base)[y - 1]["bv"] if y > 2026 else BV[ANCH])) / 2))) for y in YEARS)))

    # ---------------- 5.1 основная таблица: 3 мира x 3 сценария
    P("")
    P("5.1. Центр книги: три мира x три сценария (годовые значения; 2026 - второе полугодие, темпы в годовом выражении)")
    hdr = ["мир", "сценарий", "показатель"] + [str(y) for y in YEARS]
    P(" | ".join(hdr))
    tab = []
    summary = {}
    for w in ("N", "H", "M"):
        for s in ("schedule", "mid", "strict"):
            o = simulate(w, s)
            by = by_year(o)
            lines = [("Н20.0 на конец года, %", lambda v: pct(v["n20_end"], 2)), ("требование Н20.0 с глиссадой, %", lambda v: pct(v["req20_end"], 2)),
                     ("пол Н20.0, %", lambda v: pct(v["floor20"], 2)),
                     ("Н20.1 отчётный, минимум года, %", lambda v: pct(v["n11_min"], 2)), ("пол Н20.1, %", lambda v: pct(v["floor11"], 2)),
                     ("Н20.1 с прибылью на конец года, %", lambda v: pct(v["n11s_end"], 2)),
                     ("lambda, среднее за год", lambda v: "%.2f" % v["lam"]), ("рост кредитов потенциальный, %", lambda v: pct(v["loans_pot"])),
                     ("рост кредитов фактический, %", lambda v: pct(v["loans"])), ("рост RWA, %", lambda v: pct(v["rwa"])),
                     ("уровень кредитов к потенциальному, %", lambda v: pct(v["level"])), ("срез дивиденда, млрд руб.", lambda v: "%.1f" % v["cut"]),
                     ("кредиты / средства клиентов, %", lambda v: pct(v["ld"]))]
            for name, fn in lines:
                r = [w, s, name] + [fn(by[y]) for y in YEARS]
                tab.append(r); P(" | ".join(r))
            cutq = [(r["y"], r["q"], r["cut"]) for r in o if r["cut"] > 1e-6]
            lamq = {(r["y"], r["q"]): r["lam"] for r in o}
            summary[(w, s)] = dict(by=by, cutq=cutq, lamq=lamq, o=o)
            P("   %s x %s: срез дивиденда по кварталам: %s; lambda 4К2026 %.2f, 1К2027 %.2f, 4К2027 %.2f, 1К2028 %.2f; первый квартал с lambda < 1: %s; отчётный норматив ниже пола: %s"
              % (w, s, (", ".join("%dQ%d %.1f" % c for c in cutq) or "нет"), lamq[(2026, 4)], lamq[(2027, 1)], lamq[(2027, 4)], lamq[(2028, 1)],
                 next(("%dQ%d" % (r["y"], r["q"]) for r in o if r["lam"] < 0.999), "нет"),
                 (", ".join("%dQ%d" % (r["y"], r["q"]) for r in o if r["below_floor"]) or "нет")))
    wcsv("p5_trial_center.csv", hdr, tab)

    P("")
    P("5.2. Сводка центра: уровень кредитов к потенциальному пути (доля урезанного роста = 100 - уровень), %")
    hdr = ["мир", "сценарий", "конец 2027", "конец 2028", "конец 2030", "конец 2032", "средняя lambda 2027-2028", "кварталов с lambda < 1 до 2032", "срез дивиденда всего, млрд", "срез в 1К2027 / 1К2028"]
    P(" | ".join(hdr))
    tab = []
    for (w, s), v in summary.items():
        by = v["by"]; o = v["o"]
        l2728 = [r["lam"] for r in o if r["y"] in (2027, 2028)]
        r = [w, s, pct(by[2027]["level"]), pct(by[2028]["level"]), pct(by[2030]["level"]), pct(by[2032]["level"]), "%.2f" % (sum(l2728) / len(l2728)),
             str(sum(1 for x in o if x["lam"] < 0.999)), "%.1f" % sum(x["cut"] for x in o),
             "%.1f / %.1f" % (sum(x["cut"] for x in o if (x["y"], x["q"]) == (2027, 1)), sum(x["cut"] for x in o if (x["y"], x["q"]) == (2028, 1)))]
        tab.append(r); P(" | ".join(r))
    wcsv("p5_trial_summary.csv", hdr, tab)
    wts = {"schedule": 0.35, "mid": 0.45, "strict": 0.20}
    for w in ("N", "H", "M"):
        P("  мир %s, взвешенно по сценариям (0,35 / 0,45 / 0,20): уровень кредитов к потенциальному на конец 2028 - %.1f %%, на конец 2030 - %.1f %%, на конец 2032 - %.1f %%"
          % (w, 100 * sum(wts[s] * summary[(w, s)]["by"][2028]["level"] for s in wts), 100 * sum(wts[s] * summary[(w, s)]["by"][2030]["level"] for s in wts),
             100 * sum(wts[s] * summary[(w, s)]["by"][2032]["level"] for s in wts)))

    # ---------------- 5.3 квартальный путь модальной клетки
    P("")
    P("5.3. Квартальный путь: мир H x «средняя группа» (модальная клетка сценариев)")
    hdr = ["квартал", "Н20.0", "требование", "пол", "Н20.1 отчётный", "Н20.1 с прибылью", "требование Н20.1", "lambda", "навёрстывание", "RWA к/к, %", "прибыль", "дивиденд", "срез", "связывает"]
    P(" | ".join(hdr))
    tab = []
    for r in summary[("H", "mid")]["o"]:
        if r["y"] <= 2029:
            row = ["%dQ%d" % (r["y"], r["q"]), pct(r["n20"], 2), pct(r["req20"], 2), pct(r["floor20"], 2), pct(r["n11"], 2), pct(r["n11s"], 2), pct(r["req11"], 2),
                   "%.2f" % r["lam"], "%.2f" % r["mu"], pct(r["rwa_growth"], 1), "%.1f" % r["ni"], "%.1f" % r["div"], "%.1f" % r["cut"], r["bind"]]
            tab.append(row); P(" | ".join(row))
    wcsv("p5_trial_quarterly_H_mid.csv", hdr, tab)

    # ---------------- 5.4 чувствительности
    P("")
    P("5.4. Чувствительности (мир H; уровень кредитов к потенциальному на конец 2028 / 2030 / 2032, %; минимум lambda и число кварталов без роста до 2029; срез дивиденда всего, млрд руб.; кварталы среза)")
    hdr = ["вариант", "schedule", "mid", "strict"]
    P(" | ".join(hdr))
    tab = []

    def cell(o):
        by = by_year(o)
        cuts = [(r["y"], r["q"]) for r in o if r["cut"] > 1e-6]
        lam = [r["lam"] for r in o if r["y"] <= 2029]
        return "%s / %s / %s; мин. lambda %.2f, кварталов с lambda < 0,05: %d; срез %.1f%s" % (
            pct(by[2028]["level"]), pct(by[2030]["level"]), pct(by[2032]["level"]), min(lam), sum(1 for x in lam if x < 0.05), sum(r["cut"] for r in o),
            (" (" + ", ".join("%dQ%d" % c for c in cuts[:4]) + ("…" if len(cuts) > 4 else "") + ")") if cuts else "")

    stepped = {k: v for k, v in DN_PATH}
    variants = [("центр", {}),
                ("запас 0,5 п.п.", dict(buffer=0.005)), ("запас 3,0 п.п.", dict(buffer=0.03)),
                ("глиссада delta = 0 (ступени набраны за 8 кварталов сразу)", dict(delta=0.0)), ("глиссада delta = 0,5 п.п.", dict(delta=0.005)),
                ("без глиссады (H = 0)", dict(H=0)), ("окно H = 4", dict(H=4)), ("окно H = 12", dict(H=12)),
                ("навёрстывание 0", dict(catch_up=0.0)), ("навёрстывание 0,5", dict(catch_up=0.5)),
                ("дрейф плотности -2 % в год", dict(drift=-0.02)), ("дрейф плотности 0", dict(drift=0.0)), ("дрейф плотности +3,5 % в год", dict(drift=0.035)),
                ("плотность ступенями 4-го квартала (путь части 2.4)", dict(dn_path=stepped)),
                ("инструменты +0,7 п.п. RWA якоря", dict(t2_shift=0.007)), ("инструменты -0,7 п.п.", dict(t2_shift=-0.007)),
                ("выплата 20 %", dict(payout=0.20)), ("выплата 30 %", dict(payout=0.30)),
                ("уровни ЧПМ / CoR / C/I сразу (10,75 / 5,5 / 47)", dict(levels_now=True)),
                ("CoR +1 п.п. весь путь", dict(cor_shift=0.01)),
                ("премия роста -5 п.п.", dict(prem_shift=-0.05)), ("премия роста +5 п.п.", dict(prem_shift=0.05)),
                ("порядок growth_first", dict(order="growth_first"))]
    for name, kw in variants:
        r = [name] + [cell(simulate("H", s, **kw)) for s in ("schedule", "mid", "strict")]
        tab.append(r); P(" | ".join(r))
    wcsv("p5_trial_sensitivity.csv", hdr, tab)

    P("")
    P("  порог запаса: требование с глиссадой (H = 8, delta = 0,25) в 3К2026 равно полу 2028 года + запас - 1,5 п.п.; оно выше факта 12,93 %% при запасе больше %.2f п.п. («по графику»)"
      % (N200[ANCH] - (12.0 - 1.5)))
    P("    и больше %.2f п.п. («средняя группа» и «жёсткий») - верх оси запаса (3,0) означает «группа уже сегодня ниже собственной цели»: рост 0 с первого квартала" % (N200[ANCH] - (12.5 - 1.5)))
    o = summary[("H", "mid")]["o"]
    q4 = [r["lam"] for r in o if r["q"] == 4 and 2027 <= r["y"] <= 2029]; qo = [r["lam"] for r in o if r["q"] != 4 and 2027 <= r["y"] <= 2029]
    P("  сезонность lambda (мир H x «средняя группа», 2027-2029): 4-й квартал %.2f, прочие кварталы %.2f - в 4-м квартале календарь книги вычитает два дивиденда (за 2К и 3К)"
      % (sum(q4) / len(q4), sum(qo) / len(qo)))

    # ---------------- 5.5 три замыкания
    P("")
    P("5.5. Три замыкания капитала, мир H (кредиты конца 2030 к потенциальным, %; дивиденды 2П2026-2030, млрд руб.; минимум Н20.0 - пол, п.п.; кварталов ниже пола)")
    hdr = ["замыкание", "schedule", "mid", "strict"]
    P(" | ".join(hdr))
    tab = []
    for name, kw in (("без ограничения (enabled: false)", dict(enabled=False)), ("dividend_first", {}), ("growth_first", dict(order="growth_first"))):
        r = [name]
        for s in ("schedule", "mid", "strict"):
            o = simulate("H", s, **kw)
            by = by_year(o)
            r.append("%s; дивиденды %.0f; запас к полу %+.2f; ниже пола %d" % (pct(by[2030]["level"]), sum(x["div"] for x in o if x["y"] <= 2030),
                                                                              100 * min(x["n20"] - x["floor20"] for x in o), sum(1 for x in o if x["below_floor"])))
        tab.append(r); P(" | ".join(r))
    wcsv("p5_trial_closures.csv", hdr, tab)
    return summary


DN_PATH = []

if __name__ == "__main__":
    import io, contextlib
    _silent = io.StringIO()
    # путь плотности ступенями - из части 2.4 (без повторной печати части 2)
    import cc_common
    save = cc_common._buf.getvalue()
    with contextlib.redirect_stdout(_silent):
        _, _, _, DN_PATH = p2_rwa.run()
    cc_common._buf.seek(0); cc_common._buf.truncate(0); cc_common._buf.write(save)
    run()
    flush("out_p5.txt")
