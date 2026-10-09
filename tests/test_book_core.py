# -*- coding: utf-8 -*-
"""Книга против ядра: суждения книги Т 1.0, которые проверяются только прогоном ядра (поток book; MODEL §4.3–§4.13, §12).

* Модальная клетка книги — мир H × «нормализация» × «средняя группа»: на ней выводятся ближний сдвиг, инструменты
  капитала и спред услуг (метка `tact`, без ядра: свойство вероятностей книги).
* Числа, выведенные на ядре, делают то, что говорит их правило: стационарная маржа мира окна на составе баланса якоря —
  в допуске гейта; инструменты капитала держат долю якоря в RWA, а стоимость внешней доли их прироста стоит в «прочем»;
  ближний сдвиг ЧПМ кончается без ступени; услуги года якоря идут от факта; C/I после фазы роста слоя «рыночные ставки
  как есть» — в коридоре цели, модальная клетка печатает меньше. Если тесты КРАСНЫЕ на готовом ядре —
  запустить `data/assumptions/evidence/path/derive_on_engine.py` и перенести его строки в шаблон. Равенство «кредиты равны
  средствам клиентов» — проверка, а не правило: отношение печатает запись вывода.
* Цепочка отчётов «без новостей» не вымывает хвостовые режимы ниже пола (приёмочный тест решения ведущего № 2, §8 п. 4).
Пока ядро не исполняет ветви второй формы банка (схема называет их словом «не реализовано»), тесты с прогоном
пропускаются с названной причиной. Книга и факты — те, что читает ядро (`data/assumptions/assumptions.yaml`, `data/facts/`).
"""
from __future__ import annotations

import pytest

try:
    from tests import support_book as S
except ImportError:                      # прогон без pytest.ini (pythonpath = .) и без tests/__init__.py
    import support_book as S

FEES_FACT_BAND = (0.15, 0.18)            # рост услуг г/г кварталов года якоря идёт от факта: +15…+18 %
NEAR_FREE_PERIOD = "2030Q1"              # первый квартал без ближнего сдвига ЧПМ
NEAR_BOOK_PATH = (0.1153, 0.1148)        # путь книги: упр. ЧПМ первых двух прогнозных кварталов (3-й и 4-й кварталы 2026 года)


@pytest.fixture(scope="module")
def book() -> dict:
    return S.built_book()


@pytest.fixture(scope="module")
def modal(book):
    """(контекст прогона, модальная клетка) ядра на книге и фактах дерева; пропуск, пока ядро не готово."""
    from model import book_schema

    pending = getattr(book_schema, "pending", None)
    left = pending(book) if pending else []
    if left:
        pytest.skip(f"ядро ещё не исполняет ветви книги второй формы банка ({len(left)}): {left[0]}")
    from model.book import load_book, load_facts
    from model.cell import run_cell
    from model.grid import make_context, modal_cell

    facts = load_facts()
    core_book = load_book(facts=facts)
    ctx = make_context(core_book, facts)
    return ctx, run_cell(ctx, *modal_cell(core_book, ctx.posterior))


@pytest.mark.tact
def test_the_modal_cell_of_the_book(book):
    """Модальная клетка (INTERFACES §4.6): мир с наибольшим весом слоя «свой взгляд», режим с наибольшей вероятностью,
    сценарий капитала с наибольшей вероятностью при этом режиме — без равенств, от порядка книги не зависит."""
    j = book["joint"]
    world = max(j["world_prob"], key=j["world_prob"].get)
    regime = max(j["regime_prob"], key=j["regime_prob"].get)
    scenario = max(j["reg_prob_given_regime"][regime], key=j["reg_prob_given_regime"][regime].get)
    assert (world, regime, scenario) == ("H", "norm", "mid")
    for table in (j["world_prob"], j["regime_prob"], j["reg_prob_given_regime"][regime]):
        top = sorted(table.values())[-2:]
        assert top[1] > top[0]
    assert world == book["nii"]["transmission"]["reference_world"]            # мир отсчёта спредов — тот же


