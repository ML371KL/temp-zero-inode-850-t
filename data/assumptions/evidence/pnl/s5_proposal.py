# -*- coding: utf-8 -*-
"""Шаг 5. Предложение ключей книги (book_keys_pnl_proposal.yaml) из выходов шагов 1–4.
Каждому ключу: значение, ось (low/high), текст-источник для витрины (src, не длиннее 80 знаков), класс надёжности (A/B/C).
Проверяет длину src и печатает сводную таблицу."""
import json
from pnl_lib import *

J = lambda n: json.load(open(os.path.join(OUT, n), encoding='utf-8'))
NCJ, BRJ, OPX, MTN = J('noncore_center.json'), J('bridge_values.json'), J('opex_calibration.json'), J('misc_tax_nci.json')
DIV = list(csv.DictReader(open(os.path.join(OUT, 'dividend_payout.csv'), encoding='utf-8')))
post = [float(r['payout_to_avg4']) for r in DIV if r['period'] != '4Q2024']
EQ = list(csv.DictReader(open(os.path.join(OUT, 'equity_other_movements.csv'), encoding='utf-8')))
eq4 = sum(float(r['net']) for r in EQ[-4:]) / 4
tr = OPX['proposal']['trajectory']; ax = OPX['proposal']['axis_shift']
ncA = NCJ['traj_A']; nc_ax = NCJ['axis_shift_pretax']
gap = round(MTN['etr_gap_6q'], 3)
nci = round(MTN['nci_share_1h26'], 3)

K = []        # (путь, значение-строка YAML, ось, src ≤ 80, класс, пояснение)


def add(path, value, axis, src, cls, note):
    assert len(src) <= 80, (path, len(src), src)
    K.append(dict(path=path, value=value, axis=axis, src=src, cls=cls, note=note))


fy = lambda d: '{' + ', '.join((f'"{k}": {v}' if k[0].isdigit() else f'{k}: {v}') for k, v in d.items()) + '}'
add('fees.growth_override', '{}', None, 'гайденса по комиссиям на 2026 год у эмитента нет', 'A', 'пусто: формула связи действует с 3К2026')
add('fees.volume_link', '0.7', None, 'суждение книги: связь услуг с ростом портфеля; факт трёх кварталов 0,5–0,7', 'C',
    f"калибровка: при связи {OPX['link_at_zero_real']:.2f} C/I модальной клетки 2030 = 47 % без реального роста расходов; по трём чистым кварталам 0,54–0,67")
add('fees.growth_vs_wages', '{LT: 0.0}', 'shift −0.01…+0.01', 'суждение книги: без спреда к формуле связи; факт 1П2026 +17,7 % г/г', 'C', 'ось узкая: уровень C/I несёт ось расходов (одно суждение — одно место)')
add('opex.volume_link', '0.7', None, 'суждение книги: 0,7 пункта роста расходов на пункт роста портфеля', 'C',
    'структура расходов 1П2026: привлечение 30 % и обслуживание 22 % — с объёмом, технологии и административные 47 % — на 0,3')
add('opex.real_growth', fy(tr), f"shift {ax['0.44']:+.3f}…{ax['0.5']:+.3f} (ключи 2027–2030)", 'подбор: C/I после фазы роста 47 % (среднее семи кварталов после Росбанка)', 'C',
    'корни простого расчёта модальной клетки; концы оси дают C/I 44 и 50 %; после сборки ядра корни пересчитать тем же правилом')
add('volumes.link_base', 'loans', None, 'база связи — средний валовой кредитный портфель квартала, рост г/г', 'B', 'средства клиентов растут иначе (+8…+12 % г/г при кредитах +21…+27 %)')
add('other.insurance_volume_link', '0.0', None, 'страхование нетто шесть кварталов 9,8–12,8 млрд ₽ при росте портфеля на 37 %', 'B', 'с портфелем не растёт')
add('other.insurance_growth_vs_wages', fy(OPX['insurance_spread']), None, 'факт 1П2026 +1,8 % г/г; сход к росту зарплат мира к 2028 году', 'C', 'суждение о сроке схода')
add('other.misc_net_real', f"{{LT: {MTN['center']:.1f}}}", f"value {MTN['low']:.1f}…{MTN['high']:.1f}", 'прочее без пакета Яндекса: медиана квартала 2025–1П2026 × 4, цены 2026', 'B',
    f"1П2026 в годовом выражении {MTN['h1_2026'] * 2:.1f}; четыре квартала {MTN['last4']:.1f}; шесть кварталов без разового дохода {MTN['six_ex_oneoff_annual']:.1f} в год")
