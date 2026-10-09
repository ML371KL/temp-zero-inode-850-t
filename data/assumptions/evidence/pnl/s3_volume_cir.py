# -*- coding: utf-8 -*-
"""Шаг 3. Связь комиссий, страхования и расходов с объёмом (LEAD-2 §4) и путь C/I модальной клетки.
А. История: эластичности к росту среднего портфеля — длинный ряд Databook (research/facts/t_quarterly.csv, новая методика,
   2014–2026) и кварталы 1К2024–2К2026 листов ifrs (канон расходов — редакция 6М2026).
Б. Простой квартальный расчёт модальной клетки (мир H, режим «нормализация», без ограничения капиталом) по формулам
   LEAD-2 §4 — НЕ ядро: объёмы = сектор мира H × премия Т; ЧПМ упр. линейно к 10,75 % к 2030; CoR — путь режима;
   F_q = F_(q−4)·(1 + wage + спред + link·(v − wage)); C_q = C_(q−4)·(1 + wage + link·(v − wage))·(1 + real).
   Подбор opex.real_growth под цель C/I 47 % (упр.; в базис движка — мостом шага 2), ось 44–50 %, клетки спада и кризиса.
Пишет out/link_history_long.csv, out/link_history_recent.csv, out/cir_path_modal.csv, out/cir_regimes.csv, out/guidance_2026.csv, out/opex_calibration.json."""
import json, sys
from pnl_lib import *
from s1_op_basis import rows as OP

L = load_yaml(ROOT, 'stage1', 'calib', 'pnl', 'inputs', 'lead_decisions.yaml')
BV = json.load(open(os.path.join(OUT, 'bridge_values.json'), encoding='utf-8'))
NC = json.load(open(os.path.join(OUT, 'noncore_center.json'), encoding='utf-8'))
OPd = {r['period']: r for r in OP}
H = table(read_csv('stage1', 'ifrs', 'ifrs_history.csv'))
AB = {r['book']: r for r in read_csv('stage1', 'ifrs', 'anchor_books.csv')}
WB = json.load(open(os.path.join(HERE, '..', '..', 'worlds_bank.json'), encoding='utf-8'))['worlds']   # надстройка книги
WP = collections.defaultdict(dict)
for r in read_csv('stage1', 'worlds', 'world_paths_quarterly.csv'):
    if r['period'] != 'LT':
        y, h = int(r['period'][:4]), int(r['period'][-1])
        WP[r['world']][qlabel(y, h)] = dict(key=float(r['key_avg']) / 100, cpi=float(r['cpi_yoy_avg']) / 100, wage=float(r['nominal_wage_yoy']) / 100)
LT_INFL = {'N': 0.04, 'H': 0.055, 'M': 0.098}            # stage1/worlds/README.md: LT ИПЦ миров
B_NIM, B_COR, B_CIR = BV['nim_anchor'], BV['cor'], BV['cir']
TAX = 0.25 - 0.006; NCI = 0.024                          # предложения шага 1: effective_gap и pnl.nci_share
MTN = json.load(open(os.path.join(OUT, 'misc_tax_nci.json'), encoding='utf-8'))
MISC_REAL = float(MTN['center'])                         # центр «прочего» шага 1, млрд ₽ в год в ценах 2026
FQ = [qlabel(y, h) for y in range(2026, 2037) for h in (1, 2, 3, 4) if (y, h) >= (2026, 3)]          # прогнозные кварталы 3К2026…4К2036


# ====================================================================== А. История
def long_history():
    S = collections.defaultdict(dict)
    for r in read_csv('research', 'facts', 't_quarterly.csv'):
        if r['methodology'] != 'new': continue
        try: v = float(r['value'])
        except ValueError: continue
        y, h = int(r['period'][:4]), int(r['period'][-1])
        S[(r['metric'], r['basis'])][qlabel(y, h)] = v
    fees = S[('pl.net_service_revenue', 'q')]; ins = S[('pl.net_insurance_revenue', 'q')]; nii = S[('pl.nii', 'q')]
    nrap = S[('pl.net_revenue_after_provisions', 'q')]; opb = S[('pl.operating_result_before_market', 'q')]
    loans = S[('loans.gross.total', 'pit')]
    opex = {p: nrap[p] - opb[p] for p in nrap if p in opb}          # расходы по функциям = чистая выручка после резервов − прибыль до рыночных и прочих результатов
    per = sorted(nii, key=lambda p: qparts(p))
    out = []
    for p in per:
        def avg(b, pp):
            a, c = b.get(qprev(pp)), b.get(pp)
            return (a + c) / 2 if a is not None and c is not None else None
        la, l4 = avg(loans, p), avg(loans, qprev(p, 4))
        yoy = lambda x: (x[p] / x[qprev(p, 4)] - 1) if p in x and x.get(qprev(p, 4)) not in (None, 0) and x[qprev(p, 4)] > 0 else None
        out.append(dict(period=p, loans_avg=la, v=(la / l4 - 1) if la and l4 else None, g_fees=yoy(fees), g_ins=yoy(ins), g_opex=yoy(opex), g_nii=yoy(nii),
                        fees=fees.get(p), ins=ins.get(p), opex=opex.get(p), opex_to_loans=opex[p] * 4 / la if la and p in opex else None,
                        fees_to_loans=fees[p] * 4 / la if la and p in fees else None, ins_to_loans=ins[p] * 4 / la if la and p in ins else None))
    return out


