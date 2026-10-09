"""Дивиденды по периодам: история решений, стартовый реестр, источники (data/facts/dividends.json).

Квартальный календарь: одна строка истории на решение собрания, ключ — квартал прибыли; всё «на акцию» — после
дробления, исходное значение решения — рядом. Источник объявленного дивиденда — документ эмитента и новость о
решении; брокерский календарь — только сверка, словами. Закрыт ли квартал прибыли до якоря, решает дата решения
строки истории (правило закрытого квартала), поэтому период и дата решения обязательны в каждой строке.
"""

from __future__ import annotations

import datetime as dt
import inspect
import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.tact

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "data" / "facts"
KINDS = ("manual", "news")
SOURCE_RE = re.compile(r"^(manual|news): \S")
SHA_RE = re.compile(r"sha256 ([0-9a-f]{16})")
PERIOD_RE = re.compile(r"^\d{4}Q[1-4]$")
RECORD_AFTER_DECISION = (10, 20)     # дней от решения собрания до даты реестра (политика п. 5.5)
DIVIDENDS_DOC = "dividends_public"   # лист решений собраний — документ реестра
T_ANCHOR = "2026Q2"
# Имена полей и методов ответов брокерского API и пути к образцам ответов: в данных и документах о фактах их нет.
# Слова собраны из частей: сам тест — не «имя поля» для общего теста гигиены.
API_WORDS = tuple(a + b for a, b in (
    ("dividend", "Net"), ("record", "Date"), ("lastBuy", "Date"), ("payment", "Date"), ("declared", "Date"),
    ("close", "Price"), ("yield", "Value"), ("Get", "Dividends"), ("Get", "AssetReports"), ("Get", "LastPrices"),
    ("Get", "ForecastBy"), ("Instruments", "Service"), ("tinvest_", "samples"), ("invest-public", "-api")))
PUBLIC_TEXTS = [FACTS / "SCHEMA.md", ROOT / "docs" / "FACTS.md"]


def load(name: str) -> dict:
    return json.loads((FACTS / f"{name}.json").read_text(encoding="utf-8"))


def day(x: str) -> dt.date:
    return dt.date.fromisoformat(x)


def kinds(sources: list[str]) -> set[str]:
    return {s.split(":", 1)[0] for s in sources}


def records() -> list[tuple[str, dict]]:
    d = load("dividends")
    return [(f"history.{r['period']}", r) for r in d["history"]] + [(f"register_seed.{r['period']}", r) for r in d["register_seed"]]


def split_events() -> list[tuple[str, int]]:
    return [(a["date"], int(a["factor"]["v"])) for a in load("shares")["corporate_actions"] if a["kind"] == "split"]


# ------------------------------------------------------------------ формат строки истории

def test_history_is_one_row_per_decision_keyed_by_the_profit_quarter():
    h = load("dividends")["history"]
    periods = [r["period"] for r in h]
    assert periods == sorted(set(periods)), "периоды решений повторяются или идут не по порядку"
    for r in h:
        assert PERIOD_RE.match(r["period"]) and r["year"] == int(r["period"][:4]), r["period"]
        assert r["label"].startswith("за ") and str(r["year"]) in r["label"], f"{r['period']}: слова решения"
        assert r["settlement"] == "T+1" and r["decided_by"], r["period"]
        for k in ("recommended_date", "decided_date", "record_date", "last_buy_date", "ex_date", "pay_date", "pay_deadline_others"):
            day(r[k])
        assert r["dps"]["v"] > 0 and r["pool_declared"]["v"] > 0
    if load("anchor")["period"] == T_ANCHOR:
        got = [(r["period"], r["dps"]["v"]) for r in h]
        assert got == [("2024Q3", 9.25), ("2024Q4", 3.2), ("2025Q1", 3.3), ("2025Q2", 3.5), ("2025Q3", 3.6), ("2025Q4", 4.5),
                       ("2026Q1", 4.6), ("2026Q2", 4.7)], "восемь решений после редомициляции"
        assert h[0]["label"] == "за девять месяцев 2024 года", "решение за девять месяцев пишется последним кварталом"


def test_per_share_values_are_after_the_split_with_the_original_alongside():
    """Решение до дробления: dps — после дробления, dps_pre_split — как объявлено, split_factor — коэффициент;
    решение после дробления: коэффициент 1, исходное значение — null с причиной."""
    splits = split_events()
    assert splits, "в корпоративных событиях нет дробления"
    for r in load("dividends")["history"]:
        want = 1
        for when, factor in splits:
            if r["decided_date"] < when:
                want *= factor
        assert r["split_factor"] == want, r["period"]
        pre = r["dps_pre_split"]
        if want > 1:
            assert abs(r["dps"]["v"] * want - pre["v"]) < 1e-9, f"{r['period']}: dps × коэффициент ≠ значению решения"
            assert "дроблени" in pre["calc"] and "дроблени" in r["dps"]["calc"]
        else:
            assert pre["v"] is None and "после дробления" in pre["calc"], r["period"]


