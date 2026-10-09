# -*- coding: utf-8 -*-
"""Шаг 2. Мост «упр. ↔ движок» на листах stage1/ifrs и определениях LEAD-2 §1 п. 6 (форма facts/bridge_mgmt_ifrs.json Сбера).
CoR движка = −строка резервов ОПУ × 365/d / средние валовые кредиты по АС с лизингом (без кредитов по СС);
ЧПМ движка = ЧПД × 365/d / средние процентные активы движка (шесть кредитных книг + долговые бумаги + ликвидность с кассой и резервами);
CIR движка = −расходы / (ЧПД + услуги + страхование + «прочее» на операционном базисе).
Читает stage1/ifrs/{ifrs_history,ifrs_quarterly,anchor_books}.csv, stage1/mgmt/mgmt_kpi.csv, op_basis_quarterly.csv (шаг 1).
Пишет out/bridge_quarterly.csv, out/bridge_stats.csv, out/bridge_mgmt_ifrs_proposal.json."""
import json
from pnl_lib import *
from s1_op_basis import rows as OP, Qd, q as fq

H = table(read_csv('stage1', 'ifrs', 'ifrs_history.csv'))
K = table(read_csv('stage1', 'mgmt', 'mgmt_kpi.csv'))
AB = {r['book']: r for r in read_csv('stage1', 'ifrs', 'anchor_books.csv')}
OPd = {r['period']: r for r in OP}
SEC_DEBT = {d: float(AB['securities'][f'bal_{d}']) for d in ('2025-12-31', '2026-03-31', '2026-06-30')}      # книга securities: только долговые бумаги (LEAD-2 §1 п. 6)


def bal(m, d):
    v = H.get(m, {}).get(d)
    return v[0] if v else None


def mk(p):                           # '2Q2026' → '2026Q2' (формат листа mgmt)
    y, h = qparts(p)
    return f"{y}Q{h}"


def ends(p):
    return qend(qprev(p)), qend(p)


def loans_ac(d):                     # валовые кредиты по АС с лизингом, без кредитов по СС
    return bal('loans_gross_incl_lease_fvtpl', d) - bal('loans_fvtpl', d)


def liq(d):                          # книга liquidity: деньги и эквиваленты (с кассой и счетами в ЦБ) + обязательные резервы + средства в банках
    return bal('cash', d) + bal('mandatory_reserves', d) + bal('due_from_banks', d)


def iea_b(d):                        # ряд на все кварталы: бумаги — «инвестиционный портфель без пакета Яндекса» (с прочими акциями и паями)
    return bal('loans_gross_incl_lease_fvtpl', d) + bal('invest_portfolio_ex_yandex', d) + liq(d)


def iea_a(d):                        # точное определение LEAD-2: бумаги — только долговые (есть на три даты)
    return bal('loans_gross_incl_lease_fvtpl', d) + SEC_DEBT[d] + liq(d) if d in SEC_DEBT else None


