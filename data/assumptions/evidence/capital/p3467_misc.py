# -*- coding: utf-8 -*-
"""Части 3, 4, 6, 7: сценарии капитала из schedule.yaml; запас менеджмента (два чтения ряда ф. 0409805);
фонд FVOCI; правило оценки нормативов до выхода формы 0409805."""
import statistics as st
from cc_common import *

YEARS = [2026, 2027, 2028, 2029, 2030, 2031]
SCEN = ["schedule", "mid", "strict"]
MIN20, MIN11, MIN12 = 8.0, 4.5, 6.0


def scen_table():
    """Надбавки сценариев по годам из stage1/regulation/schedule.yaml (вариант фазировки gradual - центр листа регулирования)."""
    out = {}
    for s in SCEN:
        g = SCHED["schedule"][s]["gradual"]
        out[s] = {y: {k: float(g[y][k]) for k in ("conservation", "sifi", "ccyb", "deduction_pp")} for y in YEARS}
    return out


def compress(vals):
    """Словарь год -> значение (доли) в форме траектории книги: хвост повторов отбрасывается (после последнего года - последнее значение)."""
    ys = sorted(vals)
    last = len(ys) - 1
    while last > 0 and abs(vals[ys[last]] - vals[ys[last - 1]]) < 1e-12:
        last -= 1
    if last == 0:
        return {"LT": round(vals[ys[0]], 6)}
    return {str(y): round(vals[y], 6) for y in ys[:last + 1]}


def run3():
    P("")
    P("=" * 110)
    P("ЧАСТЬ 3. СЦЕНАРИИ КАПИТАЛА (stage1/regulation/schedule.yaml -> ключи capital.reg_scenarios.*)")
    P("=" * 110)
    t = scen_table()
    keys = {}
    hdr = ["сценарий", "год", "поддержания", "СЗКО", "антициклич.", "сумма надбавок", "пол Н20.0", "пол Н20.1", "пол Н20.2", "вычет, п.п.",
           "требование Н20.0 (пол + 1,5 + вычет)", "требование Н20.1"]
    P(" | ".join(hdr))
    tab = []
    for s in SCEN:
        for y in YEARS:
            v = t[s][y]
            add = v["conservation"] + v["sifi"] + v["ccyb"]
            r = [s, str(y), fmt(v["conservation"], 2), fmt(v["sifi"], 2), fmt(v["ccyb"], 2), fmt(add, 2), fmt(MIN20 + add, 2), fmt(MIN11 + add, 2), fmt(MIN12 + add, 2),
                 fmt(v["deduction_pp"], 2), fmt(MIN20 + add + 1.5 + v["deduction_pp"], 2), fmt(MIN11 + add + 1.5 + v["deduction_pp"], 2)]
            tab.append(r); P(" | ".join(r))
        keys[s] = {"name": SCHED["scenarios"][s]["name"],
                   "conservation": compress({y: t[s][y]["conservation"] / 100 for y in YEARS}),
                   "sifi": compress({y: t[s][y]["sifi"] / 100 for y in YEARS}),
                   "ccyb": compress({y: t[s][y]["ccyb"] / 100 for y in YEARS}),
                   "deduction_pp": {"n20_0": compress({y: t[s][y]["deduction_pp"] / 100 for y in YEARS}),
                                    "n1_1": compress({y: t[s][y]["deduction_pp"] / 100 for y in YEARS})}}
    wcsv("p3_floors.csv", hdr, tab)
    P("")
    P("  ключи (доли RWA; значение года действует с 1 января; после последнего года - последнее значение):")
    for s in SCEN:
        P("   %s: %s" % (s, keys[s]))
    P("  вероятности [В: LEAD-2 §7 п. 5]: soft / norm / downturn - schedule %.2f, mid %.2f, strict %.2f; crisis - %.2f / %.2f / %.2f"
      % (SCHED["scenarios"]["schedule"]["prob"], SCHED["scenarios"]["mid"]["prob"], SCHED["scenarios"]["strict"]["prob"],
         SCHED["scenarios"]["schedule"]["prob_in_crisis"], SCHED["scenarios"]["mid"]["prob_in_crisis"], SCHED["scenarios"]["strict"]["prob_in_crisis"]))
    ev = {y: sum(SCHED["scenarios"][s]["prob"] * (MIN20 + t[s][y]["conservation"] + t[s][y]["sifi"] + t[s][y]["ccyb"] + t[s][y]["deduction_pp"]) for s in SCEN) for y in YEARS}
    P("  ожидаемый пол Н20.0 с вычетом (веса 0,35 / 0,45 / 0,20): %s" % "; ".join("%d - %.2f" % (y, ev[y]) for y in YEARS))
    P("  сверка минимума с примечанием МСФО «Управление капиталом»: %s" % SCHED["check_ifrs"]["conclusion"])
    P("  фактическая антициклическая надбавка группы = 0,992-0,998 национальной (средневзвешенная по странам заёмщиков): пол 9,999 против 10,0 - в ключах не учитывается")
    return keys, t