def recent_history():
    out = []
    for p in QS[4:]:
        o, o4 = OPd[p], OPd[qprev(p, 4)]
        d0, d1 = qend(qprev(p)), qend(p); e0, e1 = qend(qprev(p, 5)), qend(qprev(p, 4))
        la = (H['loans_gross_incl_lease_fvtpl'][d0][0] + H['loans_gross_incl_lease_fvtpl'][d1][0]) / 2
        l4 = (H['loans_gross_incl_lease_fvtpl'][e0][0] + H['loans_gross_incl_lease_fvtpl'][e1][0]) / 2
        fa = (H['dep_customers_total'][d0][0] + H['dep_customers_total'][d1][0]) / 2; f4 = (H['dep_customers_total'][e0][0] + H['dep_customers_total'][e1][0]) / 2
        clean = qparts(p) >= (2025, 4)        # база г/г целиком после покупки Росбанка (15.08.2024): с 4К2025
        out.append(dict(period=p, clean=clean, v_loans=la / l4 - 1, v_funds=fa / f4 - 1, g_fees=o['fees'] / o4['fees'] - 1, g_ins=o['ins'] / o4['ins'] - 1,
                        g_opex=o['opex'] / o4['opex'] - 1, g_nii=o['nii'] / o4['nii'] - 1, opex_to_loans=-o['opex'] * 4 / la, fees_to_loans=o['fees'] * 4 / la, ins_to_loans=o['ins'] * 4 / la))
    return out


# ====================================================================== Б. Простой расчёт клетки
def traj(d, y, lt_from=None):
    """Значение траектории {год: v, LT: v} в году y: точный год; между годами — линейно; после последнего года — LT (сразу или линейно к lt_from)."""
    ys = sorted(k for k in d if isinstance(k, int))
    if y in d: return d[y]
    if not ys: return d.get('LT', 0.0)
    if y < ys[0]: return d[ys[0]]
    if y > ys[-1]:
        if 'LT' not in d: return d[ys[-1]]
        if lt_from and y < lt_from: return d[ys[-1]] + (d['LT'] - d[ys[-1]]) * (y - ys[-1]) / (lt_from - ys[-1])
        return d['LT']
    a = max(k for k in ys if k < y); b = min(k for k in ys if k > y)
    return d[a] + (d[b] - d[a]) * (y - a) / (b - a)


def sector_growth(world, sector, y, kind='credit_growth'):
    g = {int(k): v for k, v in WB[world][kind][sector].items()}
    gT = (1 + LT_INFL[world]) * (1 + L['terminal_real_growth']) - 1
    last = max(g); lt_from = L['volumes_lt_from']
    if y <= last: return g[max(y, min(g))]
    if y >= lt_from: return gT
    return g[last] + (gT - g[last]) * (y - last) / (lt_from - last)


CRISIS_Q = {'downturn': {'1Q2027': 0.062, '2Q2027': 0.068, '3Q2027': 0.072, '4Q2027': 0.074}, 'crisis': {'1Q2027': 0.130, '2Q2027': 0.105, '3Q2027': 0.088, '4Q2027': 0.077}}   # LEAD-2 §8 п. 1