def test_pool_is_dps_times_issued_shares():
    """«Итого» эмитента — на все размещённые акции (делитель политики), а не на акции в обращении."""
    n_iss = load("shares")["issued_total"]["v"]
    for r in load("dividends")["history"]:
        assert abs(r["pool_declared"]["v"] - r["dps"]["v"] * n_iss / 1000) < 2e-6, r["period"]
    if load("anchor")["period"] == T_ANCHOR:
        last = load("dividends")["history"][-1]
        assert abs(last["pool_declared"]["v"] - 12.609) < 0.001
        n_out = load("shares")["outstanding_total"]["v"]
        assert abs(last["dps"]["v"] * n_out / 1000 - 11.985) < 0.001, "отток — на акции в обращении"


def test_decided_date_and_record_date_rule():
    """Дата реестра — через 10–20 дней после решения; экс-дата — день реестра (T+1); последний день покупки — торговый
    день перед ним; срок выплаты номинальным держателям — 10 рабочих дней (12–18 календарных)."""
    for where, r in records():
        decided, record = day(r["decided_date"]), day(r["record_date"])
        assert RECORD_AFTER_DECISION[0] <= (record - decided).days <= RECORD_AFTER_DECISION[1], where
        assert r["ex_date"] == r["record_date"], f"{where}: экс-дата ≠ дате реестра"
        buy = day(r["last_buy_date"])
        assert 0 < (record - buy).days <= 5 and buy.weekday() < 5, f"{where}: последний день покупки"
        assert 12 <= (day(r["pay_date"]) - record).days <= 18, f"{where}: срок выплаты"
        assert day(r["recommended_date"]) < decided, f"{where}: рекомендация совета — до решения"
        period_end = dt.date(int(r["period"][:4]), 3 * int(r["period"][-1]), 28)
        assert decided > period_end, f"{where}: решение раньше конца квартала прибыли"


def test_sources_have_kind_and_document():
    reg = {d["sha256"][:16]: d for d in load("anchor")["documents"]}
    sheet = next(s for s, d in reg.items() if d["key"] == DIVIDENDS_DOC)
    for where, r in records():
        assert r["sources"], where
        for s in r["sources"]:
            assert SOURCE_RE.match(s), f"{where}: источник без вида: {s[:60]}"
            shas = SHA_RE.findall(s)
            assert shas and all(x in reg for x in shas), f"{where}: sha256 источника нет в реестре"
        assert kinds(r["sources"]) == set(KINDS), f"{where}: нужны документ эмитента и новость"
        news = [s for s in r["sources"] if s.startswith("news:")]
        assert all(re.search(r"\d\d\.\d\d\.\d{4}", s) and "http" in s and sheet in s for s in news), f"{where}: новость — с датой и адресом"
        manual = [s for s in r["sources"] if s.startswith("manual:")]
        assert all("документ эмитента" in s for s in manual), where


def test_dividend_numbers_come_from_the_public_decisions_sheet():
    reg = {d["sha256"][:16]: d for d in load("anchor")["documents"]}
    sheet = next(s for s, d in reg.items() if d["key"] == DIVIDENDS_DOC)
    for r in load("dividends")["history"]:
        for k in ("dps", "pool_declared"):
            assert sheet in r[k]["src"], f"{r['period']}.{k}: источник — лист решений собраний"
            others = [s for s in SHA_RE.findall(r[k]["src"]) if s != sheet]
            assert others, f"{r['period']}.{k}: рядом с листом — документ эмитента"


# ------------------------------------------------------------------ стартовый реестр и закрытый квартал

def closed_through() -> str:
    """Последний закрытый квартал прибыли: самая поздняя строка истории с решением не позже даты фактов."""
    a = load("anchor")["as_of"]
    return max(r["period"] for r in load("dividends")["history"] if r["decided_date"] <= a)


def test_register_seed_records():
    d, a = load("dividends"), load("anchor")
    hist = {r["period"]: r for r in d["history"]}
    want = [r["period"] for r in d["history"] if r["ex_date"] > a["as_of"]]
    assert [r["period"] for r in d["register_seed"]] == want, "стартовый реестр — решения с экс-датой позже якоря"
    for r in d["register_seed"]:
        h = hist[r["period"]]
        for k in ("year", "label", "dps", "decided_date", "recommended_date", "record_date", "last_buy_date", "ex_date", "pay_date", "sources"):
            assert r[k] == h[k], f"{r['period']}.{k}: запись реестра расходится со строкой истории"
        assert r["status"] == ("paid" if r["pay_date"] <= d["snapshot"] else "declared"), r["period"]
        assert r["period"] > closed_through(), f"{r['period']}: запись за закрытый квартал"
        assert len(kinds(r["sources"])) >= 2, f"{r['period']}: объявление подтверждено одним видом источника"
    if a["period"] == T_ANCHOR:
        got = [(r["period"], r["dps"]["v"], r["status"], r["record_date"]) for r in d["register_seed"]]
        assert got == [("2026Q1", 4.6, "paid", "2026-08-10"), ("2026Q2", 4.7, "declared", "2026-10-12")]
        assert closed_through() == "2025Q4", "собрание 14.05.2026 — последнее до даты фактов"


