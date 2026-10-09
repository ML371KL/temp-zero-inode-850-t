# -*- coding: utf-8 -*-
"""Часть 2. RWA: плотности по книгам, история индекса плотности, дрейф, роспуск макронадбавок в кризис."""
import math
from cc_common import *

BOOKS = ["cards", "cash_loans", "auto", "mortgage", "sme_loans", "corp_loans"]
RETAIL = ["cards", "cash_loans", "auto", "mortgage"]
KEYS = BOOKS + ["securities", "liquidity", "other_assets"]

# --- суждения части 2 (все [В]; чем могут ошибаться - в отчёте) ---------------------------------
W_MORTGAGE_BASE = 0.45          # базовый вес ипотеки на рубль валового остатка МСФО (без макронадбавки)
ADDON_INTENSITY = {"nps": 7.8, "auto": 2.5, "mortgage": 1.4}   # макробуфер сектора, % портфеля на 01.07.2026 (ЦБ 27.07.2026) - пропорции
APRIORI_BUSINESS = {"sme_loans": 0.85, "corp_loans": 0.80}     # соотношение весов МСБ и корпоративных на рубль (уровень задаёт регрессия 2.2)
W_SEC_CREDIT = 0.10             # кредитный вес долговых бумаг: ОФЗ 0 %; прирост корпоративных облигаций 1П2026 (+213) прочий кредитный риск не поднял
W_LIQ = 0.03                    # деньги, счета в ЦБ, банки, обратное репо
APRIORI_NONRETAIL = {"sme_loans": 0.85, "corp_loans": 0.80, "securities": 0.50, "liquidity": 0.05, "other_assets": 0.35}   # только для варианта сравнения
FIXED_DENSITY = 0.0             # пакет Яндекса и ассоциированные - вне банковской группы
OP_STEPS = {2026: 0.30, 2027: 0.22, 2028: 0.15}     # ступень операционного риска в 4-м квартале
ADDON_TREND = -0.02             # изменение макронадбавок на рубль портфеля, в год
G_BOOK = {2026: 0.16, 2027: 0.16, 2028: 0.14}       # фактический рост книг для проекции (при постоянной плотности)
STATIC_PHI = 0.5                # доля роста книг, с которой растёт прочий кредитный риск вне ссуд бизнесу (за 6 кварталов не рос: 0; в длинном счёте: 1)


def form_date(d):
    y, m = int(d[:4]), int(d[5:7])
    return "%d-%02d-01" % ((y + 1, 1) if m == 12 else (y, m + 1))


def books_at(d):
    """Книги ядра на дату d по МСФО (валовые; Databook Credit и BS через research/facts/t_quarterly.csv; три последние даты бумаг - anchor_books.csv)."""
    g = lambda m: tq(m)[d]
    b = {"cards": g("loans.gross.credit_cards"), "cash_loans": g("loans.gross.cash_and_other"), "auto": g("loans.gross.auto"),
         "mortgage": g("loans.gross.mortgage"), "sme_loans": g("loans.gross.sme"),
         "corp_loans": g("loans.gross.corporate") + g("loans.gross.leasing") + g("loans.gross.fvtpl")}
    ab = {r["book"]: r for r in rows("stage1/ifrs/anchor_books.csv")}
    col = "bal_" + d
    yan = ih("yandex_stake_fv").get(d, 0.0)
    if col in ab["securities"]:
        sec = float(ab["securities"][col]); approx = False
    else:
        sec = g("bs.securities") - yan - 32.0          # приближение: без пакета Яндекса и ~32 прочих акций и паёв; бумаги в репо не добавлены
        approx = True
    liq = g("bs.cash") + g("bs.mandatory_reserves_cbr") + g("bs.due_from_banks")
    fixed = yan + g("bs.associates_jv")
    other = g("bs.total_assets") - g("loans.net.total") - sec - liq - fixed
    b.update({"securities": sec, "liquidity": liq, "other_assets": other, "other_assets_fixed": fixed})
    return b, approx