def run(regime='norm', world='H', link_c=1.0, link_f=1.0, link_i=0.0, real=None, spread_f=None, spread_i=None, prem_shift=0.0, growth_scale=1.0, misc_real=MISC_REAL,
        ref=None, w_loans=0.94, liq_with_loans=False):
    """Квартальный проход 3К2026…4К2036. real, spread_* — траектории {год: v, 'LT': v, 'LT_from': год}.
    ЧПД опорного пути (ref=None; «нормализация», премия центра) = путь упр. ЧПМ × процентные активы. Вне опорного пути (другой рост, другой режим)
    ЧПД = ЧПД опорного пути × (w_loans × кредиты / кредиты опоры + (1 − w_loans) × ликвидные активы / ликвидные активы опоры) + сдвиг ЧПМ режима × активы:
    книги ядра начисляют доход по остаткам, и прирост кредитов приносит кредитную маржу, а не среднюю ЧПМ; w_loans — доля ЧПД от кредитных книг [В]."""
    real = real or {'LT': 0.0}; spread_f = spread_f or {'LT': 0.0}; spread_i = spread_i or {'LT': 0.0}
    rg = L['regimes'][regime]
    E = {'retail_other': sum(float(AB[b]['bal_2026-06-30']) for b in ('cards', 'cash_loans', 'auto')), 'mortgage': float(AB['mortgage']['bal_2026-06-30']),
         'corporate': sum(float(AB[b]['bal_2026-06-30']) for b in ('sme_loans', 'corp_loans'))}
    Lq = float(AB['securities']['bal_2026-06-30']) + float(AB['liquidity']['bal_2026-06-30'])
    loans_hist = {p: H['loans_gross_incl_lease_fvtpl'][qend(p)][0] for p in QS[4:]}       # концы 1К2025…2К2026
    loans_hist['4Q2024'] = H['loans_gross_incl_lease_fvtpl'][qend('4Q2024')][0]
    tot = dict(loans_hist); ac_share = (tot['2Q2026'] - H['loans_fvtpl']['2026-06-30'][0]) / tot['2Q2026']
    flows = {k: {p: OPd[p][k] for p in QS} for k in ('fees', 'ins', 'opex', 'nii', 'llp_debt_fa', 'misc_net', 'noncore_net', 'ni_shareholders')}
    I = 1.0; iea_prev = tot['2Q2026'] + Lq; out = []
    nim0 = 0.11588; nim_t = L['targets']['nim_mgmt_lt']; n_glide = (L['targets']['nim_lt_year'] - 2026) * 4 - 2       # кварталов от якоря до 4К2029
    ncA = {int(k): v for k, v in NC['traj_A'].items() if k != 'LT'}
    for k, p in enumerate(FQ, start=1):
        y, h = qparts(p); w = WP[world][p]; dd = qdays(p)
        I *= (1 + w['cpi']) ** 0.25
        # --- объёмы
        prev_tot = sum(E.values())
        for s in E:
            prem = (traj({int(a): b for a, b in L['premium_pp'][s].items()}, y) + (prem_shift if y <= 2031 else 0.0)) / 100
            prem = max(prem, 0.0) if prem_shift < 0 else prem
            if regime == 'crisis' and y in rg.get('growth_override', {}):
                g = rg['growth_override'][y]
            else:
                g = (1 + sector_growth(world, s, y)) * (1 + prem * growth_scale) - 1 + rg.get('growth_adj', {}).get(y, 0.0)
            E[s] *= (1 + g) ** 0.25
        tot[p] = sum(E.values())
        gf = (1 + sector_growth(world, 'retail', y, 'funds_growth')) * (1 + traj({int(a): b for a, b in L['funds_premium_pp'].items()}, y) / 100) - 1
        Lq *= (tot[p] / prev_tot) if liq_with_loans else (1 + gf) ** 0.25
        iea = tot[p] + Lq
        avg_l = (prev_tot + tot[p]) / 2; avg_l4 = (tot[qprev(p, 5)] + tot[qprev(p, 4)]) / 2
        v = avg_l / avg_l4 - 1
        # --- ЧПД
        sh = rg['nim_shift']; shift = 0.0
        if y >= 2027:
            shift = sh.get(y, sh.get('LT', 0.0) if y > max([a for a in sh if isinstance(a, int)] or [2026]) else 0.0)
        nim_m = nim0 + (nim_t - nim0) * min(1.0, k / n_glide) + shift
        avg_q = (iea_prev - prev_tot + Lq) / 2
        if ref is None:
            nii = (nim_m + B_NIM) * (iea_prev + iea) / 2 * dd / 365
        else:
            rl, rq, rn = ref[p]
            nii = rn * (w_loans * avg_l / rl + (1 - w_loans) * avg_q / rq) + shift * (iea_prev + iea) / 2 * dd / 365
        # --- резервы
        cor_m = CRISIS_Q.get(regime, {}).get(p)
        if cor_m is None:
            c = {int(a) if a != 'LT' else 'LT': b for a, b in rg['cor'].items()}
            cor_m = c[y] if y in c else c['LT']
        llp = (cor_m + B_COR) * avg_l * ac_share * dd / 365
        # --- комиссии, страхование, расходы (LEAD-2 §4)
        ww = w['wage']
        yr = lambda t: traj({(int(a) if a not in ('LT', 'LT_from') else a): b for a, b in t.items() if a != 'LT_from'}, y, t.get('LT_from'))
        fees = flows['fees'][qprev(p, 4)] * (1 + ww + yr(spread_f) + link_f * (v - ww))
        ins = flows['ins'][qprev(p, 4)] * (1 + ww + yr(spread_i) + link_i * (v - ww))
        opex = flows['opex'][qprev(p, 4)] * (1 + ww + link_c * (v - ww)) * (1 + yr(real))          # со знаком минус
        misc = misc_real * I * 0.25
        nc_y = ncA.get(y, NC['traj_A']['LT'])
        noncore = (nc_y - NC['R_1h']) / 2 * I if y == 2026 else nc_y / 4 * I
        one_off = rg.get('one_off', {}).get('amount', 0.0) if regime == 'crisis' and p == '1Q2027' else 0.0
        pbt = nii - llp + fees + ins + misc + noncore + opex + one_off
        ni_sh = pbt * (1 - TAX) * (1 - NCI)
        for kk, vv in (('fees', fees), ('ins', ins), ('opex', opex), ('nii', nii), ('llp_debt_fa', -llp), ('misc_net', misc), ('noncore_net', noncore), ('ni_shareholders', ni_sh)):
            flows[kk][p] = vv
        out.append(dict(period=p, year=y, loans=tot[p], v=v, wage=ww, nim_mgmt=nim_m, cor_mgmt=cor_m, nii=nii, llp=llp, fees=fees, ins=ins, opex=-opex, misc=misc, noncore=noncore,
                        one_off=one_off, pbt=pbt, ni_sh=ni_sh, income=nii + fees + ins + misc, cir_engine=-opex / (nii + fees + ins + misc), iea=iea, avg_loans=avg_l, avg_liq=avg_q))
        iea_prev = iea
    return out, flows


def annual(out, flows=None):
    res = {}
    for y in range(2026, 2037):
        qs = [r for r in out if r['year'] == y]
        c = sum(r['opex'] for r in qs); inc = sum(r['income'] for r in qs)
        if y == 2026 and flows is not None:
            c += -sum(OPd[p]['opex'] for p in ('1Q2026', '2Q2026')); inc += sum(OPd[p]['nii'] + OPd[p]['fees'] + OPd[p]['ins'] + OPd[p]['misc_net'] for p in ('1Q2026', '2Q2026'))
        res[y] = dict(cir_engine=c / inc, cir_mgmt=c / inc - B_CIR, opex=c, income=inc, ni_sh=sum(r['ni_sh'] for r in qs), loans_end=qs[-1]['loans'], v=statistics.fmean(r['v'] for r in qs),
                      nim_mgmt=statistics.fmean(r['nim_mgmt'] for r in qs), cor_mgmt=statistics.fmean(r['cor_mgmt'] for r in qs),
                      fees=sum(r['fees'] for r in qs), ins=sum(r['ins'] for r in qs), nii=sum(r['nii'] for r in qs), llp=sum(r['llp'] for r in qs))
    return res