rows = []
for p in QS:
    d0, d1 = ends(p); dd = qdays(p); o = OPd[p]
    r = dict(period=p, days=dd)
    # --- CoR
    la = (loans_ac(d0) + loans_ac(d1)) / 2
    r['loans_ac_avg'] = la; r['llp_debt_fa'] = o['llp_debt_fa']
    r['cor_engine'] = -o['llp_debt_fa'] * 365 / dd / la
    r['cor_mgmt'] = K['cor_total_exact'][mk(p)][0] / 100
    r['cor_gap'] = r['cor_engine'] - r['cor_mgmt']
    num_m = fq('llp_loans_ex_poci', p)                                    # числитель CoR эмитента (со знаком отчёта)
    r['cor_gap_numerator'] = (-o['llp_debt_fa'] + num_m) * 365 / dd / la   # часть разрыва от числителя
    r['cor_gap_days_denominator'] = r['cor_gap'] - r['cor_gap_numerator']
    lc = fq('llp_loans_and_commitments', p)
    r['cor_engine_loans_line'] = (-lc * 365 / dd / la) if lc is not None else None       # вариант: строка «кредиты и обязательства кредитного характера» примечания
    # --- ЧПМ
    ib = (iea_b(d0) + iea_b(d1)) / 2
    r['iea_engine_avg_b'] = ib; r['nii'] = o['nii']
    r['nim_engine_b'] = o['nii'] * 365 / dd / ib
    r['nim_engine_b_x4'] = o['nii'] * 4 / ib
    ia = (iea_a(d0) + iea_a(d1)) / 2 if iea_a(d0) and iea_a(d1) else None
    r['iea_engine_avg_a'] = ia
    r['nim_engine_a'] = o['nii'] * 365 / dd / ia if ia else None
    r['nim_engine_a_x4'] = o['nii'] * 4 / ia if ia else None
    r['nim_mgmt'] = K['nim_exact'][mk(p)][0] / 100
    r['nim_mgmt_comparable'] = p != '1Q2024'                               # 1К2024: упр. ЧПМ посчитана на одном конце квартала
    r['nim_gap_b'] = r['nim_engine_b'] - r['nim_mgmt']
    r['nim_gap_days'] = r['nim_engine_b'] - r['nim_engine_b_x4']            # сезонная рябь счёта дней
    r['nim_gap_b_x4'] = r['nim_engine_b_x4'] - r['nim_mgmt']                # разрыв без ряби (обе стороны «× 4»)
    r['nim_gap_a'] = r['nim_engine_a'] - r['nim_mgmt'] if ia else None
    r['nim_gap_a_x4'] = r['nim_engine_a_x4'] - r['nim_mgmt'] if ia else None
    im0 = K['iea_mgmt'].get(mk(qprev(p))); im1 = K['iea_mgmt'].get(mk(p))
    r['iea_mgmt_end'] = im1[0] if im1 else None
    r['iea_ratio_b_end'] = im1[0] / iea_b(d1) if im1 else None             # состав: процентные активы эмитента / движка на конец квартала
    r['iea_ratio_a_end'] = im1[0] / iea_a(d1) if im1 and iea_a(d1) else None
    # --- CIR (операционный базис)
    inc = o['nii'] + o['fees'] + o['ins'] + o['misc_net']
    r['opex'] = o['opex']; r['income_engine_op'] = inc
    r['cir_engine'] = -o['opex'] / inc
    r['cir_mgmt'] = K['cir_exact'][mk(p)][0] / 100
    r['cir_gap'] = r['cir_engine'] - r['cir_mgmt']
    rows.append(r)
write_csv('bridge_quarterly.csv', rows)
R = {r['period']: r for r in rows}

WIN = {'окно B9: 4К2024–2К2026 (7)': B9, '1К2025–2К2026 (6)': QS[4:10], '3К2025–2К2026 (4)': QS[6:10], '1К2026–2К2026 (2)': QS[8:10], '2К2024–2К2026 (9)': QS[1:10]}


def slope(ys):
    n = len(ys); xm = (n - 1) / 2; ym = sum(ys) / n
    return sum((i - xm) * (y - ym) for i, y in enumerate(ys)) / sum((i - xm) ** 2 for i in range(n)) if n > 2 else float('nan')


stats = []
for x, key in (('cor', 'cor_gap'), ('nim: бумаги с акциями и паями, 365/d', 'nim_gap_b'), ('nim: то же без ряби дней (× 4)', 'nim_gap_b_x4'),
               ('nim: определение LEAD-2 (долговые бумаги), 365/d', 'nim_gap_a'), ('nim: определение LEAD-2 без ряби дней (× 4)', 'nim_gap_a_x4'), ('cir (операционный базис)', 'cir_gap')):
    for wn, ps in WIN.items():
        gs = [R[p][key] for p in ps if R[p][key] is not None and (not x.startswith('nim') or R[p]['nim_mgmt_comparable'])]
        if len(gs) < 2: continue
        m, s, n = mean_sd(gs)
        det = [g - (statistics.fmean(gs) + slope(gs) * (i - (n - 1) / 2)) for i, g in enumerate(gs)] if n > 3 else None
        stats.append(dict(x=x, window=wn, n=n, gap_mean_pp=m * 100, gap_sd_pp=s * 100, gap_min_pp=min(gs) * 100, gap_max_pp=max(gs) * 100, trend_pp_per_q=slope(gs) * 100,
                          sd_detrended_pp=(sum(e * e for e in det) / (n - 2)) ** 0.5 * 100 if det else None))
write_csv('bridge_stats.csv', stats)