def run4():
    P("")
    P("=" * 110)
    P("ЧАСТЬ 4. ЗАПАС МЕНЕДЖМЕНТА: ДВА ЧТЕНИЯ РЯДА ф. 0409805")
    P("=" * 110)
    bh = SCHED["current_state"]["buffer_history"]
    hdr = ["дата", "Н20.0", "мин. Н20.0 действ.", "чтение 1: к действ.", "чтение 2: к мин. 2028 (12,0)", "к мин. 2028 «средняя группа» (12,5)",
           "Н20.1", "мин. Н20.1 действ.", "чтение 1", "чтение 2: к 8,5", "Н20.1 с прибылью: (базовый + доп.) / RWA(Н20.1)", "то же к 8,5", "Н20.2", "к мин. 2028 (10,0)"]
    P(" | ".join(hdr))
    tab = []
    for d in ["2024-12-31"] + DATES:
        m20 = float(bh[d]["min_N20_0_ifrs"]); m11 = float(bh[d]["min_N20_1_implied"])
        n11p = 100 * (CET1[d] + T2[d]) / RWA1[d]
        r = [d, fmt(N200[d], 2), fmt(m20, 3), f2(N200[d] - m20), f2(N200[d] - 12.0), f2(N200[d] - 12.5), fmt(N201[d], 2), fmt(m11, 3), f2(N201[d] - m11), f2(N201[d] - 8.5),
             fmt(n11p, 2), f2(n11p - 8.5), fmt(N202[d], 2), f2(N202[d] - 10.0)]
        tab.append(r); P(" | ".join(r))
    wcsv("p4_buffer_readings.csv", hdr, tab)
    post = DATES
    r1_20 = [N200[d] - float(bh[d]["min_N20_0_ifrs"]) for d in post]; r2_20 = [N200[d] - 12.0 for d in post]
    r1_11 = [N201[d] - float(bh[d]["min_N20_1_implied"]) for d in post]; r2_11 = [N201[d] - 8.5 for d in post]
    P("  после Росбанка (6 дат): чтение 1 - Н20.0 %.2f…%.2f (среднее %.2f), Н20.1 %.2f…%.2f (среднее %.2f);"
      % (min(r1_20), max(r1_20), st.mean(r1_20), min(r1_11), max(r1_11), st.mean(r1_11)))
    P("                           чтение 2 - Н20.0 %+.2f…%+.2f (среднее %+.2f), Н20.1 %+.2f…%+.2f (среднее %+.2f)"
      % (min(r2_20), max(r2_20), st.mean(r2_20), min(r2_11), max(r2_11), st.mean(r2_11)))
    P("  середина между чтениями (средние): Н20.0 %.2f; Н20.1 %.2f -> центр 1,5 п.п. к обоим нормативам [В: LEAD-2 §7 п. 3]" % ((st.mean(r1_20) + st.mean(r2_20)) / 2, (st.mean(r1_11) + st.mean(r2_11)) / 2))
    P("")
    P("  История до Росбанка, 2018-2021 (ф. 0409805; базовые минимумы 8 / 4,5 / 6 %; полная надбавка поддержания того времени 2,5 % - по памяти исполнителя [НП: акт не снят];")
    P("  в 2018-2019 годах действующая надбавка была ниже полной на 0,25-0,625 п.п.; надбавки СЗКО у банка не было до 2022 года)")
    hdr = ["дата", "Н20.0", "над 8 %", "над 10,5 %", "Н20.1", "над 4,5 %", "над 7,0 %", "Н20.2", "над 8,5 %"]
    P(" | ".join(hdr))
    tab = []
    hist = [d for d in sorted(F805) if "2017-12-31" <= d <= "2021-09-30"]
    for d in hist:
        r = [d, fmt(N200[d], 2), f2(N200[d] - 8), f2(N200[d] - 10.5), fmt(N201[d], 2), f2(N201[d] - 4.5), f2(N201[d] - 7.0), fmt(N202[d], 2), f2(N202[d] - 8.5)]
        tab.append(r); P(" | ".join(r))
    wcsv("p4_buffer_history_2018_2021.csv", hdr, tab)
    x20 = [N200[d] - 10.5 for d in hist if d >= "2019-01-01"]; x11 = [N201[d] - 7.0 for d in hist if d >= "2019-01-01"]; x12 = [N202[d] - 8.5 for d in hist if d >= "2019-01-01"]
    P("  2019-2021 (11 дат), запас над минимумом с полной надбавкой 2,5 %%: Н20.0 %.2f…%.2f (медиана %.2f); Н20.1 %.2f…%.2f (медиана %.2f); Н20.2 %.2f…%.2f (медиана %.2f)"
      % (min(x20), max(x20), st.median(x20), min(x11), max(x11), st.median(x11), min(x12), max(x12), st.median(x12)))
    P("  нижняя точка - 30.06.2019: Н20.0 11,90 (над 10,5 - 1,40), Н20.1 8,25 (над 7,0 - 1,25), Н20.2 10,93; в июле 2019 года группа разместила акции на 300 млн долл.")
    P("  [Ф: research/t-history.md, строка 217] - уровень, при котором менеджмент привлёк капитал, а не край оси")
    return {"r1_20": r1_20, "r2_20": r2_20, "r1_11": r1_11, "r2_11": r2_11}