def bisect(f, lo, hi, tol=1e-7):
    flo = f(lo)
    for _ in range(80):
        mid = (lo + hi) / 2; fm = f(mid)
        if (fm > 0) == (flo > 0): lo, flo = mid, fm
        else: hi = mid
        if hi - lo < tol: break
    return (lo + hi) / 2


SPI = {'2026': -0.06, '2027': -0.03, 'LT': 0.0, 'LT_from': 2028}       # страхование: зарплаты мира минус спред (факт 1П2026 +1,8 % г/г при зарплатах ≈ +10 %)
SEASON_2H = None                                                         # сезонная разность C/I упр. 2П − 1П по 2025 году (считается ниже из моста)


def make_ref(**kw):
    """Опорный путь ЧПД: «нормализация», премия центра (ЧПД = упр. ЧПМ через мост × процентные активы)."""
    base = {k: v for k, v in kw.items() if k in ('liq_with_loans',)}
    out, _ = run(**base)
    return {r['period']: (r['avg_loans'], r['avg_liq'], r['nii']) for r in out}


def tr3(r0, r1, r2):
    return {'2026': r0, **{str(y): r1 for y in range(2027, 2031)}, 'LT': r2, 'LT_from': 2031}


def calibrate(target=None, cir_2h26=None, **kw):
    """Траектория opex.real_growth из трёх чисел: 2026 (C/I упр. 2П2026 = уровень 1П2026 с сезонной разностью 2025 года),
    2027–2030 (C/I упр. 2030 = цель), с 2031 (C/I упр. 2036 = цель)."""
    target = target or L['targets']['cir_mgmt_lt']
    def h2(r0):
        out, _ = run(real=tr3(r0, 0.0, 0.0), **kw)
        qs = [r for r in out if r['year'] == 2026]
        return sum(r['opex'] for r in qs) / sum(r['income'] for r in qs) - B_CIR - cir_2h26
    r0 = bisect(h2, -0.2, 0.2)
    r1 = bisect(lambda x: annual(run(real=tr3(r0, x, 0.0), **kw)[0])[2030]['cir_mgmt'] - target, -0.15, 0.15)
    r2 = bisect(lambda x: annual(run(real=tr3(r0, r1, x), **kw)[0])[2036]['cir_mgmt'] - target, -0.05, 0.05)
    return r0, r1, r2, tr3(r0, r1, r2)


