# -*- coding: utf-8 -*-
"""Часть 1. Мост «капитал акционеров МСФО -> капитал банковской группы» в форме ядра; приёмка на ряде ф. 0409805."""
from cc_common import *


def run():
    P("=" * 110)
    P("ЧАСТЬ 1. МОСТ «КАПИТАЛ АКЦИОНЕРОВ МСФО -> КАПИТАЛ БАНКОВСКОЙ ГРУППЫ» В ФОРМЕ ЯДРА")
    P("=" * 110)
    P("Источники: МСФО - stage1/ifrs/ifrs_history.csv (eq_shareholders, orf_fvoci, op_capital), ifrs_quarterly.csv (op_np,")
    P("  np_shareholders, eqf_dividends__shareholders); банковская группа - stage1/ras/group_f805.csv (ф. 0409805);")
    P("  прибыль группы - ф. 0409803 (bridge_ifrs_to_group_capital.csv, строка B6); банк - cbr_f123_wide.csv.")
    P("  RWA группы - вменённые: капитал / Н20.0 (точность +-0,04 % RWA).")
    P("")
    P("1.1. Ряд фактов, млрд руб.")
    hdr = ["дата", "BV МСФО", "фонд FVOCI", "базовый", "добавочный", "дополнит.", "капитал", "Н20.0", "Н20.1", "RWA(Н20.0)", "RWA(Н20.1)",
           "E опер. [3,4]", "E отчётн.", "приб. группы 803 YTD", "доп.кап/E опер."]
    P(" | ".join(hdr))
    tab = []
    for d in DATES:
        r = [d, fmt(BV[d], 3), fmt(RFV[d], 3), fmt(CET1[d], 3), fmt(AT1[d], 3), fmt(T2[d], 3), fmt(KTOT[d], 3), fmt(N200[d], 2), fmt(N201[d], 2),
             fmt(RWA0[d], 1), fmt(RWA1[d], 1), fmt(EOP[d], 3), fmt(ERP[d], 3), fmt(GP_YTD[d], 3), fmt(T2[d] / EOP[d], 3)]
        tab.append(r)
        P(" | ".join(r))
    wcsv("p1_facts_series.csv", hdr, tab)

    # ------------------------------------------------------------ 1.2
    P("")
    P("1.2. Параметры ядра на якоре 30.06.2026 [Р]")
    P("  BV (капитал акционеров МСФО)                 = %.3f   [Ф: МСФО 6М2026, с. 6; ifrs_history eq_shareholders]" % BV[ANCH])
    P("  фонд FVOCI R_0 (после налога)                = %.3f   [Ф: ifrs_history orf_fvoci]" % RFV[ANCH])
    P("  fvoci_recognition f                          = %.2f    [В: часть 6]" % F_REC)
    P("  BVreg_0 = BV - (1 - f) * R_0 + DPreg_0       = %.3f   (DPreg_0 = %.1f)" % (BVREG0, DPREG0))
    P("  капитал группы K_0 (ф. 805, стр. 000)        = %.3f; базовый %.3f; добавочный %.3f; дополнительный %.3f" % (KTOT[ANCH], CET1[ANCH], AT1[ANCH], T2[ANCH]))
    P("  RWA_0 = K_0 / Н20.0                           = %.1f    (по Н20.1: %.1f; отношение %.4f)" % (R0, RWA1[ANCH], RWA1[ANCH] / R0))
    P("  capital.n20.t2 (инструменты без прибыли)     = %.3f   = %.2f %% RWA_0 [Ф: добавочный капитал группы, ф. 805 стр. 105;" % (T2_INSTR, 100 * T2_INSTR / R0))
    P("      дополнительный капитал 69,495 - неаудированная прибыль, она уже в BV]")
    P("  capital.n20.deductions_anchor Ded20_0        = BVreg_0 + t2 - K_0 = %.3f = %.3f %% RWA_0" % (DED20_0, 100 * DED20_0 / R0))
    P("  capital.n20.gap_pp                           = %.4f (расчёт равен факту по построению: Н20.0 = %.4f %%)" % (GAP20, 100 * ((BVREG0 - DED20_0 + T2_INSTR) / R0 + GAP20)))
    P("  E_0 = операционная прибыль акционеров 1П2026 = %.3f  [Ф: Databook PL!37; календарь аудитов [3, 4]]" % E0)
    P("  capital.n11.gap_pp = Н20.1 - базовый / RWA_0  = %+.5f (%.3f п.п.; Н20.1 раскрыт до 0,01 п.п. -> точность +-0,005 п.п.)" % (GAP11, 100 * GAP11))
    P("  capital.n11.deductions_anchor Ded11_0        = BVreg_0 - E_0 - базовый = %.3f = %.3f %% RWA_0" % (DED11_0, 100 * DED11_0 / R0))
    P("  проверка: Н20.1 расчёт = %.4f %% (факт 9,40)" % (100 * ((BVREG0 - E0 - DED11_0) / R0 + GAP11)))
    P("  справочно, без поправки на фонд FVOCI (f = 1): Ded20_0 = %.3f; Ded11_0 = %.3f; при E_0 = отчётная прибыль 83,1: Ded11_0 = %.3f"
      % (BV[ANCH] + T2_INSTR - KTOT[ANCH], BV[ANCH] - E0 - CET1[ANCH], BVREG0 - ERP[ANCH] - CET1[ANCH]))
    P("  состав разрыва BV - базовый = %.1f: неаудированная прибыль в счёте регулятора (дополнительный капитал) %.1f; вычет НМА %.1f [Ф: ф. 802; ф. 808 стр. 9];"
      % (BV[ANCH] - CET1[ANCH], T2[ANCH], float(BR["B5"][ANCH])))
    P("    прочие вычеты и фильтры %.1f [Р: остаток]; периметр и учёт %.1f [Р: остаток] (bridge_ifrs_to_group_capital.csv, строки M2-M4; BV там по Databook)"
      % (float(BR["M4"][ANCH]), float(BR["M2"][ANCH])))

    # ------------------------------------------------------------ 1.3
    def n20_static(d, bv, instr):
        bvreg = bv - (1 - F_REC) * RFV[d]
        return 100 * ((bvreg - DED20_0 * RWA0[d] / R0 + instr) / RWA0[d] + GAP20)

    def n11_static(d, bv, e, ded11_0):
        bvreg = bv - (1 - F_REC) * RFV[d]
        return 100 * ((bvreg - max(e, 0) - ded11_0 * RWA0[d] / R0) / RWA0[d] + GAP11)

    cum = {d: BV[d] - OPCAP[d] for d in DATES}                      # накопленные эффекты пакета Яндекса и долга под него в BV
    bvop = {d: BV[d] - (cum[d] - cum[ANCH]) for d in DATES}         # BV при эффектах пакета на уровне якоря (контур движка)

    P("")
    P("1.3. Приёмка Н20.0: форма ядра с параметрами якоря на датах 31.03.2025-30.06.2026 (уровни; BV - факт МСФО на дату)")
    P("  A - инструменты по факту даты (добавочный капитал группы - события фактов); B - инструменты постоянны (123,2, как в прогнозе ядра);")
    P("  C - как A, но BV на операционном контуре: BV - (накопленный эффект пакета Яндекса на дату - тот же эффект на якоре)")
    hdr = ["дата", "Н20.0 факт", "A расчёт", "A ошибка", "B расчёт", "B ошибка", "C расчёт", "C ошибка", "Ded20 факт, % RWA", "(BV - капитал)/RWA, %", "эффект пакета в BV"]
    P(" | ".join(hdr))
    tab, errA, errB, errC = [], [], [], []
    for d in DATES:
        a = n20_static(d, BV[d], AT1[d])
        b = n20_static(d, BV[d], T2_INSTR)
        c = n20_static(d, bvop[d], AT1[d])
        errA.append(a - N200[d]); errB.append(b - N200[d]); errC.append(c - N200[d])
        dedf = 100 * (BV[d] - (1 - F_REC) * RFV[d] - CET1[d] - T2[d]) / RWA0[d]
        r = [d, fmt(N200[d], 2), fmt(a, 2), f2(a - N200[d]), fmt(b, 2), f2(b - N200[d]), fmt(c, 2), f2(c - N200[d]), fmt(dedf, 3),
             fmt(100 * (BV[d] - KTOT[d]) / RWA0[d], 3), f2(cum[d], 1)]
        tab.append(r)
        P(" | ".join(r))
    wcsv("p1_n20_static.csv", hdr, tab)
    P("  A, 5 дат до якоря: " + stats(errA) + "; без 31.03.2025: " + stats(errA, True))
    P("  B, 5 дат до якоря: " + stats(errB) + "; без 31.03.2025: " + stats(errB, True))
    P("  C, 5 дат до якоря: " + stats(errC) + "; без 31.03.2025: " + stats(errC, True))
    P("  вычет на операционном контуре (операционный капитал эмитента - базовый - дополнительный), %% RWA: %s"
      % " / ".join("%.2f" % (100 * (OPCAP[d] - CET1[d] - T2[d]) / RWA0[d]) for d in DATES))
    # вариант D: дивиденд, объявленный до конца квартала с реестром после него (за 2К2025 - реестр 06.10.2025; за 3К2025 - 08.01.2026), прибавлен как DPreg
    dp = {"2025-09-30": -DIVQ["3Q2025"] * 3.5 / 6.8, "2025-12-31": -DIVQ["4Q2025"]}
    errD = [n20_static(d, BV[d] + dp.get(d, 0.0), AT1[d]) - N200[d] for d in DATES]
    P("  D - как A, но объявленный и не выплаченный на дату дивиденд (30.09.2025: %.1f; 31.12.2025: %.1f) прибавлен как DPreg: ошибки %s"
      % (dp["2025-09-30"], dp["2025-12-31"], " / ".join("%+.2f" % e for e in errD)))
    P("  порог приёмки 0,25 п.п.: A - вне порога: %s; B - вне порога: %s" % (
        ", ".join("%s (%+.2f)" % (d, e) for d, e in zip(DATES, errA) if abs(e) > 0.25) or "нет",
        ", ".join("%s (%+.2f)" % (d, e) for d, e in zip(DATES, errB) if abs(e) > 0.25) or "нет"))

    # ------------------------------------------------------------ 1.4
    def ded11_for(pi):
        return BVREG0 - pi * EOP[ANCH] - CET1[ANCH]

    eq1 = {d: OPNI[QLAB[d]] for d in DATES}     # прибыль одного квартала (отсечки [1,2,3,4])

    def fit_pi(dates):
        best = None
        for k in range(0, 151):
            pi = k / 100
            d11 = ded11_for(pi)
            sse = sum((n11_static(d, BV[d], pi * EOP[d], d11) - N201[d]) ** 2 for d in dates)
            if best is None or sse < best[1]:
                best = (pi, sse)
        return best[0]

    pi_fit5 = fit_pi(DATES[:-1])
    pi_fit3 = fit_pi(DATES[2:-1])
    P("")
    P("1.4. Приёмка Н20.1: варианты E (инструменты не участвуют). Порог 0,35 п.п.")
    P("  V1 - E = операционная прибыль МСФО, отсечки [3, 4] (форма ядра без новых ключей);")
    P("  V2 - то же с долей pi = %.3f (дополнительный капитал группы / E на якоре) - один дополнительный ключ;" % PI0)
    P("  V3 - E = дополнительный капитал группы по факту даты (предел точности любой записи E);")
    P("  V4 - отсечки [1, 2, 3, 4] (E = прибыль квартала); V5 - pi по МНК на пяти датах (%.2f); V6 - pi по МНК на трёх датах 30.09.2025-31.03.2026 (%.2f)" % (pi_fit5, pi_fit3))
    variants = [("V1", lambda d: EOP[d], DED11_0), ("V2", lambda d: PI0 * EOP[d], ded11_for(PI0)),
                ("V3", lambda d: T2[d], BVREG0 - T2[ANCH] - CET1[ANCH]),
                ("V4", lambda d: eq1[d], BVREG0 - eq1[ANCH] - CET1[ANCH]),
                ("V5", lambda d: pi_fit5 * EOP[d], ded11_for(pi_fit5)), ("V6", lambda d: pi_fit3 * EOP[d], ded11_for(pi_fit3))]
    hdr = ["дата", "Н20.1 факт"] + [v[0] + " ошибка" for v in variants] + ["E опер.", "pi0*E", "доп. капитал факт", "пила факт (доп.кап/RWA), п.п.", "пила V1 (E/RWA), п.п."]
    P(" | ".join(hdr))
    tab = []
    errs = {v[0]: [] for v in variants}
    for d in DATES:
        r = [d, fmt(N201[d], 2)]
        for name, fe, d11 in variants:
            e = n11_static(d, BV[d], fe(d), d11) - N201[d]
            errs[name].append(e)
            r.append(f2(e))
        r += [fmt(EOP[d], 1), fmt(PI0 * EOP[d], 1), fmt(T2[d], 1), fmt(100 * T2[d] / RWA0[d], 2), fmt(100 * EOP[d] / RWA0[d], 2)]
        tab.append(r)
        P(" | ".join(r))
    wcsv("p1_n11_static.csv", hdr, tab)
    for name, _, d11 in variants:
        out = [("%s (%+.2f)" % (d, e)) for d, e in zip(DATES, errs[name]) if abs(e) > 0.35]
        P("  %s: Ded11_0 = %.1f; %s; вне порога 0,35: %s" % (name, d11, stats(errs[name]), ", ".join(out) or "нет"))
    P("  доп. капитал / E опер. по датам: %s" % ", ".join("%s %.2f" % (QLAB[d], T2[d] / EOP[d]) for d in DATES))
    P("  Н20.1 с прибылью периода (капитал ограничения роста, LEAD-2 §5 п. 3) на якоре: V1 = %.2f %%; V2 = %.2f %%;"
      % (100 * ((BVREG0 - DED11_0) / R0 + GAP11), 100 * ((BVREG0 - ded11_for(PI0)) / R0 + GAP11)))
    P("    регуляторный аналог (базовый + дополнительный) / RWA + gap11 = %.2f %%; завышение V1 = %.2f п.п. = (1 - pi) * E_0 / RWA_0"
      % (100 * ((CET1[ANCH] + T2[ANCH]) / R0 + GAP11), 100 * (1 - PI0) * E0 / R0))
    P("  цена отказа от ключа доли (V1 против V2), отчётный Н20.1 ядра относительно регуляторного счёта при прибыли квартала ~52 и RWA ~5 300:")
    q = 52.0
    P("    3К (E = 9М): занижение на (1 - pi) * прибыль 3К / RWA = %.2f п.п.; 4К и 1К (E = квартал после аудита): завышение на (1 - pi) * (E_0 - квартал) / RWA = %.2f п.п."
      % (100 * (1 - PI0) * q / R0, 100 * (1 - PI0) * (E0 - q) / R0))

    # ------------------------------------------------------------ 1.5 потоки: прибыль и дивиденд 1:1
    P("")
    P("1.5. Потоки: «операционная прибыль - дивиденд МСФО - рост вычета, инструменты постоянны» против факта капитала группы")
    P("  K^_t = K_s + сумма (операционная прибыль - объявленный дивиденд) - (Ded20_0 / RWA_0) * (RWA_t - RWA_s); Н20.0^ = K^_t / RWA_t")
    ratio = DED20_0 / R0
    hdr = ["дата", "опер. прибыль кв.", "дивиденд МСФО кв.", "dRWA", "рост вычета", "dK факт (все уровни)", "в т.ч. инструменты", "dK расчёт", "ошибка кв., млрд", "ошибка кв., п.п."]
    P(" | ".join(hdr))
    tab = []
    flows = {}
    for i in range(1, len(DATES)):
        d, p = DATES[i], DATES[i - 1]
        ni = OPNI[QLAB[d]]
        dv = -DIVQ.get(QLAB[d], 0.0)
        drwa = RWA0[d] - RWA0[p]
        dk = KTOT[d] - KTOT[p]
        pred = ni - dv - ratio * drwa
        flows[d] = (ni, dv, drwa, dk, pred)
        r = [d, fmt(ni, 3), fmt(dv, 3), fmt(drwa, 1), fmt(ratio * drwa, 2), fmt(dk, 2), fmt(AT1[d] - AT1[p], 2), fmt(pred, 2), f2(pred - dk), f2(100 * (pred - dk) / RWA0[d])]
        tab.append(r)
        P(" | ".join(r))
    wcsv("p1_flows_quarterly.csv", hdr, tab)
    for start in (0, 1):
        s = DATES[start]
        P("  накопленно от %s:" % s)
        k = KTOT[s]
        for d in DATES[start + 1:]:
            ni, dv, drwa, dk, pred = flows[d]
            k += pred
            P("    %s: Н20.0 расчёт %.2f, факт %.2f, ошибка %+.2f п.п. (капитал расчёт %.1f, факт %.1f)" % (d, 100 * k / RWA0[d], N200[d], 100 * k / RWA0[d] - N200[d], k, KTOT[d]))
    for start, lab in ((1, "четыре квартала 3К2025-2К2026"), (0, "пять кварталов 2К2025-2К2026")):
        ds = DATES[start + 1:]
        ni = sum(flows[d][0] for d in ds); dv = sum(flows[d][1] for d in ds); drwa = sum(flows[d][2] for d in ds); dk = sum(flows[d][3] for d in ds)
        gp = sum(float(r["profit_group_f803_bn"]) for r in rows("stage1/ras/pnl_ifrs_vs_group_vs_bank_quarterly.csv") if r["period_end"] in ds)
        P("  %s: операционная прибыль %.1f; дивиденд МСФО %.1f; рост вычета %.1f; dK расчёт %.1f; dK факт %.1f (в т.ч. инструменты %+.1f);"
          % (lab, ni, dv, ratio * drwa, ni - dv - ratio * drwa, dk, AT1[ANCH] - AT1[DATES[start]]))
        P("     ошибка формы ядра %+.1f млрд = %+.2f п.п. RWA; без вычета дивиденда (форма «дивиденд холдинга капитал группы не трогает»): %+.1f млрд = %+.2f п.п."
          % (ni - dv - ratio * drwa - dk, 100 * (ni - dv - ratio * drwa - dk) / R0, ni - ratio * drwa - dk, 100 * (ni - ratio * drwa - dk) / R0))
        P("     куда ушла операционная прибыль: прибыль банковской группы (ф. 803) %.1f = %.0f %%; вне периметра %.1f, из них дивиденды %.1f, остаток %.1f; прирост инструментов %+.1f"
          % (gp, 100 * gp / ni, ni - gp, dv, ni - gp - dv, AT1[ANCH] - AT1[DATES[start]]))

    # ------------------------------------------------------------ 1.6 месяцы реестров
    P("")
    P("1.6. Базовый капитал банка в месяцы реестров (ф. 0409123, РСБУ банка) против дивиденда холдинга")
    recs = [("2025-05-16", "2025-05-01", "2025-06-01", 3.2), ("2025-07-17", "2025-07-01", "2025-08-01", 3.3), ("2025-10-06", "2025-10-01", "2025-11-01", 3.5),
            ("2026-01-08", "2026-01-01", "2026-02-01", 3.6), ("2026-05-25", "2026-05-01", "2026-06-01", 4.5), ("2026-08-10", "2026-08-01", "2026-09-01", 4.6)]
    nout = 2549.9   # акции в обращении на 30.06.2026, млн (2 682,7 - 132,8); для оценки суммы выплаты
    for rec, a, b, dps in recs:
        dc = (float(F123[b]["cet1_th"]) - float(F123[a]["cet1_th"])) / 1e6
        dk = (float(F123[b]["capital_total_th"]) - float(F123[a]["capital_total_th"])) / 1e6
        P("    реестр %s: DPS %.2f руб. (~%.1f млрд руб.); базовый капитал банка за месяц %+.2f; капитал банка %+.2f" % (rec, dps, dps * nout / 1000, dc, dk))
    P("  вывод: в месяцы реестров базовый капитал банка не падал на сумму дивиденда; годовой итог формы ядра верен, потому что прибыль вне периметра")
    P("  банковской группы за год примерно равна дивидендам холдинга (см. 1.5).")