add('other.misc_quarter_shares', '{"1": 0.25, "2": 0.25, "3": 0.25, "4": 0.25}', None, 'сезонности «прочего» в шести кварталах 2025–2026 нет — поровну', 'B', 'крупные кварталы — разовые сделки (3К2024, 2К2025)')
add('other.fvtpl_bond_reval', 'false', None, 'облигации по СС через ОПУ 14,3 млрд ₽ — переоценка в уровне «прочего»', 'A', 'выключатель FVR')
add('noncore.result_real', fy(ncA), f"shift −{nc_ax}…+{nc_ax} (ключи 2027–LT)", 'пакет Яндекса зарабатывает проценты по долгу под него; цены 2026', 'C',
    'возврат процентов: поправка эмитента / 0,75; долг постоянен в рублях, ставка — ключевая мира H + 1 п.п.; ось = ±4 млрд ₽ в год акционерам после налога')
add('noncore.price_base_year', '2026', None, 'год якоря', 'A', '')
add('pnl.nci_share', f"{nci}", None, 'НДУ в операционной прибыли 1П2026: 2,5 из 101,1 млрд ₽ (без эффекта пакета)', 'B',
    f"четыре квартала 3К25–2К26 — {MTN['nci_share_last4'] * 100:.1f} %; под НДУ — 49,99 % прибыли «Каталитик Пипл» («Точка», «Селектел»)")
add('tax.statutory', '{"2026": 0.25, LT: 0.25}', 'shift 0…+0.03', 'ставка налога на прибыль 25 % с 2025 года (закон 176-ФЗ)', 'A', '')
add('tax.effective_gap', f"{gap}", None, 'эффективная ставка на операционном базисе: 24,2 % (2025), 24,8 % (1П2026)', 'B', f"шесть кварталов 1К25–2К26: {(0.25 + MTN['etr_gap_6q']) * 100:.2f} %")
add('tax.one_off', '{year: 2027, amount: 25.0, prob: 0.0}', 'prob 0…0.30', 'суждение книги: разовое изъятие ≈12 % годовой прибыли, вероятность 0', 'C', 'масштаб — как в книге Сбера (200 из ≈1 700)')
add('equity.other_movements', '{LT: 0.0}', None, 'резерв мотивации +15,4 и выкуп −14,0 млрд ₽ за четыре квартала гасятся', 'B', f"с прочими движениями {eq4:+.2f} млрд ₽ за квартал; до возобновления выкупа (4К24–2К25) — +5…+10")
add('dividends.policy.payout', '{LT: 0.25}', 'payout_deviation shift −0.05…+0.05', f"факт к средней операционной прибыли четырёх кварталов: {min(post) * 100:.1f}–{max(post) * 100:.1f} %".replace('.', ','), 'B',
    f"среднее шести решений {statistics.fmean(post) * 100:.2f} %; несмещённый центр по факту — 0,26")
add('dividends.policy.base_window_quarters', '4', None, 'разброс доли к базе четырёх кварталов 1,2 п.п. против 2,1 к кварталу', 'B', '')
add('checks.guidance_items', '[op_np_growth, dps_growth]', None, 'прогноз эмитента на 2026 год: операционная прибыль и DPS — от +20 %', 'A', 'roe_target — цель стратегии, в гейт не входит')
add('checks.cir_range', '[0.40, 0.58]', None, 'CIR движка: цель 48,6 %; история 2024–2026 по кварталам 46,4–53,6 %', 'C', 'клетки простого расчёта 47,7–51,5 %; концы оси 45,6–51,6 %')
add('checks.bridge_drift_pp', f"{{cor: {max(BRJ['thr_cor'], 0.002):.3f}, nim: {round(BRJ['thr_nim'] + 0.0004, 3):.3f}}}", None, 'мост упр. ↔ движок: 2,5σ; у ЧПМ — с рябью счёта дней 0,11 п.п.', 'B',
    f"σ CoR {BRJ['cor_sd'] * 100:.3f} п.п.; σ ЧПМ без ряби и тренда {BRJ['nim_sd_clean'] * 100:.3f} п.п.")
add('checks.roe_range', '[-0.05, 0.36]', None, 'ROE года: факт 26,7–33,3 % по кварталам; год кризиса ≈ 2 %', 'C', 'операционная прибыль к капиталу акционеров МСФО')
add('checks.cor_range', '[0.03, 0.12]', None, 'CoR года, базис движка: пути режимов 4,0–10,0 % минус мост 0,24 п.п.', 'C', 'верх — год кризиса с добавкой κ мира M')