if __name__ == '__main__':
    print('=' * 110)
    print('ШАГ 3А. История: рост комиссий, страхования и расходов против роста среднего портфеля (г/г к тому же кварталу)')
    lh = long_history(); write_csv('link_history_long.csv', lh)
    f = lambda x: '    — ' if x is None else f"{x * 100:6.1f}"
    print('Длинный ряд Databook (новая методика), годы: рост среднего портфеля; услуги нетто; страхование нетто; расходы; отношения к среднему портфелю, %')
    for y in range(2016, 2026):
        qs = [r for r in lh if qparts(r['period'])[0] == y]; q0 = [r for r in lh if qparts(r['period'])[0] == y - 1]
        if len(qs) < 4 or len(q0) < 4 or any(r['loans_avg'] is None for r in qs + q0): continue
        la = statistics.fmean(r['loans_avg'] for r in qs); l0 = statistics.fmean(r['loans_avg'] for r in q0)
        g = lambda k: sum(r[k] for r in qs) / sum(r[k] for r in q0) - 1
        print(f"  {y}: v {f(la / l0 - 1)} | услуги {f(g('fees'))} страхование {f(g('ins'))} расходы {f(g('opex'))} | расходы/портфель {sum(r['opex'] for r in qs) / la * 100:5.1f}; услуги/портфель {sum(r['fees'] for r in qs) / la * 100:5.1f}; страхование/портфель {sum(r['ins'] for r in qs) / la * 100:4.1f}")
    print('Регрессии квартальных темпов г/г на рост среднего портфеля v (наклон = связь с объёмом; свободный член несёт зарплаты и собственный тренд):')
    REG = []
    for name, lo, hi in (('2016К1–2024К2, до Росбанка', (2016, 1), (2024, 2)), ('2019К1–2024К2', (2019, 1), (2024, 2)), ('2021К1–2024К2', (2021, 1), (2024, 2))):
        sel = [r for r in lh if lo <= qparts(r['period']) <= hi and r['v'] is not None]
        for k, lab in (('g_fees', 'услуги нетто'), ('g_ins', 'страхование'), ('g_opex', 'расходы'), ('g_nii', 'ЧПД')):
            ss = [r for r in sel if r[k] is not None]
            o = ols([r['v'] for r in ss], [r[k] for r in ss])
            REG.append(dict(window=name, series=lab, intercept=o['a'], slope=o['b'], se=o['se'], r2=o['r2'], n=o['n']))
            print(f"  {name:28s} {lab:13s}: g = {o['a'] * 100:6.1f} % + {o['b']:5.2f} (± {o['se']:4.2f}) × v;  R² {o['r2']:4.2f}; n = {o['n']}; средние: v {statistics.fmean(r['v'] for r in ss) * 100:5.1f} %, g {statistics.fmean(r[k] for r in ss) * 100:5.1f} %")
    rh = recent_history(); write_csv('link_history_recent.csv', rh)
    print('Кварталы 2025–2026 по листам ifrs (канон расходов — редакция 6М2026); «чистые» — база г/г целиком после покупки Росбанка:')
    for r in rh:
        print(f"  {r['period']} {'чистый ' if r['clean'] else 'ступень'}: v кредиты {f(r['v_loans'])}, v средства {f(r['v_funds'])} | услуги {f(r['g_fees'])}, страхование {f(r['g_ins'])}, расходы {f(r['g_opex'])}, ЧПД {f(r['g_nii'])} | "
              f"расходы/портфель {r['opex_to_loans'] * 100:5.2f}, услуги/портфель {r['fees_to_loans'] * 100:4.2f}, страхование/портфель {r['ins_to_loans'] * 100:4.2f}")
    cl = [r for r in rh if r['clean']]
    mv = statistics.fmean(r['v_loans'] for r in cl)
    print(f"  среднее трёх чистых кварталов (4К2025–2К2026): v {mv * 100:.1f} %; услуги {statistics.fmean(r['g_fees'] for r in cl) * 100:.1f} %; страхование {statistics.fmean(r['g_ins'] for r in cl) * 100:.1f} %; расходы {statistics.fmean(r['g_opex'] for r in cl) * 100:.1f} %")
    h1 = lambda k: (OPd['1Q2026'][k] + OPd['2Q2026'][k]) / (OPd['1Q2025'][k] + OPd['2Q2025'][k]) - 1
    print(f"  1П2026 к 1П2025: услуги {h1('fees') * 100:+.1f} %, страхование {h1('ins') * 100:+.1f} %, расходы {h1('opex') * 100:+.1f} %, ЧПД {h1('nii') * 100:+.1f} %")
    print('  подразумеваемая связь link = (g − w) / (v − w) по трём чистым кварталам при росте зарплат w [В: ряд зарплат в листах этапа 1 не собран; мир H на 2П2026 — 9,5 %]:')
    write_csv('link_regressions.csv', REG)
    IMP = []
    for w in (0.08, 0.095, 0.11, 0.13):
        IMP.append(dict(wage=w, fees=(statistics.fmean(r['g_fees'] for r in cl) - w) / (mv - w), ins=(statistics.fmean(r['g_ins'] for r in cl) - w) / (mv - w), opex=(statistics.fmean(r['g_opex'] for r in cl) - w) / (mv - w)))
        print(f"    w = {w * 100:4.1f} %: услуги {(statistics.fmean(r['g_fees'] for r in cl) - w) / (mv - w):5.2f}; страхование {(statistics.fmean(r['g_ins'] for r in cl) - w) / (mv - w):5.2f}; расходы {(statistics.fmean(r['g_opex'] for r in cl) - w) / (mv - w):5.2f}")
    from s1_op_basis import Qd, q as fq
    print('  состав расходов 1П2026, млрд ₽: ' + '; '.join(f"{nm} {-(fq(m, '1Q2026') + fq(m, '2Q2026')):.1f}" for nm, m in (('привлечение (маркетинг)', 'opex_marketing'), ('обслуживание', 'opex_servicing'), ('технологии', 'opex_tech'), ('административные', 'opex_admin'))))
    tot_c = -sum(fq(m, p) for m in ('opex_marketing', 'opex_servicing', 'opex_tech', 'opex_admin') for p in ('1Q2026', '2Q2026'))
    sh = {m: -(fq(m, '1Q2026') + fq(m, '2Q2026')) / tot_c for m in ('opex_marketing', 'opex_servicing', 'opex_tech', 'opex_admin')}
    struct = sh['opex_marketing'] * 1.0 + sh['opex_servicing'] * 1.0 + (sh['opex_tech'] + sh['opex_admin']) * 0.3
    print(f"  структурная оценка связи [В]: привлечение {sh['opex_marketing'] * 100:.0f} % × 1 + обслуживание {sh['opex_servicing'] * 100:.0f} % × 1 + технологии и административные {(sh['opex_tech'] + sh['opex_admin']) * 100:.0f} % × 0,3 = {struct:.2f}")
    print('  ступень Авто.ру (сделка 02.06.2026): выручка «лайфстайл и классифайды» по кварталам: ' + ', '.join(f"{p} {fq('fee_inc_lifestyle_classified', p)}" for p in QS[4:]) + ' — один месяц Авто.ру во 2К2026; про-форма не раскрыта (null)')

    print()
    print('=' * 110)
    print('ШАГ 3Б. Простой расчёт модальной клетки (мир H, «нормализация»; рост не урезан капиталом)')
    K = table(read_csv('stage1', 'mgmt', 'mgmt_kpi.csv'))
    cir_h = {p: K['cir_exact'][p][0] / 100 for p in ('6M2025', '2025FY', '6M2026')}
    inc = lambda ps: sum(OPd[p]['nii'] + OPd[p]['fees'] + OPd[p]['ins'] + OPd[p]['misc_net'] for p in ps)
    cir_eng = lambda ps: -sum(OPd[p]['opex'] for p in ps) / inc(ps)
    s25 = (cir_eng(['3Q2025', '4Q2025']) - cir_eng(['1Q2025', '2Q2025']))
    cir_2h26 = cir_eng(['1Q2026', '2Q2026']) - B_CIR + s25
    print(f"мосты (шаг 2): ЧПМ {B_NIM * 100:+.3f} п.п., CoR {B_COR * 100:+.3f} п.п., CIR {B_CIR * 100:+.3f} п.п.; цель C/I упр. {L['targets']['cir_mgmt_lt'] * 100:.1f} % → движок {(L['targets']['cir_mgmt_lt'] + B_CIR) * 100:.2f} %")
    print(f"C/I движка (операционный базис): 1П2025 {cir_eng(['1Q2025', '2Q2025']) * 100:.2f} %, 2П2025 {cir_eng(['3Q2025', '4Q2025']) * 100:.2f} % (сезонная разность {s25 * 100:+.2f} п.п.), 1П2026 {cir_eng(['1Q2026', '2Q2026']) * 100:.2f} %; "
          f"упр. (Databook): 6М2025 {cir_h['6M2025'] * 100:.2f} %, 2025 {cir_h['2025FY'] * 100:.2f} %, 6М2026 {cir_h['6M2026'] * 100:.2f} %")
    print(f"ориентир C/I упр. 2П2026 = C/I движка 1П2026 через мост + сезонная разность 2025 года = {cir_2h26 * 100:.2f} %")
    ref = make_ref()
    variants = {'A: связь 1,0 (расходы и услуги)': dict(link_c=1.0, link_f=1.0), 'D: связь 0,7': dict(link_c=0.7, link_f=0.7),
                'B: связь 0,5': dict(link_c=0.5, link_f=0.5), 'C: связь 0 (формулы Сбера)': dict(link_c=0.0, link_f=0.0)}
    common = dict(link_i=0.0, spread_i=SPI, ref=ref)
    cal = {}; g3 = {}
    write_csv('link_implied.csv', IMP)
    for name, kw in variants.items():
        kw = {**kw, **common}
        r0, r1, r2, tr = calibrate(cir_2h26=cir_2h26, **kw)
        cal[name] = (r0, r1, r2, tr, kw)
        out, fl = run(real=tr, **kw); an = annual(out, fl)
        print(f"\n{name}: opex.real_growth 2026 = {r0 * 100:+.2f} %, 2027–2030 = {r1 * 100:+.2f} % в год, с 2031 = {r2 * 100:+.2f} %")
        print('  год   рост портфеля  v(ср.)  зарплаты  ЧПМ упр  CoR упр  C/I движок  C/I упр  расходы  доход  прибыль акц.')
        prev = 3813.1
        for y in range(2026, 2037):
            a = an[y]; ww = statistics.fmean(r['wage'] for r in out if r['year'] == y)
            print(f"  {y}  {((a['loans_end'] / prev) ** (2 if y == 2026 else 1) - 1) * 100:8.1f}%  {a['v'] * 100:6.1f}  {ww * 100:7.1f}  {a['nim_mgmt'] * 100:7.2f}  {a['cor_mgmt'] * 100:6.2f}  {a['cir_engine'] * 100:9.2f}  {a['cir_mgmt'] * 100:7.2f}  {a['opex']:8.1f} {a['income']:7.1f}  {a['ni_sh']:8.1f}" + ('  (2026: расходы и доход — год с фактом 1П; прибыль — 2П; рост — 2П в годовом выражении)' if y == 2026 else ''))
            prev = a['loans_end']
        q26 = [r for r in out if r['year'] == 2026]
        g3[name] = (q26[0]['fees'] / OPd['3Q2025']['fees'] - 1, q26[0]['opex'] / -OPd['3Q2025']['opex'] - 1)
        print('  2П2026 по кварталам: ' + '; '.join(f"{r['period']}: ЧПД {r['nii']:.1f}, услуги {r['fees']:.1f} ({(r['fees'] / OPd[qprev(r['period'], 4)]['fees'] - 1) * 100:+.1f} % г/г), страхование {r['ins']:.1f}, расходы {r['opex']:.1f} ({(r['opex'] / -OPd[qprev(r['period'], 4)]['opex'] - 1) * 100:+.1f} % г/г), резервы {r['llp']:.1f}, C/I упр. {(r['cir_engine'] - B_CIR) * 100:.2f} %, прибыль {r['ni_sh']:.1f}" for r in q26))
    calraw = {n_: c_[:3] for n_, c_ in cal.items()}
    # ---- предложение: связь 0,7, траектория из четырёх чисел (2031–2032 — отдельным значением, чтобы C/I не проседал после 2030 года)
    def tr4(r0, r1, r3, r2):
        return {'2026': r0, **{str(y): r1 for y in range(2027, 2031)}, '2031': r3, '2032': r3, 'LT': r2, 'LT_from': 2033}
    r0D, r1D = cal['D: связь 0,7'][0], cal['D: связь 0,7'][1]; kwD0 = cal['D: связь 0,7'][4]; tgt = L['targets']['cir_mgmt_lt']
    r3D = bisect(lambda x: annual(run(real=tr4(r0D, r1D, x, 0.0), **kwD0)[0])[2032]['cir_mgmt'] - tgt, -0.05, 0.05)
    r2D = bisect(lambda x: annual(run(real=tr4(r0D, r1D, r3D, x), **kwD0)[0])[2036]['cir_mgmt'] - tgt, -0.05, 0.05)
    trP = tr4(round(r0D, 3), round(r1D, 3), round(r3D, 3), round(r2D, 4))
    outP, flP = run(real=trP, **kwD0); anP = annual(outP, flP)
    print()
    print(f"ПРЕДЛОЖЕНИЕ (связь 0,7): opex.real_growth ={json.dumps(trP, ensure_ascii=False)}  (точные корни: {r0D * 100:+.3f} / {r1D * 100:+.3f} / {r3D * 100:+.3f} / {r2D * 100:+.3f} %)")
    print('  C/I упр. по годам при округлённой траектории: ' + ' '.join(f"{y}: {anP[y]['cir_mgmt'] * 100:.2f}" for y in range(2026, 2037)))
    print('  рост расходов г/г по годам, %: ' + ' '.join(f"{y}: {(anP[y]['opex'] / anP[y - 1]['opex'] - 1) * 100:.1f}" for y in range(2027, 2037)) + f"; 2026 к 2025: {(anP[2026]['opex'] / -sum(OPd[p]['opex'] for p in QS[4:8]) - 1) * 100:.1f}")
    print('  рост услуг нетто г/г, %: ' + ' '.join(f"{y}: {(anP[y]['fees'] / anP[y - 1]['fees'] - 1) * 100:.1f}" for y in range(2028, 2037)))
    write_csv('cir_path_modal.csv', [dict(year=y, **anP[y]) for y in anP])
    cal['D: связь 0,7'] = (r0D, r1D, r2D, trP, kwD0)
    axP = {t_: bisect(lambda d: annual(run(real={**trP, **{str(y): trP[str(y)] + d for y in range(2027, 2031)}}, **kwD0)[0])[2030]['cir_mgmt'] - t_, -0.08, 0.08) for t_ in L['targets']['cir_axis']}
    print(f"  ось: сдвиг значений 2027–2030 на {axP[0.44] * 100:+.2f} п.п. → C/I упр. 2030 = 44,0 %; на {axP[0.50] * 100:+.2f} п.п. → 50,0 %")
    # ---- связь, при которой цель достигается без реального роста
    def at_zero(lk):
        kw = dict(link_c=lk, link_f=lk, **common)
        r0 = cal['D: связь 0,7'][0]
        return annual(run(real=tr3(r0, 0.0, 0.0), **kw)[0])[2030]['cir_mgmt'] - L['targets']['cir_mgmt_lt']
    lk0 = bisect(at_zero, 0.0, 1.0)
    print(f"\nСвязь, при которой C/I упр. 2030 = 47,0 % при нулевом реальном росте расходов в 2027–2030 годах: {lk0:.2f}")
    # ---- чувствительность калибровки к пути процентных активов и к мосту ЧПМ
    ref2 = make_ref(liq_with_loans=True)
    kwD = dict(link_c=0.7, link_f=0.7, link_i=0.0, spread_i=SPI)
    a2 = calibrate(cir_2h26=cir_2h26, ref=ref2, liq_with_loans=True, **kwD)
    print(f"Чувствительность (связь 0,7): если бумаги и ликвидность растут как кредиты (процентные активы ∝ кредитам): 2026 {a2[0] * 100:+.2f} %, 2027–2030 {a2[1] * 100:+.2f} %, с 2031 {a2[2] * 100:+.2f} % "
          f"(центр: {cal['D: связь 0,7'][0] * 100:+.2f} / {cal['D: связь 0,7'][1] * 100:+.2f} / {cal['D: связь 0,7'][2] * 100:+.2f})")
    # ---- ось расходов → C/I 44–50 %
    print()
    print('Ось расходов (сдвиг реального роста 2027–2030), переведённая в C/I упр. 2030 года:')
    axis = {}
    for name in variants:
        r0, r1, r2, tr, kw = cal[name]
        res = {}
        for tgt in L['targets']['cir_axis']:
            res[tgt] = bisect(lambda d: annual(run(real={**tr, **{str(y): tr[str(y)] + d for y in range(2027, 2031)}}, **kw)[0])[2030]['cir_mgmt'] - tgt, -0.08, 0.08)
        axis[name] = res
        chk = {t: annual(run(real={**tr, **{str(y): tr[str(y)] + d for y in range(2027, 2031)}}, **kw)[0]) for t, d in res.items()}
        print(f"  {name[:1]}: сдвиг {res[0.44] * 100:+.2f} п.п. → C/I 2030 {chk[0.44][2030]['cir_mgmt'] * 100:.1f} % (2036: {chk[0.44][2036]['cir_mgmt'] * 100:.1f} %); сдвиг {res[0.50] * 100:+.2f} п.п. → {chk[0.50][2030]['cir_mgmt'] * 100:.1f} % (2036: {chk[0.50][2036]['cir_mgmt'] * 100:.1f} %)")
    # ---- чувствительность C/I к пути роста (двойной счёт суждения о росте)
    print()
    SENS = []
    print('C/I упр. 2032 года при другом пути роста (траектория расходов — калибровка центра); доля ЧПД от кредитных книг w = 0,94 и w = 0,68 (ЧПМ на активы неизменна):')
    for name in variants:
        r0, r1, r2, tr, kw = cal[name]
        line = f"  {name[:1]}:"; rec = dict(variant=name)
        for wl in (0.94, 0.68):
            k2 = {**kw, 'w_loans': wl}
            base = annual(run(real=tr, **k2)[0]); ups = annual(run(real=tr, prem_shift=5.0, **k2)[0]); dns = annual(run(real=tr, prem_shift=-5.0, **k2)[0]); nop = annual(run(real=tr, growth_scale=0.0, **k2)[0])
            rec.update({f'center_{wl}': base[2032]['cir_mgmt'], f'plus5_{wl}': ups[2032]['cir_mgmt'], f'minus5_{wl}': dns[2032]['cir_mgmt'], f'sector_{wl}': nop[2032]['cir_mgmt']})
            line += f" w = {wl}: центр {base[2032]['cir_mgmt'] * 100:.2f} %; премия +5 п.п. {ups[2032]['cir_mgmt'] * 100:.2f} %; −5 п.п. {dns[2032]['cir_mgmt'] * 100:.2f} %; рост = сектор {nop[2032]['cir_mgmt'] * 100:.2f} % |"
        SENS.append(rec)
        print(line + f" портфель 2032: {base[2032]['loans_end']:.0f} / {ups[2032]['loans_end']:.0f} / {dns[2032]['loans_end']:.0f} / {nop[2032]['loans_end']:.0f}")
    write_csv('cir_growth_sens.csv', SENS)
    # ---- режимы
    print()
    print('Клетки режимов (мир H): C/I упр. и операционная прибыль акционеров по годам')
    reg_rows = []; np26 = {}
    for name in ('A: связь 1,0 (расходы и услуги)', 'D: связь 0,7', 'B: связь 0,5'):
        r0, r1, r2, tr, kw = cal[name]
        for rg in ('soft', 'norm', 'downturn', 'crisis'):
            out, fl = run(regime=rg, real=tr, **kw); an = annual(out, fl)
            reg_rows += [dict(variant=name[:1], regime=rg, year=y, cir_mgmt=an[y]['cir_mgmt'], ni_sh=an[y]['ni_sh'], v=an[y]['v'], opex=an[y]['opex'], fees=an[y]['fees'], nii=an[y]['nii'], llp=an[y]['llp']) for y in an]
            if name.startswith('D'): np26[rg] = [r for r in out if r['year'] == 2026]
            print(f"  {name[:1]} {rg:9s}: C/I " + ' '.join(f"{y}:{an[y]['cir_mgmt'] * 100:5.1f}" for y in (2026, 2027, 2028, 2029, 2030, 2032, 2036)) + ' | прибыль ' + ' '.join(f"{y}:{an[y]['ni_sh']:6.0f}" for y in (2027, 2028, 2030)) +
                  f" | 2027: v {an[2027]['v'] * 100:5.1f} %, расходы {an[2027]['opex']:.0f} ({(an[2027]['opex'] / an[2026]['opex'] - 1) * 100:+.1f} %), услуги {an[2027]['fees']:.0f}")
    write_csv('cir_regimes.csv', reg_rows)

    # ---- гайденс 2026 при центрах книги (п. 9)
    print()
    print('Гайденс 2026 при центрах книги (связь 0,7; простой расчёт 2П2026):')
    np25 = sum(OPd[p]['ni_shareholders'] for p in QS[4:8]); np1h = OPd['1Q2026']['ni_shareholders'] + OPd['2Q2026']['ni_shareholders']
    SH_ISS, SH_OUT = 2682.74786, 2549.948
    prob = L['regime_prob']; mass = 0.0; g_rows = []
    for rg, qs in np26.items():
        n3, n4 = qs[0]['ni_sh'], qs[1]['ni_sh']; fy = np1h + n3 + n4; gr = fy / np25 - 1
        d3 = 0.25 * (OPd['4Q2025']['ni_shareholders'] + OPd['1Q2026']['ni_shareholders'] + OPd['2Q2026']['ni_shareholders'] + n3) / 4 * 1000 / SH_ISS
        d4 = 0.25 * (OPd['1Q2026']['ni_shareholders'] + OPd['2Q2026']['ni_shareholders'] + n3 + n4) / 4 * 1000 / SH_ISS
        dps = 4.6 + 4.7 + d3 + d4
        bv3 = 756.8 + n3 - 4.6 * SH_OUT / 1000; bv4 = bv3 + n4 - 4.7 * SH_OUT / 1000
        roe = fy / statistics.fmean([683.631, 719.7, 756.8, bv3, bv4])
        if gr < 0.20: mass += prob[rg]
        g_rows.append(dict(regime=rg, np_3q=n3, np_4q=n4, np_2026=fy, growth=gr, dps_3q=d3, dps_4q=d4, dps_2026=dps, dps_growth=dps / 14.9 - 1, roe_engine=roe))
        print(f"  {rg:9s}: прибыль 3К {n3:.1f}, 4К {n4:.1f}; 2026 = {fy:.1f} ({gr * 100:+.1f} % к {np25:.1f}); DPS 3К {d3:.2f} ₽, 4К {d4:.2f} ₽, за год {dps:.2f} ₽ ({(dps / 14.9 - 1) * 100:+.1f} % к 14,90); ROE движка {roe * 100:.1f} %")
    print(f"  масса клеток с ростом операционной прибыли ниже +20 %: {mass:.2f}; порог: прибыль 2026 ≥ {np25 * 1.2:.1f}, то есть 2П2026 ≥ {np25 * 1.2 - np1h:.1f} (1П2026 — {np1h:.1f})")
    write_csv('guidance_2026.csv', g_rows)
    rD = cal['D: связь 0,7']
    json.dump({'proposal': {'links': {'opex': 0.7, 'fees': 0.7, 'insurance': 0.0}, 'trajectory': trP, 'roots': {'2026': r0D, '2027_2030': r1D, '2031_2032': r3D, 'lt': r2D}, 'axis_shift': {str(k): v for k, v in axP.items()},
                            'cir_mgmt_path': {str(y): anP[y]['cir_mgmt'] for y in anP}},
               'alternatives': {n[:1]: {'name': n, 'real_2026': calraw[n][0], 'real_2027_2030': calraw[n][1], 'real_lt': calraw[n][2], 'fees_3q26_yoy': g3[n][0], 'opex_3q26_yoy': g3[n][1], 'axis_shift': {str(k): v for k, v in axis[n].items()}} for n in cal},
               'link_at_zero_real': lk0, 'insurance_spread': SPI, 'cir_engine_target': L['targets']['cir_mgmt_lt'] + B_CIR, 'cir_2h26_mgmt_ref': cir_2h26,
               'sens_iea_with_loans': {'real_2026': a2[0], 'real_2027_2030': a2[1], 'real_lt': a2[2]}, 'guidance_mass_below_20': mass},
              open(os.path.join(OUT, 'opex_calibration.json'), 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=1)
    print()
    print('записано: out/link_history_long.csv, out/link_history_recent.csv, out/cir_path_modal.csv, out/cir_regimes.csv, out/guidance_2026.csv, out/opex_calibration.json')