def test_the_key_of_the_margin_is_the_stationary_margin_of_the_window_world(modal, book):
    """Ключ цели ЧПМ — само суждение (решение ведущего № 8, п. A1): стационарная маржа мира уровня на составе баланса
    якоря равна ключу, гейта стационарной маржи у книги нет; уровень мира-опоры передачи решатель находит сам, и он
    другой; маржа, которую печатает модальная клетка после фазы роста, — результат: кредит вытесняет ликвидные
    активы, и она выше суждения."""
    from model.grid import year_mgmt
    from model.levels import level_nim, stationary_nim

    ctx, cell = modal
    key = book["nii"]["nim_lt_target_mgmt"]
    node = level_nim(ctx)
    assert stationary_nim(ctx) is None and "nim_stationary" not in book["checks"]
    assert node["world"] == book["nii"]["transmission"]["level_world"] and node["value"] == pytest.approx(key, abs=1e-9), node
    assert node["reference_world"] == book["nii"]["transmission"]["reference_world"]
    assert node["reference_value"] != pytest.approx(key, abs=1e-4)
    values = [year_mgmt(ctx, "nim", y, cell.annual["nim"][i], lambda name, q: cell.quarters[name][q])
              for i, y in enumerate(cell.years) if y >= book["checks"]["window_backtest"]["from_year"]]
    assert sum(values) / len(values) > key


def test_the_outflow_of_client_funds_sits_in_its_quarter(modal, book):
    """Отток средств клиентов года якоря стоит в своём квартале (решение ведущего № 8, п. A5): ключ первого прогнозного
    квартала — по факту последнего месячного релиза, следующего — темп сектора. Средства физлиц модальной клетки на
    конец первого прогнозного квартала ниже якоря, а за следующий квартал растут ровно темпом сектора мира."""
    ctx, cell = modal
    tl = ctx.timeline
    year = tl.anchor_year
    retail = [float(cell.quarters["funds_retail"][q]) for q in (0, 1, 2)]
    sector = float(ctx.worlds[cell.world].funds_growth["retail"][year])
    premium = book["volumes"]["funds_share_drift"]["retail"]
    assert retail[1] < retail[0]
    assert retail[1] / retail[0] == pytest.approx(((1 + sector) * (1 + premium[tl.period(1)])) ** 0.25, rel=1e-12)
    assert premium[tl.period(2)] == 0.0 and retail[2] / retail[1] == pytest.approx((1 + sector) ** 0.25, rel=1e-12)


def test_the_cost_of_capital_instruments_sits_in_the_misc_line(modal, book):
    """Стоимость прироста инструментов капитала сверх якоря (решения ведущего № 6, п. 6, и № 7, п. A6): «прочее»
    клетки по годам ниже уровня без стоимости ровно на прирост траектории инструментов × внешнюю долю × спред записи
    вывода (в пределах 2 %)."""
    import json

    ctx, cell = modal
    tl = ctx.timeline
    record = json.loads((S.EVIDENCE / "path" / "out" / "derive_out.json").read_text(encoding="utf-8"))
    spread, level = record["cost"]["spread_on_increment"], record["cost"]["level"]
    assert spread == pytest.approx(record["cost"]["spread"]["to_wholesale"] * record["cost"]["external"]["share"], abs=1e-6)
    index = ctx.worlds[cell.world].price_index
    t2 = ctx.prep.t2
    for year in (2030, int(book["meta"]["last_period"][:4])):
        qs = tl.quarters_of_year(year)
        misc = sum(float(cell.quarters["misc"][q]) for q in qs)
        flat = sum(level * float(index[q]) * book["other"]["misc_quarter_shares"][str(int(tl.period(q)[5]))] for q in qs)
        cost = sum(((float(t2[q - 1]) + float(t2[q])) / 2 - float(t2[0])) * spread * tl.d(q) / 365 for q in qs)
        assert flat - misc == pytest.approx(cost, rel=0.02), year


def test_fees_of_the_anchor_year_follow_the_fact(modal):
    """Спред услуг года якоря (решение ведущего № 6, п. 7): рост услуг г/г в прогнозных кварталах года якоря — в
    диапазоне факта, без ускорения."""
    ctx, cell = modal
    tl, hist = ctx.timeline, ctx.prep.hist["fees"]
    growth = [float(cell.quarters["fees"][q]) / float(hist[q - 4]) - 1 for q in tl.quarters_of_year(tl.anchor_year) if q >= 1]
    assert all(FEES_FACT_BAND[0] <= g <= FEES_FACT_BAND[1] for g in growth), [round(100 * g, 1) for g in growth]