def run6():
    P("")
    P("=" * 110)
    P("ЧАСТЬ 6. ФОНД ПЕРЕОЦЕНКИ FVOCI")
    P("=" * 110)
    g = lambda m, d: ih(m).get(d)
    P("6.1. Состав портфелей на якоре 30.06.2026 (МСФО 6М2026, прим. 16, с. 37-38), млрд руб.")
    fv = g("sec_fvoci", ANCH); ofz = g("sec_fvoci_ofz", ANCH); corp = g("sec_fvoci_corp_bonds", ANCH); muni = g("sec_fvoci_muni", ANCH); eq = g("sec_fvoci_equity", ANCH)
    repo = g("repo_fvoci", ANCH)
    P("  FVOCI: %.1f, из них ОФЗ %.1f, корпоративные облигации %.1f, муниципальные %.1f, акции %.1f; заложено по репо ещё %.1f (состав не раскрыт)" % (fv, ofz, corp, muni, eq, repo))
    debt = fv - eq
    f_rec = ofz / debt
    P("  доля ОФЗ в долговых FVOCI: %.1f / %.1f = %.3f -> capital.n20.fvoci_recognition = 0,64 [В]: в норматив идёт переоценка ОФЗ (практика ЦБ - лист Сбера calib-capital, п. 7);" % (ofz, debt, f_rec))
    P("    доля ОФЗ в самом фонде не раскрыта; ось 0,50-0,80")
    ab = {r["book"]: r for r in rows("stage1/ifrs/anchor_books.csv")}
    secbook = float(ab["securities"]["bal_" + ANCH])
    share = (debt + repo) / secbook
    P("  oci.fvoci_share = (долговые FVOCI %.1f + в репо %.1f) / книга securities %.1f = %.3f" % (debt, repo, secbook, share))
    ac = g("sec_ac", ANCH); fair = g("sec_ac_fair_value_l1", ANCH) + g("sec_ac_fair_value_l2", ANCH) + g("sec_ac_fair_value_l3", ANCH)
    ac0 = g("sec_ac", "2025-12-31"); fair0 = g("sec_ac_fair_value_l1", "2025-12-31") + g("sec_ac_fair_value_l2", "2025-12-31") + g("sec_ac_fair_value_l3", "2025-12-31")
    P("  бумаги по АС: %.1f (ОФЗ %.1f, корпоративные %.1f, муниципальные %.1f); справедливая стоимость %.1f (уровни 1-3: %.1f / %.1f / %.1f; с. 85); скрытый убыток %.1f = %.1f %% балансовой"
      % (ac, g("sec_ac_ofz_gross", ANCH), g("sec_ac_corp_gross", ANCH), g("sec_ac_muni_gross", ANCH), fair, g("sec_ac_fair_value_l1", ANCH), g("sec_ac_fair_value_l2", ANCH),
         g("sec_ac_fair_value_l3", ANCH), ac - fair, 100 * (ac - fair) / ac))
    P("    на 31.12.2025: %.1f против %.1f, скрытый убыток %.1f" % (ac0, fair0, ac0 - fair0))
    P("    к капиталу: %.1f млрд руб. = %.1f %% капитала акционеров = %.2f п.п. RWA до налога (%.2f после налога 25 %%); в капитале МСФО и в нормативах его нет"
      % (ac - fair, 100 * (ac - fair) / BV[ANCH], 100 * (ac - fair) / R0, 100 * 0.75 * (ac - fair) / R0))
    P("")
    P("6.2. Эффективная дюрация фонда: изменение справедливой стоимости FVOCI за квартал против сдвига кривой ОФЗ (КБД на конец квартала, inputs/zcyc_quarter_ends_2024_2026.csv)")
    zc = {}
    for r in ZC:
        zc[(r["quarter_end"], float(r["period_y"]))] = float(r["yield_pct"])
    fvch = iq("oci_fvoci_fv_change_net"); ii = iq("ii_sec_fvoci")
    qs = [("1Q2025", "2024-12-31", "2025-03-31"), ("2Q2025", "2025-03-31", "2025-06-30"), ("3Q2025", "2025-06-30", "2025-09-30"), ("4Q2025", "2025-09-30", "2025-12-31"),
          ("1Q2026", "2025-12-31", "2026-03-31"), ("2Q2026", "2026-03-31", "2026-06-30")]
    known = {d: g("sec_fvoci", d) - g("sec_fvoci_equity", d) + g("repo_fvoci", d) for d in ("2025-12-31", "2026-03-31", "2026-06-30")}
    y_port = ii["2Q2026"] * 4 / ((known["2026-03-31"] + known["2026-06-30"]) / 2)
    P("  портфель на начало квартала: факт для 1К-2К2026; для 2025 года - оценка [Р]: проценты по FVOCI за квартал x 4 / доходность портфеля 2К2026 (%.1f %%)" % (100 * y_port))
    hdr = ["квартал", "изменение СС после налога", "до налога (25 %)", "портфель на начало", "в % портфеля", "сдвиг 1 г., п.п.", "сдвиг 3 г.", "сдвиг 5 л.", "D к 3 г.", "D к 5 л.", "D к 1 г."]
    P(" | ".join(hdr))
    tab = []; d3 = []; d5 = []
    for q, a, b in qs:
        ch = fvch[q] / 0.75
        port = known.get(a) or ii[q] * 4 / y_port
        dy = {k: zc[(b, k)] - zc[(a, k)] for k in (1.0, 3.0, 5.0)}
        pc = 100 * ch / port
        dd = {k: (-pc / dy[k] if abs(dy[k]) >= 0.2 else None) for k in dy}
        if dd[3.0] is not None: d3.append(dd[3.0])
        if dd[5.0] is not None: d5.append(dd[5.0])
        r = [q, f2(fvch[q], 2), f2(ch, 2), fmt(port, 1), f2(pc, 2), f2(dy[1.0], 2), f2(dy[3.0], 2), f2(dy[5.0], 2)] + [("%.2f" % dd[k] if dd[k] is not None else "—") for k in (3.0, 5.0, 1.0)]
        tab.append(r); P(" | ".join(r))
    wcsv("p6_fvoci_duration.csv", hdr, tab)
    P("  D к ОФЗ 3 г. (кварталы со сдвигом от 0,2 п.п.): %s -> медиана %.2f; к 5 л.: %s -> медиана %.2f" % (", ".join("%.2f" % x for x in d3), st.median(d3), ", ".join("%.2f" % x for x in d5), st.median(d5)))
    r24, r25 = RFV["2024-12-31"], RFV["2025-12-31"]
    P("  год 2025: фонд %.1f -> %.1f (%+.1f после налога); сдвиг ОФЗ 3 г. %+.2f п.п.; без подтягивания к номиналу D = %.2f; с подтягиванием за 3 года (треть фонда в год) D = %.2f"
      % (r24, r25, r25 - r24, zc[("2025-12-31", 3.0)] - zc[("2024-12-31", 3.0)],
         -(100 * (r25 - r24) / 0.75 / 340) / (zc[("2025-12-31", 3.0)] - zc[("2024-12-31", 3.0)]),
         -(100 * (r25 - r24 * (1 - 1 / 3)) / 0.75 / 340) / (zc[("2025-12-31", 3.0)] - zc[("2024-12-31", 3.0)])))
    P("  предложение [В]: oci.fvoci_tenor = ofz_3y; oci.fvoci_duration = 1,5 года (ось 0,7-2,3); oci.fvoci_maturity = 3 года (ось 2-5)")
    P("  масштаб: сдвиг кривой на 3 п.п. x D 1,5 x портфель %.0f x (1 - 0,25) = %.1f млрд руб. = %.2f п.п. RWA; с признанием 0,64 - %.2f п.п. Н20.0"
      % (known[ANCH], 0.03 * 1.5 * known[ANCH] * 0.75, 100 * 0.03 * 1.5 * known[ANCH] * 0.75 / R0, 100 * 0.64 * 0.03 * 1.5 * known[ANCH] * 0.75 / R0))
    P("  кривая на якоре (КБД 30.06.2026): 1 г. %.4f; 3 г. %.4f; 5 л. %.4f; 10 л. %.4f %%" % (zc[(ANCH, 1.0)], zc[(ANCH, 3.0)], zc[(ANCH, 5.0)], zc[(ANCH, 10.0)]))
    return {"share": share, "f_rec": f_rec, "zc": {k: zc[(ANCH, k)] for k in (1.0, 3.0, 5.0, 10.0)}}