Y = ['# Предложение ключей книги по строкам ОПУ, налогу, НДУ, непрофильному результату и дивидендной базе',
     '# (этап 1, ключ calib-pnl, 07.10.2026). Собрано s5_proposal.py из выходов s1–s4 (out/*.json, out/*.csv); руками не править.',
     '# [class] — надёжность: A — факт документа, B — расчёт по фактам, C — суждение. src — текст для витрины (≤ 80 знаков).',
     '# Якорь 30.06.2026; строки движка — на операционном базисе (LEAD-2 §1); формулы связи — LEAD-2 §4.', '']
for k in K:
    Y.append(f"{k['path']}: {k['value']}")
    Y.append(f"#   class: {k['cls']}; src: \"{k['src']}\"")
    if k['axis']: Y.append(f"#   axis: {k['axis']}")
    if k['note']: Y.append(f"#   note: {k['note']}")
Y += ['', '# ---- оси полосы (форма valuation.uncertainty.axes шаблона)', 'axes:',
      f"  - {{name: \"Расходы: реальный рост 2027–2030 (C/I 44–50 %)\", kind: shift, paths: [opex.real_growth.2027, opex.real_growth.2028, opex.real_growth.2029, opex.real_growth.2030], low: {ax['0.44']:.3f}, high: {ax['0.5']:.3f}, dist: triangular, unit: pp}}",
      '  - {name: "Услуги: рост к формуле связи", kind: shift, paths: [fees.growth_vs_wages], low: -0.01, high: 0.01, dist: triangular, unit: pp}',
      f"  - {{name: \"Пакет Яндекса и долг под него (цены 2026)\", kind: shift, paths: [{', '.join('noncore.result_real.' + k for k in ncA if k != '2026')}], low: -{nc_ax}, high: {nc_ax}, dist: triangular, unit: bn}}",
      f"  - {{name: \"Прочее ОПУ (цены 2026)\", kind: value, paths: [other.misc_net_real.LT], low: {MTN['low']:.1f}, high: {MTN['high']:.1f}, dist: triangular, unit: bn}}",
      '  - {name: "Налог: сдвиг ставки", kind: shift, paths: [tax.statutory], low: 0.0, high: 0.03, dist: triangular, unit: pp}',
      '  - {name: "Разовый налог: вероятность", kind: value, paths: [tax.one_off.prob], low: 0.0, high: 0.30, dist: triangular, unit: pct}',
      '  - {name: "Отклонение выплаты от политики", kind: shift, paths: [dividends.payout_deviation], low: -0.05, high: 0.05, dist: triangular, unit: pp}',
      '', '# ---- факты моста (facts/bridge_mgmt_ifrs.json; полный узел — out/bridge_mgmt_ifrs_proposal.json)', 'bridge_mgmt_ifrs:',
      f"  cor: {{method: additive, value: {BRJ['cor']:.6f}, sd: {BRJ['cor_sd']:.6f}, n: 7, window: [2024Q4, 2026Q2]}}",
      f"  nim: {{method: additive, value: {BRJ['nim_anchor']:.6f}, sd: {BRJ['nim_sd_clean']:.6f}, n: 2, window: [2026Q1, 2026Q2], alt_window_mean: {BRJ['nim_b9']:.6f}}}",
      f"  cir: {{method: additive, value: {BRJ['cir']:.6f}, sd: {BRJ['cir_sd']:.6f}, n: 7, window: [2024Q4, 2026Q2]}}"]
open(os.path.join(OUT, 'book_keys_pnl_proposal.yaml'), 'w', encoding='utf-8', newline='\n').write('\n'.join(Y) + '\n')

if __name__ == '__main__':
    print('=' * 110)
    print('ШАГ 5. Предложение ключей книги (book_keys_pnl_proposal.yaml)')
    for k in K:
        print(f"  {k['path']} = {k['value']}" + (f" | ось {k['axis']}" if k['axis'] else '') + f" | [{k['cls']}] {k['src']} ({len(k['src'])})")
    print('  мост: cor', f"{BRJ['cor']:+.6f}", '; nim', f"{BRJ['nim_anchor']:+.6f}", '; cir', f"{BRJ['cir']:+.6f}")
    import yaml
    chk = yaml.safe_load(open(os.path.join(OUT, 'book_keys_pnl_proposal.yaml'), encoding='utf-8'))
    print('  YAML читается; ключей верхнего уровня:', len(chk))