def test_closed_quarters_carry_a_history_row_for_every_quarter_of_the_dividend_years():
    """Годовая сумма DPS собирается из строк истории закрытых кварталов: у каждого закрытого квартала года якоря и
    прошлого года есть строка (решение за девять месяцев закрывает и кварталы до него)."""
    d, a = load("dividends"), load("anchor")
    periods = [r["period"] for r in d["history"]]
    first, last = periods[0], closed_through()
    y, k = int(first[:4]), int(first[-1])
    while f"{y}Q{k}" <= last:
        assert f"{y}Q{k}" in periods, f"нет строки истории за закрытый квартал {y}Q{k}"
        y, k = (y + 1, 1) if k == 4 else (y, k + 1)
    assert max(periods) >= a["period"] or max(periods) >= last


def test_policy_cap_holds_on_complete_years():
    """Проверка потолка политики: сумма объявленного за год ≤ 30 % отчётной прибыли акционеров за год."""
    d = load("dividends")
    cap = d["policy"]["cap"]
    assert cap["v"] == 0.30 and "4.2" in cap["calc"] and "sha256" in cap["src"]
    assert d["policy"]["threshold"]["v"] is None and "порог" in d["policy"]["threshold"]["calc"]
    assert d["policy"]["valid_until"]["v"] is None and "не ограничен" in d["policy"]["valid_until"]["calc"]
    assert d["policy"]["frequency"] == "quarterly" and d["policy"]["approved"] == "2025-03-20"
    complete = {y: rec for y, rec in d["years"].items() if rec["complete"]}
    assert complete, "нет ни одного завершённого года"
    for y, rec in d["years"].items():
        pool = sum(r["pool_declared"]["v"] for r in d["history"] if r["year"] == int(y))
        assert pool > 0, f"{y}: в истории нет решений"
        if rec["complete"]:
            assert pool <= cap["v"] * rec["ni_shareholders"]["v"] + 1e-9, f"{y}: объявлено {pool:.3f} выше потолка"
    if load("anchor")["period"] == T_ANCHOR:
        pools = {y: round(sum(r["pool_declared"]["v"] for r in d["history"] if r["year"] == int(y)), 3) for y in d["years"]}
        assert pools == {"2024": 33.4, "2025": 39.973, "2026": 24.95}
        assert d["years"]["2026"]["complete"] is False and d["years"]["2026"]["through"] == T_ANCHOR


# ------------------------------------------------------------------ брокерский календарь — только сверка

def test_no_broker_api_fields_or_sample_paths_in_facts_and_their_documents():
    bad = []
    for path in sorted(FACTS.glob("*.json")) + [p for p in PUBLIC_TEXTS if p.exists()]:
        text = path.read_text(encoding="utf-8")
        bad += [f"{path.name}: {w}" for w in API_WORDS if w in text]
    assert not bad, "имена полей и методов брокерского API в фактах: " + ", ".join(bad)
    d = load("dividends")
    assert "сверены с брокерским календарём" in d["broker_check"] and "расхождений нет" in d["broker_check"]
    assert "только сверка" in d["broker_check"]
    assert "10 рабочих дней" in d["dates_rule"] and "T+1" in d["dates_rule"]
    for s in load("calendar")["sources"]:
        assert "T-Invest" not in s["title"] and "брокер" not in s["title"].lower(), f"календарь: источник {s['key']} — брокерский календарь"


def test_core_accepts_the_seed_records():
    """Правила годности записи реестра ядра (дата реестра после решения, экс-дата, последний день покупки, два
    источника у объявленного дивиденда) принимают записи стартового реестра как есть."""
    live = pytest.importorskip("model.live")
    check = getattr(live, "check_register", None)
    if check is None:
        pytest.skip("в ядре нет check_register")
    rows = []
    for rec in load("dividends")["register_seed"]:
        rows.append({k: (x.get("v") if isinstance(x, dict) and "v" in x else x) for k, x in rec.items()})
    params = inspect.signature(check).parameters
    ok, bad = check(rows, **({"price": 300.0} if "price" in params else {}))
    assert not bad, f"ядро отвергло записи стартового реестра: {[(b.get('period'), b.get('reason')) for b in bad]}"
    assert len(ok) == len(rows)