def anchor_densities(verbose=True):
    comp = {k: tcap("reg_rwa_%s_bn" % k) for k in ("credit", "market", "operational", "macro_addons", "total")}
    dens_pct = tcap("reg_rwa_density_retail_loans_pct")
    exact = tcap("reg_rwa_total_exact_bn")
    f101 = {}
    fx = {"loans_business_broad": {}, "securities_debt_501_505": {}, "interbank_placed": {}}
    for r in rows("stage1/ras/cbr_f101_agg.csv"):
        if r["row_kind"] == "derived" and isnum(r["closing_th_rub"]):
            if r["code"] == "loans_fl_gross":
                f101[r["form_date"]] = float(r["closing_th_rub"]) / 1e6
            elif r["code"] in fx:
                fx[r["code"]][r["form_date"]] = float(r["closing_th_rub"]) / 1e6
    if verbose:
        P("")
        P("=" * 110)
        P("ЧАСТЬ 2. RWA")
        P("=" * 110)
        P("2.1. RWA банка по видам риска (РСБУ банка; слайд «Капитал» презентаций МСФО: research/facts/t_capital.csv, reg_rwa_*) и чтение «плотности розницы»")
        P("  гипотеза [Р]: плотность розницы = (кредитный риск розничных ссуд + макронадбавки) / ссуды физлицам по ф. 0409101 (без просроченных, счёт 458)")
        hdr = ["дата", "всего", "кредитный", "рыночный", "операционный", "надбавки", "доля надбавок, %", "плотность розницы, %", "ссуды ФЛ ф.101",
               "розница без надбавок", "к ссудам ФЛ, %", "кредитный прочий", "операц./всего, %"]
        P(" | ".join(hdr))
        tab = []
        for d in sorted(comp["total"]):
            fl = f101.get(form_date(d))
            base = dens_pct[d] / 100 * fl - comp["macro_addons"][d]
            r = [d, fmt(comp["total"][d], 0), fmt(comp["credit"][d], 0), fmt(comp["market"][d], 0), fmt(comp["operational"][d], 0), fmt(comp["macro_addons"][d], 0),
                 fmt(100 * comp["macro_addons"][d] / comp["total"][d], 1), fmt(dens_pct[d], 0), fmt(fl, 1), fmt(base, 0), fmt(100 * base / fl, 1),
                 fmt(comp["credit"][d] - base, 0), fmt(100 * comp["operational"][d] / comp["total"][d], 1)]
            tab.append(r); P(" | ".join(r))
        wcsv("p2_bank_rwa_components.csv", hdr, tab)
        P("  розничные ссуды без надбавок = 101-104 % ссуд ФЛ на девяти датах: чтение устойчиво (точность: плотность раскрыта до 1 п.п. -> +-0,5 % ссуд ФЛ)")

    d = ANCH
    bank_total = exact[d]
    fl = f101[form_date(d)]
    retail_total = dens_pct[d] / 100 * fl
    addon = comp["macro_addons"][d]
    retail_base = retail_total - addon
    nonretail = comp["credit"][d] - retail_base
    bk, _ = books_at(d)
    nps = bk["cards"] + bk["cash_loans"]
    wsum = nps * ADDON_INTENSITY["nps"] + bk["auto"] * ADDON_INTENSITY["auto"] + bk["mortgage"] * ADDON_INTENSITY["mortgage"]
    add = {"cards": addon * bk["cards"] * ADDON_INTENSITY["nps"] / wsum, "cash_loans": addon * bk["cash_loans"] * ADDON_INTENSITY["nps"] / wsum,
           "auto": addon * bk["auto"] * ADDON_INTENSITY["auto"] / wsum, "mortgage": addon * bk["mortgage"] * ADDON_INTENSITY["mortgage"] / wsum}
    w_unsec = (retail_base - W_MORTGAGE_BASE * bk["mortgage"]) / (bk["cards"] + bk["cash_loans"] + bk["auto"])
    credit = {"cards": w_unsec * bk["cards"], "cash_loans": w_unsec * bk["cash_loans"], "auto": w_unsec * bk["auto"], "mortgage": W_MORTGAGE_BASE * bk["mortgage"]}

    # прочий кредитный риск = постоянная часть + вес x ссуды бизнесу (ф. 101): МНК по шести датам после Росбанка
    xs = [fx["loans_business_broad"][form_date(t)] for t in DATES]
    ys = [comp["credit"][t] - (dens_pct[t] / 100 * f101[form_date(t)] - comp["macro_addons"][t]) for t in DATES]
    mx, my = sum(xs) / 6, sum(ys) / 6
    sxx = sum((x - mx) ** 2 for x in xs)
    w_bus = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    c_static = my - w_bus * mx
    resid = [y - c_static - w_bus * x for x, y in zip(xs, ys)]
    se = (sum(e * e for e in resid) / 4) ** 0.5
    se_w = se / sxx ** 0.5
    business = w_bus * fx["loans_business_broad"][form_date(d)]
    apb = sum(APRIORI_BUSINESS[k] * bk[k] for k in APRIORI_BUSINESS)
    for k in APRIORI_BUSINESS:
        credit[k] = business * APRIORI_BUSINESS[k] * bk[k] / apb
    credit["securities"] = W_SEC_CREDIT * bk["securities"]
    credit["liquidity"] = W_LIQ * bk["liquidity"]
    credit["other_assets"] = nonretail - business - credit["securities"] - credit["liquidity"]
    static_part = nonretail - business

    market = {"other_assets": comp["market"][d]}
    opr = comp["operational"][d]

    def finish(cr):
        loans_cr = sum(cr[b] + add.get(b, 0.0) for b in BOOKS)
        op = {b: opr * (cr[b] + add.get(b, 0.0)) / loans_cr for b in BOOKS}
        raw = {k: cr[k] + add.get(k, 0.0) + market.get(k, 0.0) + op.get(k, 0.0) for k in KEYS}
        return op, raw

    op, raw = finish(credit)
    s_raw = sum(raw.values())
    k_bank = bank_total / s_raw                       # округление компонентов слайда к точному итогу ф. 808
    k_group = R0 / bank_total                         # RWA группы (вменённые) / RWA банка
    rwa_b = {k: raw[k] * k_bank * k_group for k in KEYS}
    dens = {k: rwa_b[k] / bk[k] for k in KEYS}
    dens["other_assets_fixed"] = FIXED_DENSITY
    if verbose:
        P("")
        P("2.2. Плотности на якоре 30.06.2026: разбивка банка, масштабированная к вменённым RWA группы")
        P("  RWA банка (ф. 808, стр. 60.3) %.1f; RWA группы %.1f; масштаб группа / банк %.4f; RWA по Базелю МСФО %.1f (другой базис: периметр МСФО, пакет Яндекса в рыночном риске)"
          % (bank_total, R0, k_group, ih("basel_rwa")[d]))
        P("  розница: (кредитный + надбавки) = %.0f %% x %.1f = %.1f; надбавки %.0f; без надбавок %.1f; прочий кредитный риск %.1f" % (dens_pct[d], fl, retail_total, addon, retail_base, nonretail))
        P("  [В] базовый вес ипотеки %.2f -> вес карт, наличных и авто без надбавок %.3f на рубль валового остатка МСФО" % (W_MORTGAGE_BASE, w_unsec))
        P("  [В] надбавки по продуктам - пропорционально макробуферу сектора на рубль портфеля (НПС %.1f : авто %.1f : ипотека %.1f): карты %.0f, наличные %.0f, авто %.0f, ипотека %.0f"
          % (ADDON_INTENSITY["nps"], ADDON_INTENSITY["auto"], ADDON_INTENSITY["mortgage"], add["cards"], add["cash_loans"], add["auto"], add["mortgage"]))
        P("  прочий кредитный риск по шести датам 31.03.2025-30.06.2026 [Р, МНК]: %.0f + %.3f x ссуды бизнесу по ф. 101 (ст. ош. веса %.3f, остатка %.0f млрд руб.)" % (c_static, w_bus, se_w, se))
        P("    ряды: ссуды бизнесу %s; прочий кредитный риск %s" % (" / ".join("%.0f" % x for x in xs), " / ".join("%.0f" % y for y in ys)))
        P("    ссуды бизнесу на якоре %.1f -> кредитный риск ссуд бизнесу %.1f; постоянная часть (бумаги, банки, прочие активы) %.1f"
          % (fx["loans_business_broad"][form_date(d)], business, static_part))
        P("    за год 30.06.2025-30.06.2026: ссуды бизнесу %+.0f, долговые бумаги %+.0f, межбанк %+.0f, прочий кредитный риск %+.0f"
          % (xs[5] - xs[1], fx["securities_debt_501_505"][form_date(d)] - fx["securities_debt_501_505"]["2025-07-01"],
             fx["interbank_placed"][form_date(d)] - fx["interbank_placed"]["2025-07-01"], ys[5] - ys[1]))
        P("  [В] МСБ и корпоративные делят кредитный риск ссуд бизнесу в отношении весов %s; бумаги - кредитный вес %.2f; ликвидность %.2f; остаток %.1f - на растущие прочие активы"
          % (APRIORI_BUSINESS, W_SEC_CREDIT, W_LIQ, credit["other_assets"]))
        P("  рыночный риск %.0f - на растущие прочие активы (за год +40 %% при росте долговых бумаг +32 %%, по кварталам с бумагами не связан); операционный %.0f - на кредитные книги пропорционально их кредитному риску с надбавками [В]" % (comp["market"][d], opr))
        hdr = ["книга", "остаток МСФО", "кредитный", "надбавки", "рыночный", "операционный", "RWA банка", "RWA группы", "плотность (ключ книги)", "без операционного"]
        P(" | ".join(hdr))
        tab = []
        for k in KEYS:
            r = [k, fmt(bk[k], 1), fmt(credit[k], 1), fmt(add.get(k, 0.0), 1), fmt(market.get(k, 0.0), 1), fmt(op.get(k, 0.0), 1), fmt(raw[k] * k_bank, 1),
                 fmt(rwa_b[k], 1), fmt(dens[k], 4), fmt((credit[k] + add.get(k, 0.0) + market.get(k, 0.0)) * k_bank * k_group / bk[k], 4)]
            tab.append(r); P(" | ".join(r))
        r = ["other_assets_fixed", fmt(bk["other_assets_fixed"], 1), "0.0", "0.0", "0.0", "0.0", "0.0", "0.0", fmt(FIXED_DENSITY, 4), "0.0000"]
        tab.append(r); P(" | ".join(r))
        tot = ["итого", fmt(sum(bk[k] for k in KEYS) + bk["other_assets_fixed"], 1), fmt(sum(credit.values()), 1), fmt(sum(add.values()), 1), fmt(sum(market.values()), 1),
               fmt(sum(op.values()), 1), fmt(s_raw * k_bank, 1), fmt(sum(rwa_b.values()), 1), "", ""]
        tab.append(tot); P(" | ".join(tot))
        wcsv("p2_density_anchor.csv", hdr, tab)
        loans_g = sum(bk[b] for b in BOOKS)
        P("  проверки: сумма RWA по книгам = %.1f (RWA_0 %.1f); RWA группы / валовые кредиты МСФО = %.1f %%; / чистые кредиты = %.1f %%; розничные книги: %.1f %% валового остатка МСФО"
          % (sum(rwa_b.values()), R0, 100 * R0 / loans_g, 100 * R0 / tq("loans.net.total")[d], 100 * sum(rwa_b[b] for b in RETAIL) / sum(bk[b] for b in RETAIL)))
        P("  прочие активы: растущая часть %.1f = активы %.1f - чистые кредиты %.1f - долговые бумаги %.1f - ликвидность %.1f - постоянные %.1f (пакет Яндекса %.1f + ассоциированные %.1f)"
          % (bk["other_assets"], tq("bs.total_assets")[d], tq("loans.net.total")[d], bk["securities"], bk["liquidity"], bk["other_assets_fixed"], ih("yandex_stake_fv")[d], tq("bs.associates_jv")[d]))
        P("    если узел фактов прочих активов определён иначе, плотность = %.1f млрд руб. RWA / остаток узла" % rwa_b["other_assets"])
        # варианты сравнения
        ap = sum(APRIORI_NONRETAIL[k] * bk[k] for k in APRIORI_NONRETAIL)
        scale_nr = nonretail / ap
        cr1 = dict(credit)
        for k in APRIORI_NONRETAIL:
            cr1[k] = APRIORI_NONRETAIL[k] * scale_nr * bk[k]
        _, raw1 = finish(cr1)
        P("  вариант сравнения 1 (прочий кредитный риск - априорные веса %s x общий масштаб %.3f, без регрессии):" % (APRIORI_NONRETAIL, scale_nr))
        P("    " + "; ".join("%s %.3f" % (k, raw1[k] * bank_total / sum(raw1.values()) * k_group / bk[k]) for k in KEYS))
        ap_all = {"cards": 1.0, "cash_loans": 1.0, "auto": 1.0, "mortgage": W_MORTGAGE_BASE}
        ap_all.update(APRIORI_NONRETAIL)
        sc = comp["credit"][d] / sum(ap_all[k] * bk[k] for k in ap_all)
        cr2 = {k: ap_all[k] * sc * bk[k] for k in ap_all}
        _, raw2 = finish(cr2)
        P("  вариант сравнения 2 (без чтения «145 %%»): априорные веса всех книг x единый масштаб %.3f к кредитному риску %.0f:" % (sc, comp["credit"][d]))
        P("    " + "; ".join("%s %.3f" % (k, raw2[k] * bank_total / sum(raw2.values()) * k_group / bk[k]) for k in KEYS))
    return dens, rwa_b, bk, comp, add, f101, static_part * k_bank