def run7():
    P("")
    P("=" * 110)
    P("ЧАСТЬ 7. ОЦЕНКА Н20.x ДО ВЫХОДА ФОРМЫ 0409805: Н1.x БАНКА (ф. 0409135) + РАЗНОСТЬ")
    P("=" * 110)
    ds = sorted(N20N1)
    d0 = {d: float(N20N1[d]["d_0"]) for d in ds}; d1 = {d: float(N20N1[d]["d_1"]) for d in ds}

    def consecutive(a, b):
        ya, ma = int(a[:4]), int(a[5:7]); yb, mb = int(b[:4]), int(b[5:7])
        return (yb - ya) * 12 + (mb - ma) == 3

    hdr = ["дата", "Н20.0", "Н1.0", "разность", "ошибка правила «последняя разность»", "Н20.1", "Н1.1", "разность", "ошибка правила"]
    P(" | ".join(hdr))
    e0 = {}; e1 = {}; tab = []
    for i, d in enumerate(ds):
        p = ds[i - 1] if i > 0 else None
        ok = p is not None and consecutive(p, d)
        if ok:
            e0[d] = d0[d] - d0[p]; e1[d] = d1[d] - d1[p]
        if d >= "2024-12-31":
            r = [d, N20N1[d]["n20_0"], N20N1[d]["n1_0"], f2(d0[d], 3), (f2(e0[d], 3) if ok else "—"), N20N1[d]["n20_1"], N20N1[d]["n1_1"], f2(d1[d], 3), (f2(e1[d], 3) if ok else "—")]
            tab.append(r); P(" | ".join(r))
    wcsv("p7_estimate_rule.csv", hdr, tab)

    def rm(e, lo, hi, skip=()):
        x = [v for d, v in e.items() if lo <= d <= hi and d not in skip]
        return (sum(v * v for v in x) / len(x)) ** 0.5, max(abs(v) for v in x), len(x)

    for lab, lo, hi in (("после Росбанка, 30.06.2025-30.06.2026", "2025-06-30", "2026-06-30"), ("2018-2021", "2018-03-31", "2021-09-30"), ("2023-09-30-2024-12-31", "2023-09-30", "2024-12-31")):
        a = rm(e0, lo, hi); b = rm(e1, lo, hi)
        P("  правило «Н1.x + разность на последнюю общую дату», %s: Н20.0 - СКО %.2f, макс. %.2f (n = %d); Н20.1 - СКО %.2f, макс. %.2f (n = %d)" % (lab, a[0], a[1], a[2], b[0], b[1], b[2]))
    # правило «средняя разность четырёх последних дат» и «та же дата год назад» на окне после Росбанка
    post = [d for d in ds if d >= "2025-03-31"]
    P("  разности после Росбанка: Н20.0 - Н1.0: %s (среднее %+.2f, СКО %.2f); Н20.1 - Н1.1: %s (среднее %+.2f, СКО %.2f)"
      % (" / ".join("%+.2f" % d0[d] for d in post), st.mean(d0[d] for d in post), st.pstdev([d0[d] for d in post]),
         " / ".join("%+.2f" % d1[d] for d in post), st.mean(d1[d] for d in post), st.pstdev([d1[d] for d in post])))
    P("  дата 31.12: форма 0409123 / 0409135 банка на 1 января - до событий после отчётной даты, форма 0409805 группы - после (капитал банка на 01.01.2026: 619,2 по ф. 123")
    P("    против 606,1 по ф. 808): разность Н20.0 - Н1.0 на 31.12.2025 = %+.2f при %+.2f…%+.2f на прочих датах. Без переходов через 31.12: Н20.0 - СКО %.2f (n = %d)"
      % (d0["2025-12-31"], min(d0[d] for d in post if d != "2025-12-31"), max(d0[d] for d in post if d != "2025-12-31"),
         rm(e0, "2025-06-30", "2026-06-30", ("2025-12-31", "2026-03-31"))[0], rm(e0, "2025-06-30", "2026-06-30", ("2025-12-31", "2026-03-31"))[2]))
    m0 = st.mean(d0[d] for d in post if d != "2025-12-31"); m1 = st.mean(d1[d] for d in post)
    P("  правило для книги: Н20.1^ = Н1.1 + разность на последнюю общую дату (точность +-0,1-0,2 п.п.); Н20.0^ = Н1.0 + разность на последнюю общую дату, кроме оценки")
    P("    на 31.12 и первой оценки после неё: там разность - среднее прочих дат после Росбанка (%+.2f); ожидаемая точность Н20.0 +-0,3 п.п." % m0)
    last = max(F135)
    n10 = float(F135[last]["n1_0_pct"]); n11 = float(F135[last]["n1_1_pct"])
    P("  пример: последняя форма 0409135 - на %s: Н1.0 %.3f, Н1.1 %.3f -> оценка Н20.0 %.2f, Н20.1 %.2f (разности 30.06.2026: %+.3f и %+.3f); узел estimated: true"
      % (last, n10, n11, n10 + d0[ANCH], n11 + d1[ANCH], d0[ANCH], d1[ANCH]))
    return {"d0": d0[ANCH], "d1": d1[ANCH], "m0": m0, "m1": m1}


if __name__ == "__main__":
    run3(); run4(); run6(); run7()
    flush("out_p3467.txt")
