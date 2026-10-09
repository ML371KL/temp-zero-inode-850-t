# -*- coding: utf-8 -*-
"""Предложение ключей книги (форма шаблона Сбера) и узлов фактов capital.json - из тех же расчётов, что и отчёт.

Пишет book_keys_capital_proposal.yaml, facts_capital_proposal.json и out/keys_table.csv (ключ, значение, ось, источник для витрины, класс).
"""
import contextlib, io, json
from cc_common import *
import p2_rwa
import p3467_misc

DRIFT = 0.010          # центр capital.rwa.density_drift_rate [В: часть 2.4]
DRIFT_UNTIL = 2027
SRC805 = "ЦБ, ф. 0409805 на 01.07.2026 (cbr.ru/banking_sector/credit/coinfo/f805?regnum=2673&dt=202606), sha256 56dce7f18a7b0c3e"
SRC_IFRS = "primary/2026Q2_ifrs_fs.pdf, с. 6, sha256 fd08eacf4ed7e57c"


def trj(d):
    return "{" + ", ".join(('"%s": %s' % (k, ("%g" % v)) if k not in ("LT", "LT_from") else "%s: %s" % (k, ("%g" % v))) for k, v in d.items()) + "}"


def run():
    with contextlib.redirect_stdout(io.StringIO()):
        dens, rwa_b, bk, comp, add, f101, static_part = p2_rwa.anchor_densities(False)
    t = p3467_misc.scen_table()
    keys = {}
    for s in p3467_misc.SCEN:
        keys[s] = {"name": SCHED["scenarios"][s]["name"],
                   "conservation": p3467_misc.compress({y: t[s][y]["conservation"] / 100 for y in p3467_misc.YEARS}),
                   "sifi": p3467_misc.compress({y: t[s][y]["sifi"] / 100 for y in p3467_misc.YEARS}),
                   "ccyb": p3467_misc.compress({y: t[s][y]["ccyb"] / 100 for y in p3467_misc.YEARS}),
                   "ded": p3467_misc.compress({y: t[s][y]["deduction_pp"] / 100 for y in p3467_misc.YEARS})}
    ab = {r["book"]: r for r in rows("stage1/ifrs/anchor_books.csv")}
    debt_fvoci = ih("sec_fvoci")[ANCH] - ih("sec_fvoci_equity")[ANCH] + ih("repo_fvoci")[ANCH]
    fv_share = debt_fvoci / float(ab["securities"]["bal_" + ANCH])
    dl = ", ".join("%s: %.4f" % (k, dens[k]) for k in p2_rwa.KEYS) + ", other_assets_fixed: %.1f" % dens["other_assets_fixed"]
    ax_t2 = 0.007 * R0

    y = []
    y.append("# Предложение ключей книги Т 1.0: капитал, нормативы, RWA, ограничение роста (этап 1б, ключ calib-capital, 07.10.2026).")
    y.append("# Собрано make_keys.py из расчётов листа (руками не править). Форма - data/assumptions/assumptions_template.yaml Сбера.")
    y.append("# Класс: A - факт или расчёт по раскрытому; B - расчёт с суждением о составе; C - суждение. Ось - для unc.axes.")
    y.append("# Слоты ядра: n20_0 - Н20.0 банковской группы; n1_1 (n11) - Н20.1 банковской группы (оба - факт ЦБ, ф. 0409805).")
    y.append("")
    y.append("joint:")
    y.append("  reg_prob_given_regime:                                 # P(сценарий капитала | режим) [В: LEAD-2 §7 п. 5; опоры в данных нет] класс C")
    for r in ("soft", "norm", "downturn"):
        y.append("    %-9s {schedule: 0.35, mid: 0.45, strict: 0.20}" % (r + ":"))
    y.append("    crisis:   {schedule: 0.70, mid: 0.25, strict: 0.05}     # в кризисе антициклическая надбавка и макронадбавки распускаются")
    y.append("")
    y.append("oci:")
    y.append("  fvoci_share: anchor                                    # (долговые FVOCI 333,0 + в репо 13,9) / книга securities 745,8 = %.3f [Р: МСФО 6М26 с. 37-38] класс A" % fv_share)
    y.append("  fvoci_duration: 1.5                                    # эффективная дюрация к ОФЗ 3 г., лет [Р/В: 2,1 по трём кварталам из четырёх, 0,8-1,4 по году 2025]; ось 0,7-2,3; класс C")
    y.append("  fvoci_maturity: 3.0                                    # срок подтягивания к номиналу, лет [В: сроки бумаг не раскрыты]; ось 2-5; класс C")
    y.append("  fvoci_tenor: ofz_3y                                    # узел кривой мира [Р: к ОФЗ 3 г. оценка устойчивее, чем к 5 л.]; класс B")
    y.append("  fvtpl_bond_share: anchor                               # облигации по СС / книга securities: (ОФЗ + корпоративные FVTPL) / 745,8 [Р: МСФО 6М26 с. 38]")
    y.append("  fvtpl_bond_duration: null                              # не читается при other.fvtpl_bond_reval: false [нераскрыто]")
    y.append("")
    y.append("capital:")
    y.append("  minimum: {n20_0: 0.08, n1_1: 0.045}                    # минимум Н20.0 и Н20.1 группы [Ф: 220-И п. 2.2; 729-П] класс A")
    y.append("  mgmt_buffer: {n20_0: 0.015, n1_1: 0.015}               # запас менеджмента над минимумом сценария [В: LEAD-2 §7 п. 3] класс C; ось 0,5-3,0 п.п. (обе вместе)")
    y.append("                                                         #   ряд ф. 0409805 после Росбанка: 2,6-3,2 (Н20.0) и 2,7-3,8 (Н20.1) к действующему минимуму;")
    y.append("                                                         #   -0,4…+1,0 и -0,1…+1,2 к минимуму 2028 года (12,0 / 8,5); 2019-2021: 1,4-4,3 и 1,25-3,9 к полному минимуму")
    y.append("                                                         #   порог: при запасе выше 1,93 п.п. требование с глиссадой уже на якоре выше факта в «средней группе»")
    y.append("  reg_scenarios:                                         # надбавки по годам (с 1 января), доли RWA [Ф: 220-И пп. 3.2-3.4; В: 2028+] - stage1/regulation/schedule.yaml")
    y.append("    ids: [schedule, mid, strict]")
    for s in p3467_misc.SCEN:
        k = keys[s]
        y.append("    %s:" % s)
        y.append('      name: "%s"' % k["name"])
        y.append("      conservation: %s" % trj(k["conservation"]))
        y.append("      sifi: %s" % trj(k["sifi"]))
        y.append("      ccyb: %s" % trj(k["ccyb"]))
        y.append("      deduction_pp:")
        y.append("        n20_0: %s" % trj(k["ded"]))
        y.append("        n1_1: %s" % trj(k["ded"]))
    y.append("    # Пол Н20.0 = 8 % + надбавки: 10,0 (2026) -> 10,75 (2027) -> 12,0 / 12,5 / 12,5 (2028) -> 12,0 / 13,0 / 13,0 (2029) -> 12,0 / 13,0 / 13,5 (2030+);")
    y.append("    #   пол Н20.1 = 4,5 % + те же надбавки: 6,5 -> 7,25 -> 8,5 / 9,0 / 9,0 -> 8,5 / 9,5 / 9,5 -> 8,5 / 9,5 / 10,0 [Р]. Вычет «жёсткого» 0,3 п.п. с 2028 [В], ось 0-0,6.")
    y.append("  n20:                                                   # Н20.0 группы из BV - аддитивные вычеты, растущие с RWA (MODEL §4.11)")
    y.append("    deductions_anchor: %.3f                           # Ded20_0 = BVreg - (базовый + дополнительный капитал группы) = %.3f - %.3f [Р: МСФО 6М26 с. 6; ф. 0409805] класс A"
             % (DED20_0, BVREG0, CET1[ANCH] + T2[ANCH]))
    y.append("                                                         #   = %.2f %% RWA; пять дат после Росбанка 3,25-3,87 %%; состав: НМА 73,9, прочие вычеты 8,5, периметр и учёт 113,9, поправка фонда FVOCI 1,7"
             % (100 * DED20_0 / R0))
    y.append("    fvoci_recognition: %.2f                              # доля фонда FVOCI в нормативе = доля ОФЗ в долговых FVOCI 214,2 / 333,0 [В: состав фонда не раскрыт] класс C; ось 0,50-0,80" % F_REC)
    y.append("    t2: {LT: %.3f}                                     # регуляторные инструменты группы без прибыли = добавочный капитал [Ф: ф. 0409805 стр. 105] класс A; постоянные в рублях [В]"
             % T2_INSTR)
    y.append("                                                         #   ось «инструменты капитала»: сдвиг +-%.1f млрд руб. (+-0,7 п.п. RWA якоря) [В: LEAD-2 §7 п. 4]" % ax_t2)
    y.append("    gap_pp: 0.0                                          # «Н20.0 - расчёт» на якоре: 0 по построению [Р]; ось -0,3…+0,3 п.п. (ошибка формы на пяти датах: СКО 0,24) класс A")
    y.append("  n11:                                                   # Н20.1 группы (MODEL §4.11; слот n1_1)")
    y.append("    deductions_anchor: %.3f                           # Ded11_0 = BVreg - E_0 - базовый капитал группы = %.3f - %.3f - %.3f [Р] класс B (E - суждение о базисе)"
             % (DED11_0, BVREG0, E0, CET1[ANCH]))
    y.append("    gap_pp: %.5f                                      # Н20.1 - базовый / RWA(Н20.0): знаменатели Н20.1 и Н20.0 различаются на 64 млрд руб. [Р: ф. 0409805] класс A" % GAP11)
    y.append("    audit_cutoffs: [3, 4]                                # прибыль 9М входит в базовый капитал с формы на 01.12, года - с 01.04 [Ф: ф. 0409123: +56,1 и +32,9] класс A")
    y.append("  rwa:")
    y.append("    density: {%s}" % dl)
    y.append("                                                         # RWA группы / остаток книги МСФО; сумма = вменённые RWA группы %.1f [Р/В: разбивка RWA банка x 0,9929] класс B" % R0)
    y.append("                                                         #   розница: 145 % ссуд ФЛ ф. 101 с надбавками [Ф: презентация 2К26 с. 20]; надбавки по продуктам и веса бизнеса - [В]")
    y.append("    density_drift_rate: %.3f                            # [В] класс C: ступени операционного риска 4К (+30 / +22 / +15 %%) против надбавок (-2 %% в год) и" % DRIFT)
    y.append("                                                         #   постоянной части; история в форме ядра: -5,4 % за год до якоря (продажа портфелей и секьюритизация +127 млрд руб.)")
    y.append("                                                         #   ось листа -2,5…+3,5 % в год; ось LEAD-2 -4…+2 % - если программа продаж портфелей продолжится")
    y.append("    density_drift_until: %d                            # последний год дрейфа [В: к концу 2027 года индекс выходит на +1,5 %%; LEAD-2 §7 п. 6 - «до 2028»]" % DRIFT_UNTIL)
    y.append("    fx: {enabled: false, share: null, foreign_inflation: null}   # валютная переоценка RWA выключена: доля не раскрыта")
    y.append("  recapitalization: {enabled: false}")
    y.append("  growth_constraint:                                     # рост, ограниченный капиталом [В: LEAD-2 §5] класс C")
    y.append("    enabled: true")
    y.append("    order: dividend_first                                # цена порядка печатается: проба листа - дивиденды 2П2026-2030 286 против 157 млрд руб. при growth_first (мир H, mid)")
    y.append("    min_growth_scale: 0")
    y.append("    lookahead_quarters: 8                                # ступень 1,75 п.п. при 0,25 п.п. за квартал требует 7 кварталов; проба: H = 4…12 итог не меняет")
    y.append("    glide_pp_per_quarter: 0.0025                         # проба: при 0 требование нарушено на якоре (mid, strict); при 0,005 - срез дивиденда в 4К2027")
    y.append("    catch_up_rate: 0.25                                  # ось 0-0,5: уровень кредитов к потенциальному на конец 2032 (мир H, mid) 82 / 90 / 93 %")
    y.append("    tol: 0.0001")
    y.append("")
    y.append("regimes:")
    y.append("  crisis:")
    y.append('    rwa_density_mult: {"2027": 0.90, "2028": 0.933, "2029": 0.967, LT: 1.0, LT_from: 2030}')
    y.append("                                                         # роспуск макронадбавок: их доля в RWA банка 19,3 % [Ф: презентация 2К26 с. 20]; 0,90 = роспуск половины [В] класс C")
    y.append("                                                         #   ось: сдвиг -0,09…+0,10 на годы 2027-2029 (полный роспуск 0,81 … без роспуска 1,0)")
    y.append("")
    y.append("unc_axes_proposal:                                       # оси полосы по ключам листа (вид, пути, границы)")
    y.append('  - {name: "Запас менеджмента над минимумом", kind: value, paths: [capital.mgmt_buffer.n20_0, capital.mgmt_buffer.n1_1], low: 0.005, high: 0.030, dist: triangular, unit: pp}')
    y.append('  - {name: "Инструменты капитала", kind: shift, paths: [capital.n20.t2], low: %.1f, high: %.1f, dist: triangular, unit: bn}' % (-ax_t2, ax_t2))
    y.append('  - {name: "Дрейф плотности RWA до 2027", kind: value, paths: [capital.rwa.density_drift_rate], low: -0.025, high: 0.035, dist: triangular, unit: pct}   # LEAD-2: -0.04…+0.02')
    y.append('  - {name: "Поправка Н20.0 (мост МСФО - группа)", kind: value, paths: [capital.n20.gap_pp], low: -0.003, high: 0.003, dist: triangular, unit: pp}')
    y.append('  - {name: "Кризис: роспуск макронадбавок", kind: shift, paths: [regimes.crisis.rwa_density_mult], low: -0.09, high: 0.10, dist: triangular, unit: number}')
    y.append('  - {name: "Вычет «жёсткого» сценария", kind: value, paths: [capital.reg_scenarios.strict.deduction_pp.n20_0.2028, capital.reg_scenarios.strict.deduction_pp.n1_1.2028], low: 0.0, high: 0.006, dist: triangular, unit: pp}')
    y.append('  - {name: "Навёрстывание роста", kind: value, paths: [capital.growth_constraint.catch_up_rate], low: 0.0, high: 0.5, dist: triangular, unit: number}')
    y.append('  - {name: "Дюрация FVOCI", kind: value, paths: [oci.fvoci_duration], low: 0.7, high: 2.3, dist: triangular, unit: years}')
    y.append('  - {name: "Срок подтягивания FVOCI", kind: value, paths: [oci.fvoci_maturity], low: 2.0, high: 5.0, dist: triangular, unit: years}')
    y.append('  - {name: "Признание фонда FVOCI в нормативе", kind: value, paths: [capital.n20.fvoci_recognition], low: 0.50, high: 0.80, dist: triangular, unit: pct}')
    y.append("")
    y.append("checks_proposal:                                         # коридоры гейтов капитала [В: проба части 5; имена гейтов - за методикой]")
    y.append("  anchor_capital_tol: 0.0001                             # якорь: |Н20.0 расчёт - факт| и |Н20.1 расчёт - факт|, доли (условие калибровки)")
    y.append("  growth_cut:                                            # урезанный рост, клетки без шока")
    y.append("    level_2030_min: 0.65                                 # кредиты к потенциальному пути на конец 2030: проба 0,72-0,96 по девяти клеткам")
    y.append("    lambda_year_min: 0.40                                # средняя за год доля прироста: проба 0,54-1,00 (квартальная lambda в 4К ниже из-за двух вычетов дивиденда)")
    y.append("    zero_growth_quarters_max: 0                          # кварталов с lambda < 0,05 в модальной клетке")
    y.append("  step_quarter_dividend_cut: 0.0                         # срез дивиденда политики в 1К2027 и 1К2028, млрд руб. (аналитический тест): проба - 0 во всех девяти клетках")
    y.append("  capital_gap_mass_max: 0.0                              # масса клеток без шока с нормативом ниже пола: проба - 0 (минимум отчётного Н20.1 над полом +1,3 п.п.)")
    y.append("  n20_requirement_tol: 0.0001                            # урезанная клетка держит норматив на требовании")
    y.append("  estimate_before_f805: {n20_0: 0.003, n20_1: 0.002}     # допуск оценки «Н1.x банка + разность» против формы, доли (СКО 0,24 и 0,11 п.п.)")
    (OUT / "book_keys_capital_proposal.yaml").write_text("\n".join(y) + "\n", encoding="utf-8", newline="\n")
    yaml.safe_load("\n".join(y))                      # проверка разбора

    # ------------------------------------------------------------ факты
    def node(v, src=None, calc=None, basis=None):
        n = {"v": v}
        if src: n["src"] = src
        if calc: n["calc"] = calc
        if basis: n["basis"] = basis
        return n

    zc = {(r["quarter_end"], float(r["period_y"])): (float(r["yield_pct"]), r["tradedate"], r["tradetime"], r["sha256"]) for r in ZC}
    f135 = F135["2026-07-01"]
    hist = []
    bh = SCHED["current_state"]["buffer_history"]
    for d in ["2024-12-31"] + DATES:
        src = "ЦБ, ф. 0409805, %s, sha256 %s" % (F805[d]["url"], F805[d]["sha256"][:16])
        hist.append({"period": "%sQ%d" % (d[:4], int(d[5:7]) // 3), "date": d, "estimated": False,
                     "n20_0": node(N200[d] / 100, src, basis="банковская группа по ЦБ"), "n20_1": node(N201[d] / 100, src, basis="банковская группа по ЦБ"),
                     "n20_2": node(N202[d] / 100, src, basis="банковская группа по ЦБ"),
                     "capital_total": node(round(KTOT[d], 3), src), "base": node(round(CET1[d], 3), src), "additional": node(round(AT1[d], 3), src),
                     "tier2": node(round(T2[d], 3), src),
                     "rwa": node(round(RWA0[d], 1), calc="вменённые: капитал / Н20.0 (точность +-0,04 %)", basis="банковская группа по ЦБ"),
                     "min_n20_0_with_buffers": node(float(bh[d]["min_N20_0_ifrs"]) / 100, "МСФО, прим. «Управление капиталом» (stage1/regulation/schedule.yaml, check_ifrs)"),
                     "bv_shareholders": node(BV[d], "stage1/ifrs/ifrs_history.csv: eq_shareholders", basis="IFRS")})
    facts = {
        "basis": "mixed", "as_of": ANCH,
        "note": "у каждого блока свой basis: банковская группа по ЦБ (ф. 0409805), РСБУ банка (ф. 0409135 / 0409123 / 0409808), МСФО группы, Базель группы (примечание МСФО), рынок",
        "at1": {"basis": "IFRS",
                "amount": node(0.0, calc="в капитале МСФО бессрочных инструментов нет: займы 65,7 млрд руб. - в обязательствах (%s); регуляторные инструменты - узел t2_recognized" % SRC_IFRS),
                "coupon_annual": node(0.0, calc="проценты по бессрочным займам - в процентных расходах МСФО; купона из капитала нет"),
                "coupon_quarter": node(4, calc="формальное значение: купон равен 0")},
        "t2_recognized": node(round(T2_INSTR, 3), SRC805 + ", стр. 105",
                              calc="регуляторные инструменты группы без прибыли = добавочный капитал; дополнительный капитал 69,495 - неаудированная прибыль (в BV)", basis="банковская группа по ЦБ"),
        "basel": {"basis": "банковская группа по ЦБ (слоты ядра; Базель МСФО - узел basel_ifrs)", "as_of": ANCH,
                  "cet1": node(round(CET1[ANCH] + T2[ANCH], 3), SRC805 + ", стр. 102 + 203", calc="базовый с прибылью периода: 490,971 + 69,495; BV - этот узел = вычет якоря без поправки фонда FVOCI"),
                  "rwa": node(round(R0, 1), calc="вменённые RWA группы: капитал 683,648 / Н20.0 12,93 %; к ним калиброваны плотности"),
                  "cet1_ratio": node(round((CET1[ANCH] + T2[ANCH]) / R0, 5), calc="basel.cet1 / basel.rwa"),
                  "total_ratio": node(N200[ANCH] / 100, SRC805)},
        "basel_ifrs": {"basis": "Basel (группа МСФО; примечание «Управление капиталом»)", "as_of": ANCH,
                       "cet1": node(ih("basel_cet1")[ANCH], "primary/2026Q2_ifrs_fs.pdf, с. 80"), "t1": node(ih("basel_t1")[ANCH], "primary/2026Q2_ifrs_fs.pdf, с. 80"),
                       "rwa": node(ih("basel_rwa")[ANCH], "primary/2026Q2_ifrs_fs.pdf, с. 80"),
                       "rwa_credit": node(ih("basel_rwa_credit")[ANCH], "primary/2026Q2_ifrs_fs.pdf, с. 80"), "rwa_market": node(ih("basel_rwa_market")[ANCH], "primary/2026Q2_ifrs_fs.pdf, с. 80"),
                       "rwa_operational": node(ih("basel_rwa_operational")[ANCH], "primary/2026Q2_ifrs_fs.pdf, с. 80"),
                       "note": "ядро не читает: периметр МСФО, НДУ в базовом капитале, пакет Яндекса в рыночном риске"},
        "n20_0": {"basis": "банковская группа по ЦБ (Н20.0)", "value": node(N200[ANCH] / 100, SRC805), "as_of": ANCH, "estimated": False, "pre_dividend": False,
                  "pre_dividend_note": "дивиденд холдинга из капитала банковской группы на отсечке не вычитается; объявленных и не вычтенных на 30.06.2026 нет",
                  "min_with_buffers": node(0.09999, "primary/2026Q2_ifrs_fs.pdf, с. 80")},
        "n1_1_bank": {"basis": "банковская группа по ЦБ (Н20.1; слот ядра n1_1_bank - LEAD-2 §7 п. 1)", "value": node(N201[ANCH] / 100, SRC805), "as_of": ANCH, "estimated": False},
        "n20_2": node(N202[ANCH] / 100, SRC805, basis="банковская группа по ЦБ"),
        "bank_base_capital": node(round(CET1[ANCH], 3), SRC805 + ", стр. 102", calc="базовый капитал ГРУППЫ (слот ядра для сверки Ded11_0)", basis="банковская группа по ЦБ"),
        "group_capital": {"basis": "банковская группа по ЦБ", "total": node(round(KTOT[ANCH], 3), SRC805 + ", стр. 000"), "base": node(round(CET1[ANCH], 3), SRC805 + ", стр. 102"),
                          "additional": node(round(AT1[ANCH], 3), SRC805 + ", стр. 105"), "tier2": node(round(T2[ANCH], 3), SRC805 + ", стр. 203")},
        "bank_solo": {"basis": "RAS", "as_of": "2026-07-01",
                      "n1_0": node(float(f135["n1_0_pct"]) / 100, "stage1/ras/cbr_f135_wide.csv, ф. 0409135 на 2026-07-01, sha256 %s" % f135["sha256"][:16]),
                      "n1_1": node(float(f135["n1_1_pct"]) / 100, "то же"), "n1_2": node(float(f135["n1_2_pct"]) / 100, "то же"),
                      "rwa_n1_0": node(5325.048, "stage1/ras/cbr_f808_bank.csv, ф. 0409808 на 2026-07-01, стр. 60.3"), "rwa_n1_1": node(5261.341, "там же, стр. 60.1"),
                      "rwa_by_risk": {"credit": node(3430.0, "primary/2026Q2_ifrs_presentation.pdf, с. 20 (слайд-картинка; research/facts/t_capital.csv)"), "market": node(172.0, "то же"),
                                      "operational": node(698.0, "то же"), "macro_addons": node(1026.0, "то же"), "retail_density": node(1.45, "то же")}},
        "n20_minus_n1": {"basis": "банковская группа по ЦБ минус РСБУ банка", "as_of": ANCH,
                         "n20_0": node(round(N200[ANCH] / 100 - float(f135["n1_0_pct"]) / 100, 5), calc="Н20.0 - Н1.0 на последнюю общую дату (правило оценки до выхода ф. 0409805)"),
                         "n20_1": node(round(N201[ANCH] / 100 - float(f135["n1_1_pct"]) / 100, 5), calc="Н20.1 - Н1.1 на последнюю общую дату")},
        "instruments": {"basis": "mixed",
                        "group_additional": node(round(AT1[ANCH], 3), SRC805 + ", стр. 105"),
                        "bank_instruments_gross": node(142.142, "stage1/ras/cbr_f808_bank.csv, стр. 30"), "bank_deductions": node(18.959, "там же, стр. 43"),
                        "ifrs_perpetual_loans": node(65.7, SRC_IFRS, basis="IFRS (в обязательствах, в долларах США)"),
                        "intragroup": node(round(142.142 - 65.7, 1), calc="инструменты банка до вычетов - бессрочные займы МСФО: оценка внутригрупповых; прямого раскрытия нет"),
                        "calls": [{"instrument": "бессрочные облигации 600 млн долл., купон 6,00 %", "call_from": "2026-12-20", "src": "primary/FY2025_ifrs_fs.pdf, с. 78"},
                                  {"instrument": "бессрочные облигации 300 млн долл., купон 11,26 %", "call_from": "2027-09-15", "src": "primary/FY2025_ifrs_fs.pdf, с. 78"}]},
        "fvoci_reserve": node(RFV[ANCH], "primary/2026Q2_ifrs_fs.pdf (stage1/ifrs/ifrs_history.csv: orf_fvoci)", calc="после налога; = balance.equity.fvoci_reserve", basis="IFRS"),
        "ac_securities_hidden_loss": node(round(ih("sec_ac")[ANCH] - sum(ih("sec_ac_fair_value_l%d" % i)[ANCH] for i in (1, 2, 3)), 1), "primary/2026Q2_ifrs_fs.pdf, с. 37 и 85",
                                          calc="балансовая 377,8 - справедливая 346,3; в капитал и нормативы не входит; ядро не читает", basis="IFRS"),
        "ofz_curve_anchor": {"basis": "market", "as_of": ANCH, "convention": "бескупонная доходность ОФЗ (КБД MOEX), годовое начисление, доли"},
        "history": hist,
    }
    for k in (1.0, 3.0, 5.0, 10.0):
        v, td, tt, sha = zc[(ANCH, k)]
        facts["ofz_curve_anchor"][str(int(k))] = node(round(v / 100, 6), "MOEX ISS zcyc %s %s, yearyields, sha256 %s" % (td, tt, sha[:16]))
    (OUT / "facts_capital_proposal.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")

    # ------------------------------------------------------------ таблица ключей для отчёта
    tab = [
        ("capital.minimum.n20_0", "0.08", "—", "Минимум Н20.0: Инструкция ЦБ 220-И, п. 2.2", "A"),
        ("capital.minimum.n1_1", "0.045", "—", "Минимум Н20.1: Инструкция ЦБ 220-И, п. 2.2", "A"),
        ("capital.mgmt_buffer.n20_0", "0.015", "0.005…0.030", "Суждение: ряд ЦБ ф. 0409805 читается двояко (2,9 и 0,3 п.п.)", "C"),
        ("capital.mgmt_buffer.n1_1", "0.015", "0.005…0.030", "Суждение: тот же запас к Н20.1 (ряд 3,3 и 0,7 п.п.)", "C"),
        ("capital.reg_scenarios.*.conservation", trj(keys["schedule"]["conservation"]), "—", "Надбавка поддержания: 220-И, п. 3.2", "A"),
        ("capital.reg_scenarios.schedule.sifi", trj(keys["schedule"]["sifi"]), "—", "Надбавка СЗКО по графику: 220-И, п. 3.4", "A"),
        ("capital.reg_scenarios.mid.sifi", trj(keys["mid"]["sifi"]), "—", "Суждение: средняя группа СЗКО, 1,5 % с 2029 (доклад ЦБ 22.05.2025)", "C"),
        ("capital.reg_scenarios.strict.sifi", trj(keys["strict"]["sifi"]), "—", "Суждение: 2,0 % с 2030 (доклад ЦБ 22.05.2025)", "C"),
        ("capital.reg_scenarios.schedule.ccyb", trj(keys["schedule"]["ccyb"]), "—", "Антициклическая надбавка 0,5 %: решение ЦБ 08.11.2024, 27.07.2026", "A"),
        ("capital.reg_scenarios.{mid,strict}.ccyb", trj(keys["mid"]["ccyb"]), "—", "Суждение: целевой уровень ЦБ 1 % с 2028 года", "C"),
        ("capital.reg_scenarios.strict.deduction_pp.{n20_0,n1_1}", trj(keys["strict"]["ded"]), "2028: 0…0.006", "Суждение: вычет 0,3 п.п. с 2028 (консолидация, иммобилизованные активы)", "C"),
        ("capital.n20.deductions_anchor", "%.3f" % DED20_0, "через gap_pp", "МСФО 6М2026 и ЦБ ф. 0409805: капитал акционеров минус капитал группы", "A"),
        ("capital.n20.fvoci_recognition", "%.2f" % F_REC, "0.50…0.80", "Доля ОФЗ в долговых бумагах FVOCI: МСФО 6М2026, с. 38", "C"),
        ("capital.n20.t2", "{LT: %.3f}" % T2_INSTR, "сдвиг ±%.1f" % ax_t2, "Добавочный капитал группы: ЦБ, ф. 0409805 на 01.07.2026", "A (уровень), C (траектория)"),
        ("capital.n20.gap_pp", "0.0", "−0.003…+0.003", "Расчёт равен Н20.0 12,93 % на якоре; ошибка формы на истории 0,24 п.п.", "A"),
        ("capital.n11.deductions_anchor", "%.3f" % DED11_0, "—", "Капитал акционеров минус прибыль 1П2026 минус базовый капитал группы", "B"),
        ("capital.n11.gap_pp", "%.5f" % GAP11, "—", "Н20.1 9,40 % минус базовый капитал / RWA: ЦБ, ф. 0409805", "A"),
        ("capital.n11.audit_cutoffs", "[3, 4]", "—", "Ступени базового капитала банка: ф. 0409123 на 01.12 и 01.04", "A"),
        ("capital.rwa.density", "{" + dl + "}", "через дрейф", "RWA банка по видам риска (презентация 2К2026) к вменённым RWA группы", "B"),
        ("capital.rwa.density_drift_rate", "%.3f" % DRIFT, "−0.025…+0.035 (LEAD-2: −0.04…+0.02)", "Суждение: ступени операционного риска против снижения макронадбавок", "C"),
        ("capital.rwa.density_drift_until", "%d" % DRIFT_UNTIL, "—", "Суждение: ступени операционного риска выравниваются к 2028 году", "C"),
        ("capital.growth_constraint.enabled / order", "true / dividend_first", "—", "Суждение: с ноября 2024 года компания платит и растёт на остаток", "C"),
        ("capital.growth_constraint.lookahead_quarters", "8", "—", "График минимумов 220-И известен на два года вперёд", "C"),
        ("capital.growth_constraint.glide_pp_per_quarter", "0.0025", "—", "Суждение: набор капитала под ступени по 0,25 п.п. за квартал", "C"),
        ("capital.growth_constraint.catch_up_rate", "0.25", "0…0.5", "Суждение: урезанный рост навёрстывается на четверть разрыва в год", "C"),
        ("capital.growth_constraint.{min_growth_scale, tol}", "0 / 0.0001", "—", "Техническое: портфель не сжимается; допуск норматива 1 б.п.", "—"),
        ("oci.fvoci_share", "anchor (%.3f)" % fv_share, "—", "Долговые бумаги FVOCI с заложенными / долговые бумаги: МСФО 6М2026", "A"),
        ("oci.fvoci_duration", "1.5", "0.7…2.3", "Переоценка FVOCI против сдвига ОФЗ 3 г. в 2025–2026 годах", "C"),
        ("oci.fvoci_maturity", "3.0", "2.0…5.0", "Суждение: сроки бумаг не раскрыты", "C"),
        ("oci.fvoci_tenor", "ofz_3y", "—", "Переоценка FVOCI против сдвига ОФЗ 3 г. в 2025–2026 годах", "B"),
        ("regimes.crisis.rwa_density_mult", '{"2027": 0.90, "2028": 0.933, "2029": 0.967, LT: 1.0, LT_from: 2030}', "сдвиг −0.09…+0.10", "Макронадбавки — 19,3 % RWA банка; роспуск половины в год шока", "C"),
        ("joint.reg_prob_given_regime", "0.35 / 0.45 / 0.20; crisis 0.70 / 0.25 / 0.05", "смесь обратного расчёта", "Суждение ведущего: надбавка СЗКО и антициклическая надбавка 2028+", "C"),
    ]
    for r in tab:
        assert len(r[3]) <= 80, (r[0], len(r[3]))
    wcsv("keys_table.csv", ["ключ", "значение", "ось", "источник для витрины (до 80 знаков)", "класс"], tab)
    return tab


if __name__ == "__main__":
    t = run()
    print("ключей в таблице:", len(t))
