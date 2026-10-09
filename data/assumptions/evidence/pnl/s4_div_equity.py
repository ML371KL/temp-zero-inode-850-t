# -*- coding: utf-8 -*-
"""Шаг 4. Дивидендная база и доля выплаты; прочие движения капитала; квартальный профиль; узлы гайденса.
Читает stage1/market/dividends_public.csv, stage1/ifrs/ifrs_quarterly.csv, stage1/mgmt/{mgmt_kpi,guidance}.csv,
stage1/regimes/season_sigma.json, op_basis_quarterly.csv (шаг 1), out/guidance_2026.csv (шаг 3).
Пишет out/dividend_payout.csv, out/equity_other_movements.csv, out/quarter_profile.csv, out/guidance_nodes_proposal.json."""
import json
from pnl_lib import *
from s1_op_basis import rows as OP, q as fq

OPd = {r['period']: r for r in OP}
L = load_yaml(ROOT, 'stage1', 'calib', 'pnl', 'inputs', 'lead_decisions.yaml')
SH_ISS = 2682.74786            # размещённые акции, млн шт. (МСФО 6М2026, прим. 22, с. 79)

if __name__ == '__main__':
    print('=' * 110)
    print('ШАГ 4. Дивиденды: доля выплаты к средней операционной прибыли акционеров четырёх последних кварталов')
    DIV = read_csv('stage1', 'market', 'dividends_public.csv')
    rows = []
    for d in DIV:
        fp = d['fiscal_period']
        if '-' in fp: continue                                  # выплата «за девять месяцев 2024 года» — до квартального ритма
        p = qlabel(int(fp[:4]), int(fp[-1])); dps = float(d['dps']); pool = float(d['total_rub']) / 1e9
        win = [qprev(p, k) for k in (3, 2, 1, 0)]
        base = statistics.fmean(OPd[w]['ni_shareholders'] for w in win)
        qp = OPd[p]['ni_shareholders']
        rows.append(dict(period=p, dps=dps, pool_bn=pool, op_np_quarter=qp, base_avg4=base, payout_to_avg4=pool / base, payout_to_quarter=pool / qp,
                         payout_to_reported_quarter=pool / OPd[p]['ni_sh_reported'], decided=d['decided_date'], record=d['record_date'], window=' + '.join(win)))
        print(f"  {p}: DPS {dps:.2f} ₽ × {SH_ISS:.1f} млн = {pool:6.3f} млрд ₽; база (средняя за {win[0]}…{win[-1]}) {base:6.3f} → {pool / base * 100:5.1f} %; к операционной прибыли квартала {qp:6.3f} → {pool / qp * 100:5.1f} %; к отчётной прибыли акционеров квартала → {pool / OPd[p]['ni_sh_reported'] * 100:5.1f} %")
    write_csv('dividend_payout.csv', rows)
    post = [r for r in rows if r['period'] != '4Q2024']
    m, s, n = mean_sd(r['payout_to_avg4'] for r in post)
    print(f"  шесть решений 1К2025–2К2026 (база целиком после покупки Росбанка): {min(r['payout_to_avg4'] for r in post) * 100:.1f}–{max(r['payout_to_avg4'] for r in post) * 100:.1f} %, среднее {m * 100:.2f} %, σ {s * 100:.2f} п.п.; "
          f"с 4К2024 (в базе два квартала до сделки): среднее {statistics.fmean(r['payout_to_avg4'] for r in rows) * 100:.2f} %")
    mq, sq, _ = mean_sd(r['payout_to_quarter'] for r in rows)
    print(f"  к операционной прибыли самого квартала (семь решений): {min(r['payout_to_quarter'] for r in rows) * 100:.1f}–{max(r['payout_to_quarter'] for r in rows) * 100:.1f} %, среднее {mq * 100:.2f} %, σ {sq * 100:.2f} п.п. — разброс базы «средняя четырёх» {s * 100:.2f} п.п.")
    y25 = sum(r['pool_bn'] for r in rows if r['period'].endswith('2025')); np25 = sum(OPd[p]['ni_shareholders'] for p in QS[4:8]); rp25 = sum(OPd[p]['ni_sh_reported'] for p in QS[4:8])
    h26 = sum(r['pool_bn'] for r in rows if r['period'].endswith('2026')); np26 = sum(OPd[p]['ni_shareholders'] for p in QS[8:10]); rp26 = sum(OPd[p]['ni_sh_reported'] for p in QS[8:10])
    print(f"  за год прибыли: 2025 — {y25:.3f} млрд ₽ = {y25 / np25 * 100:.1f} % операционной ({np25:.3f}) и {y25 / rp25 * 100:.1f} % отчётной ({rp25:.3f}); 1П2026 — {h26:.3f} = {h26 / np26 * 100:.1f} % операционной и {h26 / rp26 * 100:.1f} % отчётной ({rp26:.1f}; потолок политики 30 % — к году)")
    seq = [r['dps'] for r in rows]
    print('  лестница DPS: ' + ' → '.join(f"{x:.1f}" for x in seq) + ' ₽; шаги: ' + ', '.join(f"{b - a:+.1f}" for a, b in zip(seq, seq[1:])))

    print()
    print('Прочие движения капитала акционеров (МСФО, отчёт об изменениях капитала), млрд ₽ за квартал:')
    er = []
    for p in QS:
        sbp = fq('eqf_sbp__shareholders', p, 0.0); bb = fq('eqf_buyback__shareholders', p, 0.0)
        oth = fq('eqf_other__shareholders', p, 0.0) + fq('eqf_minority_buyout__shareholders', p, 0.0) + fq('eqf_subs_contrib__shareholders', p, 0.0)
        ex = fq('sbp_expense_pos', p, 0.0)
        er.append(dict(period=p, sbp_reserve_credit=sbp, buyback=bb, other=oth, net=sbp + bb + oth, sbp_expense_pnl=ex, bought_back_th=fq('shares_bought_back_th', p, 0.0), transferred_ltip_th=fq('shares_transferred_ltip_th', p, 0.0)))
        print(f"  {p}: резерв выплат акциями {sbp:+6.2f}; выкуп {bb:+7.2f}; прочее (операции с НДУ, взносы) {oth:+6.2f} → итого {sbp + bb + oth:+7.2f} | расход на мотивацию в ОПУ {ex:5.2f}; выкуплено {fq('shares_bought_back_th', p, 0.0) / 1000:6.2f} млн акций")
    write_csv('equity_other_movements.csv', er)
    for name, ps in (('семь кварталов 4К2024–2К2026', B9), ('четыре квартала 3К2025–2К2026 (выкуп возобновлён с 3К2025)', QS[6:10]), ('1П2026', QS[8:10])):
        sel = [r for r in er if r['period'] in ps]
        print(f"  {name}: резерв {sum(r['sbp_reserve_credit'] for r in sel):+.2f}, выкуп {sum(r['buyback'] for r in sel):+.2f}, прочее {sum(r['other'] for r in sel):+.2f} → итого {sum(r['net'] for r in sel):+.2f} ({sum(r['net'] for r in sel) / len(sel):+.2f} за квартал; "
              f"{sum(r['net'] for r in sel) / len(sel) / 756.8 * 100:+.3f} % капитала якоря за квартал)")

    print()
    print('Квартальный профиль (операционный базис): есть ли сезонность, которую не несут базы «к тому же кварталу»')
    K = table(read_csv('stage1', 'mgmt', 'mgmt_kpi.csv'))
    prof = []
    for p in QS[4:]:
        y, h = qparts(p); o = OPd[p]; mkp = f"{y}Q{h}"
        prof.append(dict(period=p, ni_sh=o['ni_shareholders'], nii=o['nii'], fees=o['fees'], ins=o['ins'], opex=-o['opex'], llp=-o['llp_debt_fa'], misc=o['misc_net'],
                         cor_mgmt=K['cor_total_exact'][mkp][0], nim_mgmt=K['nim_exact'][mkp][0], cir_mgmt=K['cir_exact'][mkp][0]))
        print(f"  {p}: прибыль {o['ni_shareholders']:6.2f}; услуги {o['fees']:5.1f}; страхование {o['ins']:5.1f}; расходы {-o['opex']:6.1f}; резервы {-o['llp_debt_fa']:5.1f}; CoR упр. {K['cor_total_exact'][mkp][0]:.2f} %; ЧПМ упр. {K['nim_exact'][mkp][0]:.2f} %; C/I упр. {K['cir_exact'][mkp][0]:.2f} %")
    write_csv('quarter_profile.csv', prof)
    y25 = {h: OPd[qlabel(2025, h)] for h in (1, 2, 3, 4)}
    tot = lambda k: sum(abs(y25[h][k]) for h in (1, 2, 3, 4))
    print('  доли кварталов в сумме 2025 года: ' + '; '.join(f"{nm}: " + ' / '.join(f"{abs(y25[h][k]) / tot(k) * 100:.1f}" for h in (1, 2, 3, 4)) for nm, k in (('услуги', 'fees'), ('страхование', 'ins'), ('расходы', 'opex'), ('ЧПД', 'nii'), ('прибыль', 'ni_shareholders'))))
    SS = json.load(open(rel('stage1', 'regimes', 'season_sigma.json'), encoding='utf-8'))['season_year_ratio']
    for kname in ('2019-2025', '2019-2025 без 2020 и 2022', '2021, 2023-2025'):
        v = SS[kname]
        print(f"  лист режимов, CoR квартала к CoR года, {kname}: " + ' / '.join(f"{v[str(h)][0]:.2f} (±{v[str(h)][1]:.2f})" for h in (1, 2, 3, 4)))

    print()
    print('Гайденс 2026 — узлы фактов (LEAD-2 §10 п. 5) и ожидание гейта guidance_gap:')
    G = [r for r in read_csv('stage1', 'mgmt', 'guidance.csv') if r['target_year'] == '2026' and r['as_of'] == '2026-08-11' and r['metric'] in ('op_np_growth', 'dps_growth') and r['low'] and not r['high']]
    for r in G:
        print(f"  {r['metric']}: «{r['text']}» ({r['doc']}, с. {r['page']}; {r['as_of']})")
    GS = [r for r in read_csv('stage1', 'mgmt', 'guidance.csv') if 'ROE' in r['text'] and r['doc'].endswith('strategy_shareholder_value.pdf')]
    for r in GS[:3]:
        print(f"  стратегия: {r['metric']} [{r['target_year']}]: «{r['text'][:160]}» ({r['doc']}, с. {r['page']})")
    exp = list(csv.DictReader(open(os.path.join(OUT, 'guidance_2026.csv'), encoding='utf-8')))
    for r in exp:
        print(f"  ожидание, режим {r['regime']:9s}: операционная прибыль 2026 {float(r['np_2026']):.1f} ({float(r['growth']) * 100:+.1f} %); DPS за год {float(r['dps_2026']):.2f} ₽ ({float(r['dps_growth']) * 100:+.1f} %); ROE движка {float(r['roe_engine']) * 100:.1f} %")
    np25 = sum(OPd[p]['ni_shareholders'] for p in QS[4:8])
    g_op = next(r for r in G if r['metric'] == 'op_np_growth'); g_dps = next(r for r in G if r['metric'] == 'dps_growth')
    nodes = {'basis': 'issuer-defined (операционная прибыль акционеров); DPS — на акцию после дробления', 'year': 2026, 'as_of': '2026-08-11',
             'items': {
                 'op_np_growth': {'v': 0.20, 'kind': 'min', 'scope': 'group', 'text': 'рост операционной чистой прибыли на 20% и выше', 'date': g_op['as_of'], 'event': 'МСФО 2К26',
                                  'src': f"{g_op['doc']}, с. {g_op['page']}, sha256 {g_op['sha256'][:16]}", 'calc': f"база — операционная прибыль акционеров 2025 года {np25:.3f} млрд ₽ (Databook PL!AX37); порог 2026 года — {np25 * 1.2:.1f}"},
                 'dps_growth': {'v': 0.20, 'kind': 'min', 'scope': 'group', 'text': 'увеличение совокупных дивидендов на акцию за год более чем на 20%', 'date': g_dps['as_of'], 'event': 'МСФО 2К26',
                                'src': f"{g_dps['doc']}, с. {g_dps['page']}, sha256 {g_dps['sha256'][:16]}", 'calc': 'база — 14,90 ₽ за 2025 год (3,3 + 3,5 + 3,6 + 4,5); порог — более 17,88 ₽ за 2026 год'},
                 'roe_target': {'v': 0.30, 'kind': 'point', 'tol': 0.005, 'scope': 'group', 'text': 'целевой ROE ~30%', 'date': '2026-07-21', 'event': 'Стратегия повышения акционерной стоимости (СД 21.07.2026)',
                                'src': 'primary/strategy_shareholder_value.pdf, с. 9', 'calc': 'цель стратегии, не прогноз 2026 года; ROE эмитента — к операционному капиталу; в гейт не входит (checks.guidance_items)'},
                 'nim': {'v': None, 'calc': 'гайденса по ЧПМ на 2026 год нет'}, 'cor_max': {'v': None, 'calc': 'гайденса по CoR на 2026 год нет'}, 'cir': {'v': None, 'calc': 'гайденса по C/I на 2026 год нет'}}}
    json.dump(nodes, open(os.path.join(OUT, 'guidance_nodes_proposal.json'), 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=1)
    print()
    print('записано: out/dividend_payout.csv, out/equity_other_movements.csv, out/quarter_profile.csv, out/guidance_nodes_proposal.json')