def run():
    dens, rwa_b, bk0, comp, add, f101, static_part = anchor_densities(True)

    # ------------------------------------------------------------ 2.3 история индекса плотности в форме ядра
    P("")
    P("2.3. История индекса плотности в форме ядра: Dn_t = RWA группы_t / сумма (плотность якоря x книга_t), Dn(якорь) = 1; прочие активы - по правилу ядра (доля якоря x кредиты)")
    hdr = ["дата", "RWA группы", "сумма плотность x книга", "Dn", "за квартал, %", "валовые кредиты", "RWA / кредиты, %", "надбавки / (НПС + авто), %",
           "операц. / кредиты, %", "кредитный риск / кредиты, %", "бумаги - приближение"]
    P(" | ".join(hdr))
    tab = []; dn = {}
    oa_ratio = bk0["other_assets"] / sum(bk0[k] for k in BOOKS)
    for d in DATES:
        b, approx = books_at(d)
        loans_t = sum(b[k] for k in BOOKS)
        b["other_assets"] = oa_ratio * loans_t          # правило ядра: прочие активы = доля якоря x кредиты
        m = sum(dens[k] * b[k] for k in KEYS)
        dn[d] = RWA0[d] / m
        loans = sum(b[k] for k in BOOKS)
        prev = DATES[DATES.index(d) - 1] if d != DATES[0] else None
        r = [d, fmt(RWA0[d], 1), fmt(m, 1), fmt(dn[d], 4), (f2(100 * (dn[d] / dn[prev] - 1), 1) if prev else ""), fmt(loans, 1), fmt(100 * RWA0[d] / loans, 1),
             fmt(100 * comp["macro_addons"][d] / (b["cards"] + b["cash_loans"] + b["auto"]), 1), fmt(100 * comp["operational"][d] / loans, 1),
             fmt(100 * comp["credit"][d] / loans, 1), "да" if approx else "нет"]
        tab.append(r); P(" | ".join(r))
    wcsv("p2_density_index_history.csv", hdr, tab)
    P("  за четыре квартала 30.06.2025 -> 30.06.2026: Dn %+.1f %%; за 1П2026: %+.1f %% (%+.1f %% в годовом выражении); 4К2025: %+.1f %%"
      % (100 * (1 / dn["2025-06-30"] - 1), 100 * (1 / dn["2025-12-31"] - 1), 100 * ((1 / dn["2025-12-31"]) ** 2 - 1), 100 * (dn["2025-12-31"] / dn["2025-09-30"] - 1)))
    # разложение изменения за 4 квартала по видам риска банка
    d1, d0 = ANCH, "2025-06-30"
    b1, _ = books_at(d1); b0, _ = books_at(d0)
    ro1 = b1["cards"] + b1["cash_loans"] + b1["auto"]; ro0 = b0["cards"] + b0["cash_loans"] + b0["auto"]
    l1 = sum(b1[k] for k in BOOKS); l0 = sum(b0[k] for k in BOOKS)
    t1 = comp["total"][d1]
    P("  разложение за четыре квартала (RWA банка, доли итога якоря): макронадбавки на рубль НПС и авто %+.1f %% -> вклад %+.1f %%; операционный риск на рубль кредитов %+.1f %% -> вклад %+.1f %%;"
      % (100 * (comp["macro_addons"][d1] / ro1 / (comp["macro_addons"][d0] / ro0) - 1), 100 * (comp["macro_addons"][d1] - comp["macro_addons"][d0] * ro1 / ro0) / t1,
         100 * (comp["operational"][d1] / l1 / (comp["operational"][d0] / l0) - 1), 100 * (comp["operational"][d1] - comp["operational"][d0] * l1 / l0) / t1))
    P("    кредитный риск на рубль кредитов %+.1f %% (состав портфеля учитывают книги; внутри книг - остаток индекса)"
      % (100 * (comp["credit"][d1] / l1 / (comp["credit"][d0] / l0) - 1)))
    a0 = comp["macro_addons"]
    P("  макронадбавки по кварталам: %s" % "; ".join("%s %.0f" % (d, a0[d]) for d in sorted(a0)))
    P("  ступени операционного риска: 4К2024 %+.1f %% (307 -> 405); 1К2025 %+.1f %% (присоединение Росбанка); 4К2025 %+.1f %% (531 -> 690)"
      % (100 * (comp["operational"]["2024-12-31"] / comp["operational"]["2024-09-30"] - 1), 100 * (comp["operational"]["2025-03-31"] / comp["operational"]["2024-12-31"] - 1),
         100 * (comp["operational"]["2025-12-31"] / comp["operational"]["2025-09-30"] - 1)))

    # ------------------------------------------------------------ 2.4 проекция дрейфа
    P("")
    P("2.4. Проекция индекса плотности 2026-2028: ступени операционного риска против тренда надбавок [В]")
    S = static_part
    C = comp["credit"][ANCH] + comp["market"][ANCH] - S; A = comp["macro_addons"][ANCH]; O = comp["operational"][ANCH]
    tot0 = C + A + O + S

    def project(steps, addon_trend, g, phi=STATIC_PHI):
        """Dn в точках: 4К2026 (t = 0,5), 2К2027 (1,0), 4К2027 (1,5), 2К2028 (2,0), 4К2028 (2,5)."""
        out = {}
        G = 1.0; Gs = 1.0; op = O; t = 0.0
        for (y, half) in [(2026, 2), (2027, 1), (2027, 2), (2028, 1), (2028, 2)]:
            G *= (1 + g[y]) ** 0.5
            Gs *= (1 + phi * g[y]) ** 0.5
            t += 0.5
            if half == 2:
                op *= 1 + steps[y]
            real = C * G + A * G * (1 + addon_trend) ** t + op + S * Gs
            out[(y, half)] = real / (tot0 * G)
        return out

    def eq_rate(pr, until):
        pts = [(0.5, pr[(2026, 2)]), (1.5, pr[(2027, 2)])] + ([(2.5, pr[(2028, 2)])] if until >= 2028 else [])
        return math.exp(sum(t * math.log(v) for t, v in pts) / sum(t * t for t, _ in pts)) - 1

    base = project(OP_STEPS, ADDON_TREND, G_BOOK)
    P("  состав RWA банка на якоре: растущие с книгами (кредитный риск ссуд, рыночный) %.0f; макронадбавки %.0f; операционный %.0f; постоянная часть прочего кредитного риска %.0f"
      % (C, A, O, S))
    P("  центр: ступени операционного риска %s; надбавки на рубль портфеля %+.0f %% в год; рост книг %s; постоянная часть растёт с долей %.1f роста книг;"
      % (OP_STEPS, 100 * ADDON_TREND, G_BOOK, STATIC_PHI))
    P("    надбавка 250 % по секьюритизации с 15.10.2026 - 0 (эффект не раскрыт)")
    P("  Dn: 4К2026 %.4f; 2К2027 %.4f; 4К2027 %.4f; 2К2028 %.4f; 4К2028 %.4f" % tuple(base[k] for k in [(2026, 2), (2027, 1), (2027, 2), (2028, 1), (2028, 2)]))
    r27, r28 = eq_rate(base, 2027), eq_rate(base, 2028)
    P("  эквивалентная постоянная ставка дрейфа по точкам 4-го квартала: до 2027 - %+.2f %% в год; до 2028 - %+.2f %% в год" % (100 * r27, 100 * r28))
    hdr = ["вариант", "Dn 4К2026", "Dn 4К2027", "Dn 4К2028", "ставка до 2028, % в год"]
    P(" | ".join(hdr))
    tab = []
    lo_s = {2026: 0.20, 2027: 0.12, 2028: 0.10}; hi_s = {2026: 0.40, 2027: 0.32, 2028: 0.20}
    cases = [("центр", OP_STEPS, ADDON_TREND, G_BOOK, STATIC_PHI),
             ("ступени 20/12/10 %", lo_s, ADDON_TREND, G_BOOK, STATIC_PHI),
             ("ступени 40/32/20 %", hi_s, ADDON_TREND, G_BOOK, STATIC_PHI),
             ("надбавки без тренда", OP_STEPS, 0.0, G_BOOK, STATIC_PHI),
             ("надбавки -5 % в год", OP_STEPS, -0.05, G_BOOK, STATIC_PHI),
             ("надбавки -8,5 % в год (как 30.06.2025-30.06.2026)", OP_STEPS, -0.085, G_BOOK, STATIC_PHI),
             ("постоянная часть не растёт", OP_STEPS, ADDON_TREND, G_BOOK, 0.0),
             ("постоянная часть растёт с книгами", OP_STEPS, ADDON_TREND, G_BOOK, 1.0),
             ("рост книг 12 %", OP_STEPS, ADDON_TREND, {2026: 0.12, 2027: 0.12, 2028: 0.12}, STATIC_PHI),
             ("рост книг 20 %", OP_STEPS, ADDON_TREND, {2026: 0.20, 2027: 0.20, 2028: 0.20}, STATIC_PHI),
             ("низ: ступени 20/12/10, надбавки -8,5 %, постоянная часть не растёт", lo_s, -0.085, G_BOOK, 0.0),
             ("верх: ступени 40/32/20, надбавки 0, постоянная часть с книгами", hi_s, 0.0, G_BOOK, 1.0)]
    for name, st_, a, g, phi in cases:
        pr = project(st_, a, g, phi)
        r = [name, fmt(pr[(2026, 2)], 4), fmt(pr[(2027, 2)], 4), fmt(pr[(2028, 2)], 4), f2(100 * eq_rate(pr, 2028))]
        tab.append(r); P(" | ".join(r))
    wcsv("p2_drift_projection.csv", hdr, tab)
    sec_ub = float(SCHED["macro_addons"]["securitization"]["upper_bound_rwa_bn"])
    P("  секьюритизация: верхняя граница эффекта надбавки 250 %% - %.0f млрд руб. RWA = %+.1f %% RWA (stage1/regulation/schedule.yaml); в центр не входит"
      % (sec_ub, 100 * sec_ub / comp["total"][ANCH]))
    P("  цена: 1 %% плотности = %.2f п.п. Н20.0 на якоре (Н20.0 x 1 %%)" % (N200[ANCH] * 0.01))
    step = O * OP_STEPS[2026]
    P("  ступень 4К2026: +%.0f млрд руб. RWA = %+.1f %% RWA банка = %.2f п.п. Н20.0 одним кварталом"
      % (step, 100 * step / comp["total"][ANCH], N200[ANCH] * step / comp["total"][ANCH]))
    for rr in (0.01, 0.015, 0.02):
        P("    плавный дрейф %+.1f %% в год до 2027: Dn 4К2026 %.4f (проекция %.4f, разница в Н20.0 %+.2f п.п.); 4К2027 %.4f (%.4f, %+.2f); 4К2028 %.4f (%.4f, %+.2f); до 2028: 4К2028 %.4f (%+.2f)"
          % (100 * rr, (1 + rr) ** 0.5, base[(2026, 2)], N200[ANCH] * (base[(2026, 2)] / (1 + rr) ** 0.5 - 1),
             (1 + rr) ** 1.5, base[(2027, 2)], N200[ANCH] * (base[(2027, 2)] / (1 + rr) ** 1.5 - 1),
             (1 + rr) ** 1.5, base[(2028, 2)], N200[ANCH] * (base[(2028, 2)] / (1 + rr) ** 1.5 - 1),
             (1 + rr) ** 2.5, N200[ANCH] * (base[(2028, 2)] / (1 + rr) ** 2.5 - 1)))
    P("  путь множителя для записи ступени данными (квартальные ключи траектории rwa_density_mult при density_drift_rate = 0), центр:")
    G = 1.0; Gs = 1.0; opv = O; t = 0.0; path = []
    for (y, q) in [(2026, 3), (2026, 4), (2027, 1), (2027, 2), (2027, 3), (2027, 4), (2028, 1), (2028, 2), (2028, 3), (2028, 4)]:
        G *= (1 + G_BOOK[y]) ** 0.25; Gs *= (1 + STATIC_PHI * G_BOOK[y]) ** 0.25; t += 0.25
        if q == 4:
            opv *= 1 + OP_STEPS[y]
        path.append(("%dQ%d" % (y, q), (C * G + A * G * (1 + ADDON_TREND) ** t + opv + S * Gs) / (tot0 * G)))
    P("    " + "; ".join("%s %.3f" % p for p in path))

    # ------------------------------------------------------------ 2.5 кризис
    P("")
    P("2.5. Кризис: regimes.crisis.rwa_density_mult")
    sh = A / comp["total"][ANCH]
    P("  доля макронадбавок в RWA банка на якоре: %.1f %% (%.0f из %.0f)" % (100 * sh, A, comp["total"][ANCH]))
    for rel, name in ((1.0, "полный роспуск накопленного буфера (как 28.02.2022)"), (0.5, "роспуск половины (как в 2020 году: буфер по старым выдачам)"),
                      (0.0, "без роспуска")):
        m = 1 - sh * rel
        P("    %s: множитель %.3f; Н20.0 при прочих равных %+.2f п.п." % (name, m, N200[ANCH] * (1 / m - 1)))
    P("  история после роспуска 2022 года: доля надбавок в RWA банка 28-29 % к середине 2024 года (надбавки вернулись за 2-2,5 года после возврата с 01.07.2023)")
    P("  предложение: 0,90 в год шока, возврат к 1 линейно за три года: {2027: 0.90, 2028: 0.933, 2029: 0.967, LT: 1.0, LT_from: 2030}")
    return dens, rwa_b, r28, path


if __name__ == "__main__":
    run()
    flush("out_p2.txt")