if __name__ == '__main__':
    print('=' * 110)
    print('ШАГ 2. Мост упр. ↔ движок (проценты годовых; разрыв = движок − упр.)')
    print('квартал  d | CoR упр  движок  разрыв (числитель; дни и знаменатель) | ЧПМ упр  движок(b)  разрыв(b)  рябь дней  без ряби | движок(a) разрыв(a) без ряби(a) | состав b / a | CIR упр  движок  разрыв')
    f = lambda v, nd=2: '   — ' if v is None else f"{v * 100:6.{nd}f}"
    for r in rows:
        print(f"{r['period']} {r['days']} | {f(r['cor_mgmt'])} {f(r['cor_engine'])} {f(r['cor_gap'])} ({f(r['cor_gap_numerator'])}; {f(r['cor_gap_days_denominator'])}) | "
              f"{f(r['nim_mgmt'])}{'' if r['nim_mgmt_comparable'] else '*'} {f(r['nim_engine_b'])} {f(r['nim_gap_b'])} {f(r['nim_gap_days'])} {f(r['nim_gap_b_x4'])} | "
              f"{f(r['nim_engine_a'])} {f(r['nim_gap_a'])} {f(r['nim_gap_a_x4'])} | {'  —  ' if r['iea_ratio_b_end'] is None else format(r['iea_ratio_b_end'], '.4f')} / {'  —  ' if r['iea_ratio_a_end'] is None else format(r['iea_ratio_a_end'], '.4f')} | "
              f"{f(r['cir_mgmt'])} {f(r['cir_engine'])} {f(r['cir_gap'])}")
    print('  * упр. ЧПМ 1К2024 посчитана на одном конце квартала — из окон ЧПМ исключена')
    print()
    for s in stats:
        print(f"  {s['x']:52s} | {s['window']:28s} | среднее {s['gap_mean_pp']:+7.3f} п.п., σ {s['gap_sd_pp']:6.3f}, [{s['gap_min_pp']:+6.3f}; {s['gap_max_pp']:+6.3f}], тренд {s['trend_pp_per_q']:+6.3f} за квартал"
              + (f", σ без тренда {s['sd_detrended_pp']:.3f}" if s['sd_detrended_pp'] is not None else ''))
    # вариант числителя CoR
    print()
    print('CoR: вариант числителя «резерв по кредитам и обязательствам кредитного характера» (прим. 17; раскрыт за 4 квартала):')
    for p in QS:
        if R[p]['cor_engine_loans_line'] is not None:
            print(f"  {p}: {R[p]['cor_engine_loans_line'] * 100:.3f} % против {R[p]['cor_engine'] * 100:.3f} % по строке ОПУ (разность {(R[p]['cor_engine_loans_line'] - R[p]['cor_engine']) * 100:+.3f} п.п.)")
    # состав процентных активов на якоре
    d = '2026-06-30'
    print()
    print('Состав процентных активов на 30.06.2026, млрд ₽:')
    print(f"  движок (LEAD-2): кредиты {bal('loans_gross_incl_lease_fvtpl', d):.1f} + долговые бумаги {SEC_DEBT[d]:.1f} + ликвидность {liq(d):.1f} = {iea_a(d):.1f}")
    print(f"  эмитент: {K['iea_mgmt']['2026Q2'][0]:.1f} (Databook BS!AZ63); разность движок − эмитент = {iea_a(d) - K['iea_mgmt']['2026Q2'][0]:.1f}: "
          f"касса {bal('cash_on_hand', d):.1f} + счета в ЦБ {bal('cash_cbr_accounts', d):.1f} + обязательные резервы {bal('mandatory_reserves', d):.1f} − маржинальные кредиты (брокерская дебиторка) 110,9 − прочие акции и паи {bal('invest_portfolio_ex_yandex', d) - SEC_DEBT[d]:.1f}")
    for dd_ in ('2025-12-31', '2026-03-31', '2026-06-30'):
        print(f"  {dd_}: прочие акции и паи в «инвестиционном портфеле» эмитента = {bal('invest_portfolio_ex_yandex', dd_) - SEC_DEBT[dd_]:.1f}; касса + ЦБ + резервы = {bal('cash_on_hand', dd_) + bal('cash_cbr_accounts', dd_) + bal('mandatory_reserves', dd_):.1f}")
    # уровни B9 в базисе движка
    print()
    print('Средние окна B9 (семь кварталов 4К2024–2К2026):')
    for nm, km, ke in (('ЧПМ', 'nim_mgmt', 'nim_engine_b'), ('CoR', 'cor_mgmt', 'cor_engine'), ('C/I', 'cir_mgmt', 'cir_engine')):
        print(f"  {nm}: упр. {statistics.fmean(R[p][km] for p in B9) * 100:.3f} %; движок {statistics.fmean(R[p][ke] for p in B9) * 100:.3f} %")

    # ---------- предложение узла фактов
    def st(x, w):
        return next(s for s in stats if s['x'] == x and s['window'].startswith(w))
    cor7 = st('cor', 'окно B9'); cir7 = st('cir (операционный базис)', 'окно B9')
    nim_a = st('nim: определение LEAD-2 без ряби дней (× 4)', '1К2026'); nim_b7 = st('nim: то же без ряби дней (× 4)', 'окно B9'); nim_b4 = st('nim: то же без ряби дней (× 4)', '3К2025')
    nim_b7d = st('nim: бумаги с акциями и паями, 365/d', 'окно B9')
    print()
    print('ПРЕДЛОЖЕНИЕ значений моста (аддитивный, доли):')
    print(f"  cor.value = {cor7['gap_mean_pp'] / 100:+.6f} (σ {cor7['gap_sd_pp'] / 100:.6f}, n = 7, окно B9)")
    print(f"  cir.value = {cir7['gap_mean_pp'] / 100:+.6f} (σ {cir7['gap_sd_pp'] / 100:.6f}, n = 7, окно B9)")
    print(f"  nim.value: состав якоря (определение LEAD-2, без ряби дней, 1К–2К2026) = {nim_a['gap_mean_pp'] / 100:+.6f}; "
          f"среднее окна B9 (ряд b, без ряби) = {nim_b7['gap_mean_pp'] / 100:+.6f}; четыре последних квартала (ряд b) = {nim_b4['gap_mean_pp'] / 100:+.6f}")
    print(f"  разность «состав якоря» − «среднее окна B9» = {(nim_a['gap_mean_pp'] - nim_b7['gap_mean_pp']):+.3f} п.п. ЧПМ; σ ряда b без ряби и тренда = {nim_b7['sd_detrended_pp']:.3f} п.п.; σ с рябью = {nim_b7d['gap_sd_pp']:.3f} п.п.")
    ripple = {h: statistics.fmean(R[p]['nim_gap_days'] for p in QS if qparts(p)[1] == h) * 100 for h in (1, 2, 3, 4)}
    print('  рябь счёта дней по номеру квартала, п.п.: ' + ', '.join(f"{h}К {v:+.3f}" for h, v in ripple.items()), '(1К високосного года — 91 день)')
    lastq = R['2Q2026']
    print(f"  дрейф последнего квартала (2К2026) от значения: CoR {abs(lastq['cor_gap'] * 100 - cor7['gap_mean_pp']):.3f} п.п.; ЧПМ (определение LEAD-2, 365/d) {abs(lastq['nim_gap_a'] * 100 - nim_a['gap_mean_pp']):.3f} п.п.")
    thr_cor = round(2.5 * cor7['gap_sd_pp'] / 100, 4); thr_nim = round((max(abs(v) for v in ripple.values()) + 2.5 * nim_b7['sd_detrended_pp']) / 100, 4)
    print(f"  пороги гейта bridge_drift_pp: cor = 2,5σ = {thr_cor:.4f}; nim = рябь дней {max(abs(v) for v in ripple.values()):.3f} + 2,5σ без ряби и тренда = {thr_nim:.4f}")

    def hist(kind):
        out = []
        for p in QS:
            r = R[p]
            if kind == 'nim' and not r['nim_mgmt_comparable']: continue
            y, h = qparts(p); d0, d1 = ends(p)
            if kind == 'cor':
                e = dict(v=round(r['cor_engine'], 6), calc=f"−llp_debt_fa {ru(r['llp_debt_fa'])} / средние валовые кредиты по АС с лизингом {ru(r['loans_ac_avg'])} × 365/{r['days']}")
                mg = dict(v=round(r['cor_mgmt'], 6), src=K['cor_total_exact'][mk(p)][1]); g = r['cor_gap']
            elif kind == 'nim':
                use_a = r['nim_engine_a'] is not None
                e = dict(v=round(r['nim_engine_a'] if use_a else r['nim_engine_b'], 6),
                         calc=f"nii {ru(r['nii'])} × 365/{r['days']} / средние процентные активы движка {ru(r['iea_engine_avg_a'] if use_a else r['iea_engine_avg_b'])}"
                              + ('' if use_a else ' (бумаги — с прочими акциями и паями: долговые отдельно на эти даты не собраны)'))
                mg = dict(v=round(r['nim_mgmt'], 6), src=K['nim_exact'][mk(p)][1]); g = (r['nim_engine_a'] if use_a else r['nim_engine_b']) - r['nim_mgmt']
            else:
                e = dict(v=round(r['cir_engine'], 6), calc=f"−opex {ru(r['opex'])} / (nii + услуги + страхование + прочее на операционном базисе) {ru(r['income_engine_op'])}")
                mg = dict(v=round(r['cir_mgmt'], 6), src=K['cir_exact'][mk(p)][1]); g = r['cir_gap']
            out.append({'period': f"{y}Q{h}", 'mgmt': mg, 'engine': e, 'gap': {'v': round(g, 6), 'calc': 'engine − mgmt'}})
        return out
    prop = {'basis': 'mgmt↔IFRS', 'as_of': '2026-06-30', 'unit': 'доли, годовые', 'window': ['2024Q4', '2026Q2'],
            'direction': 'to_engine(v) = v + value (additive); value = среднее по окну (engine − mgmt)',
            'status': 'предложение листа калибровки calib-pnl (07.10.2026) на листах stage1/ifrs и определениях LEAD-2 §1 п. 6',
            'cor': {'method': 'additive', 'value': {'v': round(cor7['gap_mean_pp'] / 100, 6), 'calc': 'среднее gap по окну 2024Q4–2026Q2 (n = 7)'},
                    'sd': {'v': round(cor7['gap_sd_pp'] / 100, 6), 'calc': 'выборочное стандартное отклонение gap по окну'}, 'n': {'v': 7, 'calc': 'кварталов в окне'},
                    'definition': 'CoR движка = −llp_debt_fa (строка ОПУ «оценочные резервы под ожидаемые кредитные убытки») / средние валовые кредиты по АС с лизингом, без кредитов по СС × 365/d; упр. — CoR эмитента: резерв по кредитам без POCI × 4 / среднее двух концов валовых кредитов без POCI и FVTPL',
                    'history': hist('cor')},
            'nim': {'method': 'additive', 'value': {'v': round(nim_a['gap_mean_pp'] / 100, 6), 'calc': 'состав якоря: среднее по 2026Q1–2026Q2 разности (ЧПД × 4 / средние процентные активы движка − упр. ЧПМ), определение LEAD-2; без ряби счёта дней'},
                    'sd': {'v': round(nim_b7['sd_detrended_pp'] / 100, 6), 'calc': 'σ ряда 2024Q4–2026Q2 (бумаги с акциями и паями) без ряби дней и линейного тренда'}, 'n': {'v': 2, 'calc': 'кварталов в окне значения; σ — по 7 кварталам'},
                    'alt_value_window_mean': {'v': round(nim_b7['gap_mean_pp'] / 100, 6), 'calc': 'среднее окна 2024Q4–2026Q2 (ряд с акциями и паями, без ряби): не для LT-цели — состав процентных активов сместился'},
                    'day_ripple_pp': {str(h): round(v, 3) for h, v in ripple.items()},
                    'definition': 'ЧПМ движка = ЧПД × 365/d / средние процентные активы движка (шесть кредитных книг валовых + долговые бумаги + деньги, счета в ЦБ, обязательные резервы и средства в банках); упр. — ЧПМ эмитента: ЧПД × 4 / среднее двух концов процентных активов эмитента (кредиты с маржинальными, бумаги без пакета Яндекса, процентные деньги)',
                    'history': hist('nim')},
            'cir': {'method': 'additive', 'value': {'v': round(cir7['gap_mean_pp'] / 100, 6), 'calc': 'среднее gap по окну 2024Q4–2026Q2 (n = 7)'},
                    'sd': {'v': round(cir7['gap_sd_pp'] / 100, 6), 'calc': 'выборочное стандартное отклонение gap по окну'}, 'n': {'v': 7, 'calc': 'кварталов в окне'},
                    'definition': 'CIR движка = −opex / (nii + fees_net + insurance_net + misc_net) на операционном базисе (без переоценки и дивидендов пакета Яндекса; noncore_net в доход не входит); упр. — C/I эмитента с затратами на привлечение (Databook PL!136)',
                    'history': hist('cir')}}
    json.dump(prop, open(os.path.join(OUT, 'bridge_mgmt_ifrs_proposal.json'), 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=1)
    json.dump({'cor': cor7['gap_mean_pp'] / 100, 'cor_sd': cor7['gap_sd_pp'] / 100, 'cir': cir7['gap_mean_pp'] / 100, 'cir_sd': cir7['gap_sd_pp'] / 100,
               'nim_anchor': nim_a['gap_mean_pp'] / 100, 'nim_b9': nim_b7['gap_mean_pp'] / 100, 'nim_last4': nim_b4['gap_mean_pp'] / 100, 'nim_sd_clean': nim_b7['sd_detrended_pp'] / 100,
               'thr_cor': thr_cor, 'thr_nim': thr_nim}, open(os.path.join(OUT, 'bridge_values.json'), 'w', encoding='utf-8', newline='\n'), indent=1)
    print()
    print('записано: out/bridge_quarterly.csv, out/bridge_stats.csv, out/bridge_mgmt_ifrs_proposal.json, out/bridge_values.json')
