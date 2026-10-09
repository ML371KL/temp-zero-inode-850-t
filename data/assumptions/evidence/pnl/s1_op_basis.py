# -*- coding: utf-8 -*-
"""Шаг 1. Строки движка на ОПЕРАЦИОННОМ базисе по кварталам 1К2024–2К2026 (LEAD-2 §1 пп. 2–4).
Читает stage1/ifrs/{ifrs_quarterly,three_profits}.csv, stage1/worlds/world_paths_quarterly.csv,
research/facts/cbr_key_rate_quarterly.csv и inputs/. Пишет op_basis_quarterly.csv (в каталог листа),
out/noncore_alternatives.csv, out/nci_check.csv, out/misc_components.csv, out/tax_effective.csv,
out/noncore_center.json, out/pnl_quarterly_proposal.json. Печатает числа разделов 1, 4, 5, 6 отчёта."""
import json, sys
from pnl_lib import *

L = load_yaml(ROOT, 'stage1', 'calib', 'pnl', 'inputs', 'lead_decisions.yaml')
S_GRP = float(L['catalytic_group_share'])            # доля Группы в «Каталитик Пипл»
T_STAT = 0.25                                        # законная ставка налога на прибыль с 2025 года
Qd = table(read_csv('stage1', 'ifrs', 'ifrs_quarterly.csv'))
TP = table(read_csv('stage1', 'ifrs', 'three_profits.csv'))
YD = {r['period']: (float(r['value']), f"{r['doc']}, с. {r['page']}") for r in read_csv('stage1', 'calib', 'pnl', 'inputs', 'yandex_dividends.csv')}
BLOCK_QS = ['2Q2025', '3Q2025', '4Q2025', '1Q2026', '2Q2026']


def q(m, p, default=None):
    v = Qd.get(m, {}).get(p)
    return v[0] if v else default


def src(m, p):
    v = Qd.get(m, {}).get(p)
    return v[1] if v else ''


def op_line(p, t_int=T_STAT, s_int=1.0):
    """Строки движка квартала p. t_int — ставка налогового щита по процентам под пакет; s_int — доля акционеров Группы
    в компании-заёмщике (1 = долг на компаниях со 100 % владения; 0,5001 = долг на «Каталитик Пипл»)."""
    r = dict(period=p)
    r['nii'] = q('nii', p); r['fees'] = q('fees_net', p); r['ins'] = q('ins_net', p)
    r['opex'] = sum(q(m, p) for m in ('opex_tech', 'opex_marketing', 'opex_servicing', 'opex_admin'))
    r['llp_debt_fa'] = q('llp_debt_fa', p)
    r['pbt_reported'] = q('pbt', p); r['tax_reported'] = q('tax', p); r['ni_reported'] = q('np', p)
    r['nci_reported'] = q('np_nci', p); r['ni_sh_reported'] = q('np_shareholders', p)
    r['misc_net_reported'] = r['pbt_reported'] - (r['nii'] + r['fees'] + r['ins'] + r['opex'] + r['llp_debt_fa'])
    blk = p in BLOCK_QS
    reval = TP['tp_yandex_reval_gross_100'][p][0] if blk else 0.0
    div = YD[p][0] if blk else 0.0
    y_sh = TP['tp_adj_yandex_after_tax_sh'][p][0] if blk else 0.0         # эффект пакета после налога, доля акционеров (эмитент)
    i_sh = TP['tp_adj_interest_loans_sh'][p][0] if blk else 0.0           # проценты по займам после налога, доля акционеров (эмитент; < 0)
    y_100 = y_sh / S_GRP                                                  # эффект пакета после налога, 100 %
    R = -i_sh / ((1 - t_int) * s_int)                                     # проценты по долгу под пакет до налога, 100 %  → noncore_net
    tax_y = y_100 - (reval + div)                                         # налог по переоценке и дивидендам (знак строки налога: < 0 — расход)
    tax_i = t_int * R                                                     # налоговый щит процентов (> 0 — уменьшает налог отчёта)
    nci_blk = y_100 * (1 - S_GRP) - (1 - s_int) * R * (1 - t_int)         # доля НДУ в блоке
    r.update(yandex_reval=reval, yandex_dividends=div, issuer_adj_yandex_sh=y_sh, issuer_adj_interest_sh=i_sh)
    r['misc_net'] = r['misc_net_reported'] - reval - div
    r['noncore_net'] = R
    r['fvc'] = 0.0; r['fvr'] = 0.0; r['one_off'] = 0.0
    r['pbt'] = r['pbt_reported'] - reval - div + R
    r['tax'] = r['tax_reported'] - tax_y - tax_i
    r['ni'] = r['pbt'] + r['tax']
    r['nci'] = r['nci_reported'] - nci_blk
    r['ni_shareholders'] = r['ni'] - r['nci']
    r['issuer_op_np'] = TP['tp_op_np_issuer'][p][0] if blk else q('op_np', p)
    r['test_ni_sh_minus_issuer'] = r['ni_shareholders'] - r['issuer_op_np']
    # узел investment_block (100 %, до налога → налог → НДУ → доля акционеров)
    r['ib_reval'] = reval; r['ib_dividends'] = div; r['ib_interest'] = -R
    r['ib_tax'] = tax_y + tax_i; r['ib_nci'] = -nci_blk
    r['ib_total_sh'] = reval + div - R + tax_y + tax_i - nci_blk
    r['ib_issuer_sh'] = y_sh + i_sh
    r['id_reported_eq_op_plus_block'] = r['ni_sh_reported'] - (r['ni_shareholders'] + r['ib_total_sh'])
    r['id_pbt'] = r['pbt'] - (r['nii'] + r['fees'] + r['ins'] + r['opex'] + r['llp_debt_fa'] + r['misc_net'] + r['noncore_net'])
    r['etr'] = -r['tax'] / r['pbt']; r['etr_reported'] = -r['tax_reported'] / r['pbt_reported']
    r['nci_share'] = r['nci'] / r['ni']
    return r


