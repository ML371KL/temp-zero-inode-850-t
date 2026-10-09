"""Документы фактов: SCHEMA.md описывает каждый файл и параметры сборщика, FACTS.md называет каждый документ
реестров, повторяет печатаемые записки календаря и политики и говорит о трёх прибылях и нераскрытом."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "data" / "facts"

pytestmark = pytest.mark.docs


def load(name: str) -> dict:
    return json.loads((FACTS / f"{name}.json").read_text(encoding="utf-8"))


def facts_md() -> str:
    return (ROOT / "docs" / "FACTS.md").read_text(encoding="utf-8")


def test_schema_describes_every_file():
    text = (FACTS / "SCHEMA.md").read_text(encoding="utf-8")
    missing = [p.name for p in sorted(FACTS.glob("*.json")) if f"`{p.name}`" not in text]
    assert not missing, f"SCHEMA.md не описывает: {missing}"


def test_schema_lists_the_named_parameters_of_the_builder():
    """Всё, что в сборщике названо датой или периодом, — именованный параметр, и схема его перечисляет."""
    text = (FACTS / "SCHEMA.md").read_text(encoding="utf-8")
    src = (ROOT / "ops" / "tools" / "build_facts.py").read_text(encoding="utf-8")
    for name in ("PNL_FIRST", "HISTORY_FIRST", "CAPITAL_HISTORY_FIRST", "DEBT_SECURITIES_FROM", "BRIDGE_FIRST",
                 "NIM_BRIDGE_COMPARABLE_FROM", "COR_BRIDGE_DENOMINATOR", "RAS_FROM", "POLICY", "ACTIONS", "SPLIT_FIRST_TRADE", "INSTRUMENTS",
                 "GUIDANCE_ITEMS", "MGMT_PAIRS", "BOOKS", "PNL_LINES", "PNL_REPORTED", "BLOCK", "OTHER_ASSETS",
                 "OTHER_LIABILITIES"):
        assert re.search(rf"^{name}\b", src, re.M), f"в сборщике нет параметра {name}"
        assert f"`{name}`" in text, f"SCHEMA.md не называет параметр {name}"
    for name in ("PNL_FIRST", "HISTORY_FIRST", "DEBT_SECURITIES_FROM", "BRIDGE_FIRST", "NIM_BRIDGE_COMPARABLE_FROM", "RAS_FROM"):
        value = re.search(rf'^{name} = "(\d{{4}}Q[1-4])"', src, re.M).group(1)
        assert re.search(rf"`{name}`[^|]*\| {value} \|", text) or re.search(rf"`{name}`, `\w+` \| {value} \|", text), \
            f"SCHEMA.md: значение {name} расходится со сборщиком ({value})"


def test_schema_node_names_exist_in_the_facts():
    """Имена узлов в обратных кавычках с точкой (`файл → узел` пишется как `balance.books` в тексте тождеств) не
    проверяются поштучно; проверяется перечень файлов и то, что схема не называет узлов семейства, которых нет."""
    text = (FACTS / "SCHEMA.md").read_text(encoding="utf-8")
    for gone in ("dividends_payable_year", "history_before", "n1_0_bank", "dps_ordinary", "mortgage_sub"):
        assert f"`{gone}`" not in text or "вместо" in text, f"SCHEMA.md описывает узел семейства {gone}, которого у эмитента нет"


def test_facts_md_names_every_document():
    text = facts_md()
    missing = []
    for name, key in (("anchor", "documents"), ("calendar", "sources"), ("peers", "sources")):
        for d in load(name)[key]:
            if f"`{d['key']}`" not in text or d["sha256"][:16] not in text:
                missing.append(f"{name}:{d['key']}")
    assert not missing, f"FACTS.md не называет документы: {missing}"


def test_facts_md_repeats_the_calendar_notes():
    """Таблица календаря в FACTS.md повторяет названия и записки событий дословно: их печатает витрина, и документ не
    должен отставать от правки факта."""
    text = facts_md()
    missing = []
    for e in load("calendar")["events"]:
        row = f"| {e['title']} | {e.get('note') or ''} |"
        if row not in text:
            missing.append(e["id"])
    assert not missing, f"FACTS.md расходится с calendar.json в событиях: {missing}"


def test_facts_md_repeats_the_peer_row_sources():
    """Источник строки аналога уходит в выпуск без хвостов sha256 — FACTS.md повторяет его дословно."""
    text = facts_md()
    missing = []
    for b in load("peers")["banks"]:
        words = "; ".join(x for x in (re.sub(r",?\s*sha256\s+[0-9a-f]{8,}", "", item).strip()
                                      for item in b["src"].split(";")) if x)
        if f"| {b['ticker']} | {words} |" not in text:
            missing.append(b["ticker"])
    assert not missing, f"FACTS.md расходится с peers.json в источниках строк: {missing}"


def test_facts_md_explains_the_quarter_differences_and_the_pay_dates():
    """Два правила чтения фактов названы словами: квартал-разность нарастающих итогов и смысл срока выплаты."""
    text = " ".join(facts_md().split())
    schema = " ".join((FACTS / "SCHEMA.md").read_text(encoding="utf-8").split())
    for doc, body in (("FACTS.md", text), ("SCHEMA.md", schema)):
        for words in ("нарастающих итогов", "уменьшаемое и вычитаемое", "срок выплаты номинальным держателям",
                      "История дивидендных выплат", "День фактической выплаты в фактах не хранится"):
            assert words in body, f"{doc}: нет слов «{words}»"
    d = load("dividends")
    for r in d["history"]:                              # срок из решения собрания — в таблице истории
        day = ".".join(reversed(r["pay_date"].split("-")))
        assert f"| {day} |" in facts_md(), f"FACTS.md: нет срока выплаты {day} ({r['period']})"


def test_facts_md_quotes_the_policy_and_the_rules():
    """Текст политики, записка о сроке, правило дат и итог сверки с брокерским календарём печатаются на витрине —
    FACTS.md приводит их дословно."""
    text = " ".join(facts_md().split())
    d = load("dividends")
    for what, s in (("текст политики", d["policy"]["text"]), ("записка о сроке", d["policy"]["valid_until_note"]),
                    ("правило дат", d["dates_rule"]), ("сверка с брокерским календарём", d["broker_check"])):
        assert " ".join(s.split()) in text, f"FACTS.md: {what} расходится с dividends.json"


def test_facts_md_states_the_anchor_numbers_of_the_facts():
    """Числа якоря в тексте FACTS.md — те же, что в фактах (документ не отстаёт от пересборки)."""
    text = facts_md()
    ru = lambda x, n: f"{x:,.{n}f}".replace(",", " ").replace(".", ",")   # noqa: E731
    b, nb, c, s = load("balance"), load("nii_books"), load("capital"), load("shares")
    a = load("pnl_quarterly")["quarters"][load("anchor")["period"]]
    br = load("bridge_mgmt_ifrs")
    want = {
        "активы": ru(b["total_assets"]["v"], 1), "прочие активы": ru(b["other_assets"]["v"], 1),
        "прочие обязательства": ru(b["other_liabilities"]["v"], 1), "дивиденды к выплате": ru(b["dividends_payable"]["v"], 1),
        "ЧПД квартала": ru(nb["nii_q"]["v"], 1), "операционная прибыль квартала": ru(a["ni_shareholders"]["v"], 3),
        "отчётная прибыль квартала": ru(a["reported"]["ni_shareholders"]["v"], 1),
        "Н20.0": ru(c["n20_0"]["value"]["v"] * 100, 2), "Н20.1": ru(c["n1_1_bank"]["value"]["v"] * 100, 2),
        "вменённые активы": ru(c["basel"]["rwa"]["v"], 1), "размещённые акции": ru(s["issued_total"]["v"], 5),
        "акции в обращении": ru(s["outstanding_total"]["v"], 5),
        "мост CoR": ru(br["cor"]["value"]["v"] * 100, 4), "мост ЧПМ": ru(br["nim"]["value"]["v"] * 100, 4),
        "мост C/I": ru(br["cir"]["value"]["v"] * 100, 4),
    }
    missing = [f"{k}: {x}" for k, x in want.items() if x.replace("-", "−") not in text]
    assert not missing, f"FACTS.md не называет числа фактов: {missing}"


def test_facts_md_explains_the_three_profits_and_the_undisclosed():
    text = facts_md()
    for word in ("отчётная прибыль акционеров", "операционная прибыль акционеров", "блок пакета", "операционном базисе",
                 "после дробления", "Лист!Ячейка", "sha256", "BANK_HANDOFF_DIR", "не раскрыт", "расчёт", "оценк"):
        assert word in text, f"FACTS.md: нет слов «{word}»"
    assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]|/Users/|\\Users\\", text), "FACTS.md: абсолютный путь"