def test_capital_instruments_keep_the_anchor_share_of_rwa(modal, book):
    """Траектория инструментов капитала держит долю якоря в RWA модальной клетки (решение ведущего № 4, п. 3)."""
    ctx, cell = modal
    tl, t2 = ctx.timeline, book["capital"]["n20"]["t2"]
    share0 = ctx.facts.need("capital", "t2_recognized") / float(cell.quarters["rwa"][0])
    last_year = book["meta"]["last_period"][:4]
    worst = max(abs(t2[tl.period(q)] / float(cell.quarters["rwa"][q]) - share0)
                for q in range(1, tl.Q + 1) if tl.period(q)[:4] != last_year)
    assert 0.022 <= share0 <= 0.025 and worst <= 0.001, f"доля инструментов в RWA уходит от якоря на {100 * worst:.2f} п.п."


def test_the_near_path_of_the_anchor_year_is_the_path_of_the_book(modal):
    """Ближний сдвиг года якоря печатает путь книги (решение ведущего № 4, п. 17): упр. ЧПМ модальной клетки в 3-м и
    4-м кварталах года якоря — 11,53 и 11,48 % (допуск — точность записи ключа сдвига)."""
    ctx, cell = modal
    nim = [ctx.bridge.to_mgmt_nim(float(cell.quarters["nim"][q])) for q in (1, 2)]
    assert nim == pytest.approx(list(NEAR_BOOK_PATH), abs=2e-5), [round(100 * v, 3) for v in nim]


def test_the_near_nim_shift_ends_without_a_step(modal):
    """Ближний сдвиг ЧПМ подводит путь к марже, которую клетка печатает без сдвига: на стыке с первым свободным
    кварталом ступени нет (шаг не больше 0,15 п.п. — как между соседними кварталами ближнего пути)."""
    ctx, cell = modal
    q = ctx.timeline.index(NEAR_FREE_PERIOD)
    nim = [ctx.bridge.to_mgmt_nim(float(cell.quarters["nim"][k])) for k in (q - 1, q)]
    assert abs(nim[1] - nim[0]) <= 0.0015, f"ступень ЧПМ на стыке с {NEAR_FREE_PERIOD}: {100 * (nim[1] - nim[0]):+.2f} п.п."


def test_cost_to_income_after_the_growth_phase_is_on_target(modal, book):
    """Корни реального роста расходов выведены под цель C/I после фазы роста в ожидании слоя «рыночные ставки как
    есть» (решение ведущего № 7, п. A2): число гейта долгосрочного C/I — в коридоре цели; модальная клетка мира H
    печатает меньше цели — это результат."""
    from model.book import load_book, load_facts
    from model.grid import run_grid
    from model.levels import cir_lt_value
    from model.live import live_from_book

    facts = load_facts()
    b = load_book(facts=facts)
    node = cir_lt_value(run_grid(b, facts, live_from_book(b, facts)))
    gate = book["checks"]["cir_lt"]
    assert node["scope"] == gate["scope"] == "market_layer"
    assert abs(node["value"] - gate["target"]) <= gate["tolerance"], f"C/I упр. слоя: {100 * node['value']:.2f} %"
    assert node["modal"] < node["value"]


def test_the_no_news_chain_stops_at_the_floor(modal, book):
    """Приёмочный тест книги (решение ведущего № 2, §8 п. 4): цепочка восьми отчётов «факт = ожидание» не опускает
    вероятность ни одного режима ниже пола — доли `floor_share` базовой вероятности; сумма вероятностей — единица."""
    from model.book import load_book, load_facts
    from model.grid import run_grid
    from model.live import live_from_book
    from model.nextreport import model_expectation, open_period, with_observation

    facts = load_facts()
    b = load_book(facts=facts)
    live = live_from_book(b, facts)
    share, prior = book["joint"]["regime_update"]["floor_share"], book["joint"]["regime_prob"]
    for _ in range(8):
        period = open_period(b, facts)
        e = model_expectation(b, facts, period, live=live, run=run_grid(b, facts, live))
        b = with_observation(b, period, cor=e["cor_q_mgmt"], nim=e["nim_q_mgmt"])
        post = dict(run_grid(b, facts, live).ctx.posterior)
        assert abs(sum(post.values()) - 1) < 1e-9
        assert all(post[r] >= share * prior[r] - 1e-12 for r in prior), post