rows = [op_line(p) for p in QS]
COLS = ['period', 'nii', 'fees', 'ins', 'opex', 'llp_debt_fa', 'fvc', 'misc_net', 'noncore_net', 'fvr', 'one_off', 'pbt', 'tax', 'ni', 'nci',
        'ni_shareholders', 'issuer_op_np', 'test_ni_sh_minus_issuer', 'id_pbt', 'pbt_reported', 'tax_reported', 'ni_reported', 'nci_reported',
        'ni_sh_reported', 'misc_net_reported', 'yandex_reval', 'yandex_dividends', 'issuer_adj_yandex_sh', 'issuer_adj_interest_sh',
        'ib_reval', 'ib_dividends', 'ib_interest', 'ib_tax', 'ib_nci', 'ib_total_sh', 'ib_issuer_sh', 'id_reported_eq_op_plus_block',
        'etr', 'etr_reported', 'nci_share']
write_csv(os.path.join(OUT, 'op_basis_quarterly.csv'), [{c: (round(r[c], 6) if isinstance(r[c], float) else r[c]) for c in COLS} for r in rows], COLS)

if __name__ == '__main__':
    print('=' * 110)
    print('ШАГ 1. ОПУ на операционном базисе, млрд ₽ (знаки отчёта: расходы и резервы — минус)')
    print('Допущения центра: долг под пакет — на компаниях со 100 % владения (s_int = 1), щит по процентам 25 %; доля Группы в «Каталитик Пипл»', S_GRP)
    hdr = ['nii', 'fees', 'ins', 'opex', 'llp_debt_fa', 'misc_net', 'noncore_net', 'pbt', 'tax', 'ni', 'nci', 'ni_shareholders', 'issuer_op_np', 'test_ni_sh_minus_issuer', 'id_pbt']
    print('квартал ' + ' '.join(h[:11].rjust(11) for h in hdr))
    for r in rows:
        print(r['period'].ljust(8) + ' '.join(f"{r[h]:11.3f}" for h in hdr))
    print()
    print('Инвестиционный блок (2К2025–2К2026): отчётная акционерам = операционная + блок')
    hb = ['ni_sh_reported', 'ni_shareholders', 'ib_reval', 'ib_dividends', 'ib_interest', 'ib_tax', 'ib_nci', 'ib_total_sh', 'ib_issuer_sh', 'id_reported_eq_op_plus_block']
    print('квартал ' + ' '.join(h[:13].rjust(13) for h in hb))
    for r in rows:
        if r['period'] in BLOCK_QS:
            print(r['period'].ljust(8) + ' '.join(f"{r[h]:13.4f}" for h in hb))
    a = next(r for r in rows if r['period'] == '2Q2026')
    print()
    print(f"ТЕСТ: ni_shareholders движка за 2К2026 = {a['ni_shareholders']:.6f}; Databook PL!AZ107 = {a['issuer_op_np']:.6f}; разность {a['test_ni_sh_minus_issuer']:.2e}")
    print('ТЕСТ: максимум |ni_shareholders − операционная прибыль эмитента| по 10 кварталам =', f"{max(abs(r['test_ni_sh_minus_issuer']) for r in rows):.2e}")
    print('ТЕСТ: максимум |тождество PBT| =', f"{max(abs(r['id_pbt']) for r in rows):.2e}", '; максимум |отчётная − (операционная + блок)| =', f"{max(abs(r['id_reported_eq_op_plus_block']) for r in rows):.2e}")
    print('Сверка состава «прочего» отчёта (остаток PBT против суммы строк ОПУ): ')
    comp = []
    for r in rows:
        p = r['period']
        parts = dict(assoc_share=q('assoc_share', p, 0.0), fx_net=q('fx_net', p, 0.0), gl_fin_instruments=q('gl_fin_instruments', p, 0.0),
                     other_provisions=q('other_provisions', p, 0.0), other_income=q('other_income', p, 0.0))
        s = sum(parts.values())
        gl_ex = parts['gl_fin_instruments'] - r['yandex_reval'] - r['yandex_dividends']
        comp.append(dict(period=p, **parts, gl_ex_yandex=gl_ex, sum_lines=s, misc_net_reported=r['misc_net_reported'], rounding_gap=r['misc_net_reported'] - s,
                         misc_net=r['misc_net']))
        print(f"  {p}: доля в прибыли ассоц. {parts['assoc_share']:6.2f}; курсовые {parts['fx_net']:6.2f}; фин. инструменты без пакета {gl_ex:7.2f} (отчёт {parts['gl_fin_instruments']:6.2f}); "
              f"прочие резервы {parts['other_provisions']:6.2f}; прочие доходы {parts['other_income']:6.2f} | Σ строк {s:7.2f}, остаток PBT {r['misc_net_reported']:7.3f}, округление {r['misc_net_reported'] - s:6.3f} | прочее опер. {r['misc_net']:7.3f}")
    write_csv('misc_components.csv', comp)

    # ---------- альтернативные допущения о возврате процентов (noncore_net)
    print()
    print('Альтернативы вывода noncore_net из поправки эмитента «проценты по займам» (после налога, доля акционеров):')
    alts = [('центр: 100 % владения, щит 25 %', T_STAT, 1.0), ('100 % владения, без налогового щита', 0.0, 1.0),
            ('долг на «Каталитик Пипл» (50,01 %), щит 25 %', T_STAT, S_GRP), ('долг на «Каталитик Пипл», без щита', 0.0, S_GRP)]
    alt_rows = []
    for name, t, s in alts:
        rr = {p: op_line(p, t, s) for p in BLOCK_QS}
        rec = dict(assumption=name, tax_shield=t, group_share=s)
        for p in BLOCK_QS:
            rec[f'noncore_{p}'] = rr[p]['noncore_net']; rec[f'nci_{p}'] = rr[p]['nci']; rec[f'etr_{p}'] = rr[p]['etr']
        rec['nonfin_interest_exceeded'] = ', '.join(p for p in BLOCK_QS if rr[p]['noncore_net'] > -q('ie_nonfin_borrowings', p) + 0.05) or 'нет'
        alt_rows.append(rec)
        print(f"  {name:48s}: " + '  '.join(f"{p} {rr[p]['noncore_net']:5.2f}" for p in BLOCK_QS) + f" | НДУ опер. 2К26 {rr['2Q2026']['nci']:5.2f} | больше всех процентов нефин. компаний: {rec['nonfin_interest_exceeded']}")
    print('  все процентные расходы нефинансовых компаний (верхняя граница, строка ОПУ):       ' + '  '.join(f"{p} {-q('ie_nonfin_borrowings', p):5.2f}" for p in BLOCK_QS))
    write_csv('noncore_alternatives.csv', alt_rows)
    lo = min(op_line('2Q2026', t, s)['noncore_net'] for _, t, s in alts); hi = max(op_line('2Q2026', t, s)['noncore_net'] for _, t, s in alts)
    print(f"  разброс noncore_net 2К2026 по допущениям: {lo:.2f}…{hi:.2f} (центр {a['noncore_net']:.3f}); прибыль акционеров от допущений не зависит (тождество)")

    # ---------- НДУ на операционном базисе (п. 6 задания)
    print()
    print('НДУ на операционном базисе, млрд ₽ за квартал:')
    nci_rows = []
    for r in rows:
        p = r['period']
        if p not in BLOCK_QS: continue
        assoc = q('assoc_share', p, 0.0)
        nci_assoc = assoc * (1 - S_GRP)
        alt = op_line(p, T_STAT, S_GRP)['nci']
        nci_rows.append(dict(period=p, nci_reported=r['nci_reported'], nci_share_of_yandex=-r['ib_nci'], nci_operating=r['nci'], ni_operating=r['ni'], nci_share=r['nci_share'],
                             assoc_share_100=assoc, nci_part_of_assoc=nci_assoc, residual_other=r['nci'] - nci_assoc,
                             nci_if_debt_at_catalytic=alt, residual_if_debt_at_catalytic=alt - nci_assoc))
        print(f"  {p}: отчётная НДУ {r['nci_reported']:7.3f} − доля в эффекте пакета {-r['ib_nci']:7.3f} = операционная {r['nci']:6.3f} ({r['nci_share'] * 100:4.2f} % прибыли {r['ni']:7.3f}); "
              f"из неё 49,99 % доли в прибыли «Точки» и «Селектела» {nci_assoc:5.2f}, остаток {r['nci'] - nci_assoc:5.2f} | если бы долг был на «Каталитике»: {alt:5.2f} (остаток {alt - nci_assoc:5.2f})")
    write_csv('nci_check.csv', nci_rows)
    h1 = [r for r in rows if r['period'] in ('1Q2026', '2Q2026')]
    l4 = [r for r in rows if r['period'] in ('3Q2025', '4Q2025', '1Q2026', '2Q2026')]
    print(f"  доля НДУ в операционной прибыли: 1П2026 {sum(r['nci'] for r in h1) / sum(r['ni'] for r in h1) * 100:.2f} %; четыре квартала 3К25–2К26 {sum(r['nci'] for r in l4) / sum(r['ni'] for r in l4) * 100:.2f} %; "
          f"сумма НДУ за четыре квартала {sum(r['nci'] for r in l4):.2f}, за 1П2026 {sum(r['nci'] for r in h1):.2f}")

    # ---------- налог (п. 4)
    print()
    print('Эффективная ставка налога, операционный базис (и отчётный):')
    tx = []
    for name, ps in (('2025 год', ['1Q2025', '2Q2025', '3Q2025', '4Q2025']), ('2П2025', ['3Q2025', '4Q2025']), ('1П2026', ['1Q2026', '2Q2026']), ('четыре квартала 3К25–2К26', ['3Q2025', '4Q2025', '1Q2026', '2Q2026']),
                     ('2024 год (ставка 20 %)', ['1Q2024', '2Q2024', '3Q2024', '4Q2024'])):
        sel = [r for r in rows if r['period'] in ps]
        e = -sum(r['tax'] for r in sel) / sum(r['pbt'] for r in sel); er = -sum(r['tax_reported'] for r in sel) / sum(r['pbt_reported'] for r in sel)
        tx.append(dict(window=name, pbt_op=sum(r['pbt'] for r in sel), tax_op=sum(r['tax'] for r in sel), etr_op=e, pbt_reported=sum(r['pbt_reported'] for r in sel), tax_reported=sum(r['tax_reported'] for r in sel), etr_reported=er))
        print(f"  {name:28s}: PBT опер. {tx[-1]['pbt_op']:8.3f}, налог {tx[-1]['tax_op']:8.3f}, ставка {e * 100:5.2f} % (отчётная {er * 100:5.2f} %)")
    for r in rows:
        print(f"    {r['period']}: {r['etr'] * 100:5.2f} % (отчётная {r['etr_reported'] * 100:5.2f} %)")
    write_csv('tax_effective.csv', tx)
    gap25 = tx[0]['etr_op'] - T_STAT; gap26 = tx[2]['etr_op'] - T_STAT
    print(f"  эффективная − законная: 2025 {gap25 * 100:+.2f} п.п., 1П2026 {gap26 * 100:+.2f} п.п.; среднее {(gap25 + gap26) / 2 * 100:+.2f} п.п.; шесть кварталов 1К25–2К26 "
          f"{(-sum(r['tax'] for r in rows[4:10]) / sum(r['pbt'] for r in rows[4:10]) - T_STAT) * 100:+.2f} п.п.")
    sbp25 = sum(q('sbp_expense_pos', p) for p in ['1Q2025', '2Q2025', '3Q2025', '4Q2025']); as25 = sum(q('assoc_share', p) for p in ['1Q2025', '2Q2025', '3Q2025', '4Q2025'])
    print(f"  ориентиры разрыва за 2025: необлагаемая доля в прибыли ассоциированных {as25:.1f} × 25 % = {as25 * 0.25 / tx[0]['pbt_op'] * 100:.2f} п.п. вниз; расход на мотивацию {sbp25:.1f} × 25 % = {sbp25 * 0.25 / tx[0]['pbt_op'] * 100:.2f} п.п. вверх (если не вычитается) [Р, порядок]")

    # ---------- «прочее» (п. 5)
    print()
    print('«Прочее» на операционном базисе (misc_net), млрд ₽:')
    m = {r['period']: r['misc_net'] for r in rows}
    for name, ps in (('2024', QS[0:4]), ('2025', QS[4:8]), ('1П2026', QS[8:10]), ('четыре квартала 3К25–2К26', QS[6:10]), ('шесть кварталов 1К25–2К26', QS[4:10])):
        s = sum(m[p] for p in ps)
        print(f"  {name:28s}: Σ {s:7.2f}; в годовом выражении {s * 4 / len(ps):7.2f}")
    six = sorted(m[p] for p in QS[4:10])
    med = (six[2] + six[3]) / 2
    print(f"  медиана квартала по шести кварталам 1К25–2К26: {med:.2f} → {med * 4:.1f} в год; минимум {six[0]:.2f}, максимум {six[-1]:.2f}")
    oi = {p: q('other_income', p, 0.0) for p in QS}
    oi_norm = statistics.median([oi[p] for p in QS if p not in ('3Q2024', '4Q2024', '2Q2025')])
    print(f"  разовые в «прочих доходах»: 3К2024 {oi['3Q2024']:.1f} (выгодная покупка Росбанка 8,7), 4К2024 {oi['4Q2024']:.1f}, 2К2025 {oi['2Q2025']:.1f} (сделка «Каталитик»); медиана прочих доходов остальных кварталов {oi_norm:.1f}")
    ex = sum(m[p] for p in QS[4:10]) - (oi['2Q2025'] - oi_norm)
    print(f"  шесть кварталов без разового дохода 2К2025: Σ {ex:.2f}; в годовом выражении {ex * 4 / 6:.2f}")
    byq = {h: [m[p] for p in QS[4:10] if qparts(p)[1] == h] for h in (1, 2, 3, 4)}
    print('  по номеру квартала (2025–2026): ' + '; '.join(f"{h}К: {', '.join(f'{x:.1f}' for x in v)}" for h, v in byq.items()))
    cm = {c['period']: c for c in comp}
    last4 = sum(m[p] for p in QS[6:10]); assoc_y = sum(cm[p]['assoc_share'] for p in QS[6:10])
    misc_center = round(med * 4)
    print(f"  ЦЕНТР other.misc_net_real = медиана квартала × 4, до целого: {misc_center}; ось: низ — доля в прибыли ассоциированных за четыре квартала {assoc_y:.1f} → {round(assoc_y)}, верх — симметрично {2 * misc_center - round(assoc_y)} (сумма четырёх последних кварталов {last4:.1f} — внутри)")
    json.dump({'center': misc_center, 'low': round(assoc_y), 'high': 2 * misc_center - round(assoc_y), 'median_q': med, 'last4': last4, 'h1_2026': m['1Q2026'] + m['2Q2026'], 'six_ex_oneoff_annual': ex * 4 / 6,
               'etr_gap_6q': -sum(r['tax'] for r in rows[4:10]) / sum(r['pbt'] for r in rows[4:10]) - T_STAT, 'etr_2025': tx[0]['etr_op'], 'etr_1h26': tx[2]['etr_op'],
               'nci_share_1h26': sum(r['nci'] for r in h1) / sum(r['ni'] for r in h1), 'nci_share_last4': sum(r['nci'] for r in l4) / sum(r['ni'] for r in l4), 'nci_1h26': sum(r['nci'] for r in h1)},
              open(os.path.join(OUT, 'misc_tax_nci.json'), 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=1)
    for nm, key_ in (('доля в прибыли ассоциированных', 'assoc_share'), ('курсовые разницы', 'fx_net'), ('финансовые инструменты без пакета', 'gl_ex_yandex'), ('прочие резервы', 'other_provisions'), ('прочие доходы', 'other_income')):
        v6 = [cm[p][key_] for p in QS[4:10]]
        print(f"    {nm:36s}: шесть кварталов Σ {sum(v6):6.2f} (в год {sum(v6) * 4 / 6:6.2f}); 1П2026 {cm['1Q2026'][key_] + cm['2Q2026'][key_]:6.2f}")

    # ---------- центр noncore.result_real и правило «остаток года якоря» (п. 1)
    _root = HERE                                              # корень репозитория: каталог с model/cell.py
    while not os.path.exists(os.path.join(_root, 'model', 'cell.py')) and os.path.dirname(_root) != _root:
        _root = os.path.dirname(_root)
    sys.path.insert(0, _root)
    from model.cell import _year_sum_table
    W = [r for r in read_csv('stage1', 'worlds', 'world_paths_quarterly.csv') if r['world'] == 'H' and r['period'] != 'LT']
    key = {r['period']: float(r['key_avg']) / 100 for r in W}; cpi = {r['period']: float(r['cpi_yoy_avg']) / 100 for r in W}
    KR = {r['period']: r for r in read_csv('research', 'facts', 'cbr_key_rate_quarterly.csv')}
    key_anchor = float(KR['2026Q2']['key_avg_pct']) / 100
    R_anchor = a['noncore_net']; R_1h = sum(r['noncore_net'] for r in h1)
    SPREAD = 0.01                                             # [В] спред долга к ключевой: облигации нефинансовых компаний «ключевая + 1,0 п.п.» (МСФО 6М2026, прим. 21, с. 79)
    idx, I = {}, 1.0
    for r in W:
        I *= (1 + cpi[r['period']]) ** 0.25
        idx[r['period']] = I
    years = range(2026, 2037)
    nom, real, iavg, kavg = {}, {}, {}, {}
    for y in years:
        ps = [p for p in idx if p.startswith(str(y))]
        kavg[y] = statistics.fmean(key[p] for p in ps); iavg[y] = statistics.fmean(idx[p] for p in ps)
        nom[y] = 4 * R_anchor * (kavg[y] + SPREAD) / (key_anchor + SPREAD)          # постоянный в рублях долг × (ключевая мира H + спред)
        real[y] = nom[y] / iavg[y]
    book_2026 = R_1h + 2 * R_anchor * (kavg[2026] + SPREAD) / (key_anchor + SPREAD) / iavg[2026]
    traj_A = {'2026': round(book_2026, 2)}
    traj_A.update({str(y): round(real[y], 2) for y in years if y >= 2027})
    traj_A['LT'] = traj_A['2036']
    traj_B = {'2026': round(R_1h + 2 * R_anchor, 2), 'LT': round(4 * R_anchor, 2)}
    print()
    print('Центр noncore.result_real (млрд ₽ в год, цены 2026), мир H:')
    print(f"  факт: 1К2026 {h1[0]['noncore_net']:.4f}, 2К2026 {R_anchor:.4f}; 1П2026 {R_1h:.4f}; уровень квартала якоря × 4 = {4 * R_anchor:.3f}; средняя ключевая 2К2026 {key_anchor * 100:.2f} %")
    for y in years:
        print(f"  {y}: ключевая мира H {kavg[y] * 100:5.2f} %, индекс цен (ср.) {iavg[y]:.4f}, проценты по долгу (номинал) {nom[y]:6.3f}, в ценах 2026 {real[y]:6.3f}")
    print('  вариант A (постоянный в рублях долг × ключевая мира H): ', json.dumps(traj_A, ensure_ascii=False))
    print('  вариант B (ровно в реальном выражении): ', json.dumps(traj_B, ensure_ascii=False))
    for name, tr in (('A', traj_A), ('B', traj_B), ('книга 0 при фактах-возврате (центр LEAD-1 B1)', {'LT': 0.0}), ('ловушка: факты = переоценка и дивиденды пакета, книга 0', {'LT': 0.0})):
        tab = _year_sum_table(tr, range(2025, 2037))
        fact = R_1h if 'ловушка' not in name else sum(op_line(p)['yandex_reval'] + op_line(p)['yandex_dividends'] for p in ('1Q2026', '2Q2026'))
        rest = (tab[2026] - fact) / 2
        print(f"  остаток года якоря (cell.py:255–256), {name}: книга 2026 = {tab[2026]:.3f}, факт 1П2026 = {fact:.3f} → 3К и 4К2026 по {rest:+.3f} (факт 2К2026 {R_anchor:.3f})")
    # цена выбора A против B: приведённая стоимость разности после налога в доле акционеров, грубо
    tabA = _year_sum_table(traj_A, range(2026, 2037)); tabB = _year_sum_table(traj_B, range(2026, 2037))
    # проверка траектории A в мирах N и M: номинал 2036 года против «постоянный долг × (ключевая мира + спред)»
    for Wn in ('N', 'H', 'M'):
        Ww = [r for r in read_csv('stage1', 'worlds', 'world_paths_quarterly.csv') if r['world'] == Wn and r['period'] != 'LT']
        Iw, acc = 1.0, []
        for r in Ww:
            Iw *= (1 + float(r['cpi_yoy_avg']) / 100) ** 0.25
            if r['period'].startswith('2036'): acc.append((Iw, float(r['key_avg']) / 100))
        i36 = statistics.fmean(a_[0] for a_ in acc); k36 = statistics.fmean(a_[1] for a_ in acc)
        print(f"  мир {Wn}, 2036: траектория A даёт {traj_A['2036'] * i36:.2f} млрд ₽ номинала (индекс цен {i36:.3f}); «долг × ставка» = {4 * R_anchor * (k36 + SPREAD) / (key_anchor + SPREAD):.2f} (ключевая {k36 * 100:.1f} %)")
    print(f"  разность B − A в номинале до налога: 2030 — {traj_B['LT'] * iavg[2030] - nom[2030]:.2f}; 2036 — {traj_B['LT'] * iavg[2036] - nom[2036]:.2f}")
    nci_contrib = 72.809      # взнос НДУ в капитал дочерних компаний, 2К2025 (МСФО 6М2025, с. 7; лист ifrs_all: eqf_subs_contrib__nci)
    for pq, kq in (('3Q2025', '2025Q3'), ('4Q2025', '2025Q4'), ('1Q2026', '2026Q1'), ('2Q2026', '2026Q2')):
        rq = op_line(pq)['noncore_net']
        print(f"  порядок ставки: {pq} проценты {rq:.3f} × 365/{qdays(pq)} / {nci_contrib} = {rq * 365 / qdays(pq) / nci_contrib * 100:.1f} % годовых при средней ключевой {float(KR[kq]['key_avg_pct']):.2f} %")
    div4 = sum(YD[pq][0] for pq in ('3Q2025', '4Q2025', '1Q2026', '2Q2026')); int4 = sum(op_line(pq)['noncore_net'] for pq in ('3Q2025', '4Q2025', '1Q2026', '2Q2026'))
    print(f"  дивиденды по пакету за четыре квартала 3К25–2К26: {div4:.2f} (100 %), доля группы {div4 * S_GRP:.2f}; проценты под пакет за те же кварталы {int4:.2f}")
    k = 0.185; g = (1 + 0.055) * (1 + 0.015) - 1; after = (1 - 0.244) * (1 - 0.024)
    pv = sum((tabB[y] - tabA[y]) * iavg[y] * after / (1 + k) ** (i + 0.75) for i, y in enumerate(range(2027, 2037)))
    tv = (tabB[2036] - tabA[2036]) * iavg[2036] * after * (1 + g) / (k - g) / (1 + k) ** 10.25
    print(f"  цена выбора B вместо A: PV разности 2027–2036 ≈ {pv:.1f} млрд ₽ + терминал ≈ {tv:.1f} млрд ₽ = {pv + tv:.1f} млрд ₽ ≈ {(pv + tv) / 2.6827:.1f} ₽ на акцию [Р, порядок: k = 18,5 %, g = {g * 100:.2f} %]")
    ax = float(L['noncore_axis_after_tax_sh']) / after
    print(f"  ось: ±{L['noncore_axis_after_tax_sh']} млрд ₽ в год в доле акционеров после налога = ±{ax:.2f} до налога, 100 % (делитель (1 − 0,244)(1 − 0,024) = {after:.4f}) → сдвиг пути ±{round(ax, 1)}")
    json.dump({'traj_A': traj_A, 'traj_B': traj_B, 'axis_shift_pretax': round(ax, 1), 'R_anchor_q': R_anchor, 'R_1h': R_1h,
               'nominal_by_year': {str(y): round(nom[y], 3) for y in years}, 'cpi_index_avg': {str(y): round(iavg[y], 4) for y in years}},
              open(os.path.join(OUT, 'noncore_center.json'), 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=1)

    # ---------- предложение узлов фактов pnl_quarterly (форма Сбера; расчётные узлы — calc)
    facts = {'basis': 'IFRS группы, строки движка на операционном базисе (LEAD-2 §1 п. 3)', 'unit': 'млрд ₽', 'sign': 'как в отчёте: расходы, резервы, налог — минус',
             'status': 'предложение листа калибровки calib-pnl; сборщик фактов пересчитывает из листов stage1/ifrs', 'quarters': {}}
    for r in rows:
        p = r['period']; y, h = qparts(p); key_p = f"{y}Q{h}"
        n = {}
        n['nii'] = {'v': r['nii'], 'src': src('nii', p)}
        n['fees_net'] = {'v': r['fees'], 'src': src('fees_net', p), 'calc': 'выручка от оказания услуг + расходы, напрямую связанные с оказанием услуг'}
        n['insurance_net'] = {'v': r['ins'], 'src': src('ins_net', p), 'calc': 'выручка по страховой деятельности + расходы по страховой деятельности (финансовые расходы страхования — внутри строки расходов)'}
        n['llp_debt_fa'] = {'v': r['llp_debt_fa'], 'src': src('llp_debt_fa', p)}
        n['fv_loans_credit'] = {'v': None, 'calc': 'не раскрыто: кредиты по СС 5,3 млрд ₽ — в книге corp_loans, кредитная переоценка отдельно не раскрыта'}
        n['opex'] = {'v': round(r['opex'], 4), 'src': src('opex_tech', p), 'calc': 'четыре строки расходов по функциям: технологии + маркетинг и привлечение + обслуживание + административные (редакция 6М2026)'}
        n['misc_net'] = {'v': round(r['misc_net'], 4), 'calc': 'pbt отчёта − (nii + fees_net + insurance_net + llp_debt_fa + opex) − переоценка пакета Яндекса − дивиденды по пакету'}
        n['noncore_net'] = {'v': round(r['noncore_net'], 4), 'calc': '−(поправка эмитента «проценты по займам», после налога, доля акционеров; Databook ROE_operating!30) / (1 − 0,25); допущения: долг на компаниях со 100 % владения, щит 25 %'}
        n['pbt'] = {'v': round(r['pbt'], 4), 'calc': 'pbt отчёта − переоценка пакета − дивиденды по пакету + noncore_net'}
        n['tax'] = {'v': round(r['tax'], 4), 'calc': 'ni − pbt; ni = прибыль отчёта − эффект пакета после налога (поправка эмитента / 0,5001) + noncore_net × 0,75'}
        n['ni'] = {'v': round(r['ni'], 4), 'calc': 'pbt + tax'}
        n['ni_shareholders'] = {'v': round(r['ni_shareholders'], 6), 'calc': 'прибыль акционеров отчёта − поправки эмитента (ROE_operating!29–30) = Databook PL!107'}
        n['ni_nci'] = {'v': round(r['nci'], 4), 'calc': 'НДУ отчёта − (поправка эмитента по пакету) × 0,4999 / 0,5001'}
        if p in BLOCK_QS:
            n['investment_block'] = {'reval_pretax': {'v': r['ib_reval'], 'src': TP['tp_yandex_reval_gross_100'][p][1]}, 'dividends_pretax': {'v': r['ib_dividends'], 'src': YD[p][1]},
                                     'interest_pretax': {'v': round(r['ib_interest'], 4), 'calc': '−noncore_net'}, 'tax': {'v': round(r['ib_tax'], 4), 'calc': 'эффект пакета после налога − (переоценка + дивиденды) + 0,25 × проценты'},
                                     'nci': {'v': round(r['ib_nci'], 4), 'calc': '−эффект пакета после налога × 0,4999'}, 'total_shareholders': {'v': round(r['ib_total_sh'], 6), 'calc': 'сумма пяти строк = поправки эмитента ROE_operating!29 + !30'},
                                     'ni_shareholders_reported': {'v': r['ni_sh_reported'], 'src': src('np_shareholders', p)},
                                     'identity': {'v': round(r['id_reported_eq_op_plus_block'], 9) + 0.0, 'calc': 'отчётная акционерам − (операционная + блок) = 0'}}
        facts['quarters'][key_p] = n
    json.dump(facts, open(os.path.join(OUT, 'pnl_quarterly_proposal.json'), 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=1)
    print()
    print('записано: op_basis_quarterly.csv, out/pnl_quarterly_proposal.json, out/noncore_center.json, out/*.csv')
