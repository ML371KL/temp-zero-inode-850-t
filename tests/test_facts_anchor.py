"""Сборщик фактов без папки передачи: якорь — из аргумента, состав — тремя таблицами, функции — общие.

Квартал якоря приходит аргументом `--anchor` (по умолчанию — `data/facts/anchor.json`); дата, лист якоря,
нарастающий итог, окна мостов и стартовый реестр выводятся из него и из данных. В теле функций сборщика нет
периодов и дат — они живут в именованных параметрах начала файла (SCHEMA.md §3). Формулы блока пакета, формы
ядра и файла отчёта квартала проверяются на закоммиченных фактах.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.tact

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "data" / "facts"
BUILDER = ROOT / "ops" / "tools" / "build_facts.py"

# Периоды и даты в строках кода: 2026Q2, 2Q2026, 6M2026, FY2025, 2026-06-30, 30.06.2026.
PERIOD_RE = re.compile(r"(?<![\w.])(?:20\d\dQ[1-4]|[1-4]Q20\d\d|\d{1,2}M20\d\d|FY20\d\d|20\d\d-\d\d-\d\d|"
                       r"\d\d\.\d\d\.20\d\d)(?![\w])")
YEAR_RE = re.compile(r"(?<![\w.,/-])20[1-4]\d(?![\w,/-])")


def builder():
    spec = importlib.util.spec_from_file_location("build_facts_under_test", BUILDER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


B = builder()


def facts() -> dict[str, dict]:
    return {k: json.loads((FACTS / f"{k}.json").read_text(encoding="utf-8")) for k in B.BUILT}


# ------------------------------------------------------------------ якорь и выводимое из него

def test_anchor_derivations():
    a = B.Anchor("2026Q2")
    assert (a.date, a.open_date, a.prev_year_end) == ("2026-06-30", "2026-03-31", "2025-12-31")
    assert (a.ytd, a.ytd_ru, a.year_quarters) == ("6M2026", "6М2026", ["2026Q1", "2026Q2"])
    assert a.anchor_sheet == "stage1/ifrs/ifrs_anchor_2026Q2.csv"
    q4 = B.Anchor("2026Q4")
    assert (q4.date, q4.ytd, q4.ytd_ru, q4.prev_year_end, len(q4.year_quarters)) == ("2026-12-31", "FY2026", "2026 год", "2025-12-31", 4)
    q1 = B.Anchor("2027Q1")
    assert (q1.open_date, q1.ytd, q1.prev_year_end, q1.year_quarters) == ("2026-12-31", "3M2027", "2026-12-31", ["2027Q1"])
    assert B.q_prev("2027Q1") == "2026Q4" and B.q_days("2026Q2") == 91 and B.q_days("2026Q1") == 90
    assert B.q_range("2025Q3", "2026Q2") == ["2025Q3", "2025Q4", "2026Q1", "2026Q2"]
    assert B.ifrs_q("2026Q2") == "2Q2026" and B.q_of_date("2026-06-30") == "2026Q2" and B.q_ru("2026Q2") == "2К2026"
    with pytest.raises(B.BuildError):
        B.Anchor("2026-Q2")


def test_default_anchor_is_the_committed_one():
    assert B.default_anchor() == json.loads((FACTS / "anchor.json").read_text(encoding="utf-8"))["period"]


def test_builder_has_no_quarter_literals_outside_named_parameters():
    """В теле функций сборщика нет периодов, дат и лет: всё, что привязано к календарю, — именованный параметр начала
    файла или выводится из якоря (строки документации не в счёт)."""
    tree = ast.parse(BUILDER.read_text(encoding="utf-8"))
    bad = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(fn, clean=False)
        for n in ast.walk(fn):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value != doc:
                m = PERIOD_RE.search(n.value) or YEAR_RE.search(n.value)
                if m:
                    bad.append(f"{fn.name}:{n.lineno}: «{m.group(0)}»")
    assert not bad, "периоды и даты в теле функций: " + "; ".join(bad)


# ------------------------------------------------------------------ три таблицы состава

BOOKS = ("cards", "cash_loans", "auto", "mortgage", "sme_loans", "corp_loans", "securities", "liquidity",
         "retail_current", "retail_term", "corp_funds", "wholesale")
NAMES = ("Кредитные карты", "Кредиты наличными", "Автокредиты", "Ипотека", "Кредиты МСБ", "Корпоративные кредиты и лизинг",
         "Долговые бумаги", "Ликвидность", "Текущие счета физлиц", "Срочные вклады физлиц", "Средства бизнеса",
         "Оптовое фондирование")


def test_table_of_books_is_the_contract_set():
    assert tuple(B.BOOKS) == BOOKS and tuple(s["name"] for s in B.BOOKS.values()) == NAMES
    assert [b for b in BOOKS if B.BOOKS[b]["side"] == "asset"] == list(BOOKS[:8])
    assert B.books_of(loans=True) == list(BOOKS[:6]) and B.books_of("liability") == list(BOOKS[8:])
    seg = {b: B.BOOKS[b]["segment"] for b in B.books_of(loans=True)}
    assert seg == {**dict.fromkeys(BOOKS[:5], "retail"), "corp_loans": "corporate"}, "кредиты МСБ — сегмент retail (решение проекта)"
    for b, s in B.BOOKS.items():
        assert s["balance"] and s["interest"], b
        for path, lines in (s.get("nodes") or {}).items():
            assert set(lines) <= set(s["balance"]), f"{b}: узел {path} называет строку вне книги"
    lines = [ln.lstrip("-") for s in B.BOOKS.values() for ln in s["balance"]]
    assert len(lines) == len(set(lines)), "строка остатка стоит в двух книгах"
    interest = [ln for s in B.BOOKS.values() for ln in s["interest"]] + [ln for ls in B.INTEREST_OUTSIDE.values() for ln in ls]
    assert len(interest) == len(set(interest)), "строка процентов стоит в двух книгах"


def test_table_of_pnl_lines_and_the_block():
    assert tuple(B.PNL_LINES) == ("nii", "fees_net", "insurance_net", "llp_debt_fa", "opex")
    assert len(B.PNL_LINES["opex"]) == 4, "расходы — четыре строки по функциям"
    assert set(B.PNL_REPORTED) == {"pbt", "tax", "ni", "ni_shareholders", "ni_nci"}
    assert B.BLOCK["tax_shield"] == 0.25 and B.PNL_OPERATING_NI == "op_np"


def test_table_of_other_assets_and_liabilities():
    fixed = [k for k, s in B.OTHER_ASSETS.items() if s.get("fixed")]
    assert fixed == ["yandex_stake", "associates"], "постоянные прочие активы — пакет и ассоциированные компании"
    book_lines = {ln for s in B.BOOKS.values() for ln in s["balance"] if not ln.startswith("-")}
    other = [ln for spec in (B.OTHER_ASSETS, B.OTHER_LIABILITIES) for s in spec.values() for ln in s["lines"] if not ln.startswith("-")]
    assert not set(other) & book_lines, "строка прочих активов или обязательств уже стоит в книге"
    moved = {ln[1:] for s in B.BOOKS.values() for ln in s["balance"] if ln.startswith("-")}
    assert moved <= set(other), "строка, вычтенная из книги, обязана стоять в прочих активах (акции — вне книги бумаг)"
    for spec in (B.OTHER_ASSETS, B.OTHER_LIABILITIES):
        assert all(s["title"] for s in spec.values())


def test_committed_facts_follow_the_tables():
    """Факты собраны теми же таблицами: порядок книг, строки ОПУ, части прочих активов и обязательств."""
    f = facts()
    assert tuple(f["balance"]["books"]) == tuple(B.BOOKS) == tuple(f["nii_books"]["books"])
    assert tuple(f["balance"]["other_assets_parts"]) == tuple(B.OTHER_ASSETS)
    assert tuple(f["balance"]["other_liabilities_parts"]) == tuple(B.OTHER_LIABILITIES)
    row = f["pnl_quarterly"]["quarters"][f["anchor"]["period"]]
    assert all(k in row for k in B.PNL_LINES) and tuple(row["reported"]) == tuple(B.PNL_REPORTED)
    dates = [a["date"] for a in f["shares"]["corporate_actions"]]
    assert dates == sorted(B.ACTIONS), "корпоративные события — по таблице подписей сборщика"
    assert f["dividends"]["policy"]["cap"]["v"] == B.POLICY["cap"] and f["dividends"]["policy"]["name"] == B.POLICY["name"]


# ------------------------------------------------------------------ формулы

def test_block_of_the_stake():
    """Блок пакета из двух поправок эмитента: проценты — поправка / (1 − 0,25), без деления на долю акционеров;
    неконтролирующая доля — только эффект пакета."""
    x = B.block_of(-6.056275, -1.698894, -21.8, 4.3, 0.5001, 0.25)
    assert abs(x["debt_interest"] + 2.265192) < 1e-6 and abs(x["ni_shareholders"] + 7.755169) < 1e-6
    assert abs(x["nci"] + 6.053853) < 1e-6 and abs(x["pbt"] + 19.765192) < 1e-6
    assert abs(x["ni"] - x["ni_shareholders"] - x["nci"]) < 1e-12 and abs(x["tax"] - (x["ni"] - x["pbt"])) < 1e-12
    zero = B.block_of(0.0, 0.0, 0.0, 0.0, 0.5001, 0.25)
    assert all(v == 0 for v in zero.values())


def test_block_on_the_committed_facts():
    f = facts()
    for p, r in f["pnl_quarterly"]["quarters"].items():
        blk = r["investment_block"]
        x = B.block_of(blk["adj_stake_sh"]["v"], blk["adj_interest_sh"]["v"], blk["reval"]["v"], blk["dividends"]["v"], 0.5001, 0.25)
        for k, val in x.items():
            assert abs(val - blk[k]["v"]) < 2e-6, f"{p}.{k}"


def test_unaudited_profit_and_core_form():
    ni = {"2025Q3": 45.0, "2025Q4": 54.0, "2026Q1": 46.5, "2026Q2": 52.0}
    assert B.unaudited_profit(ni, "2026Q2", [3, 4]) == 98.5, "после отсечки 4-го квартала — прибыль двух кварталов"
    assert B.unaudited_profit(ni, "2026Q1", [3, 4]) == 46.5 and B.unaudited_profit(ni, "2025Q4", [3, 4]) == 54.0
    keys = {"ded20": 197.99, "gap20": 0.0, "fvoci_recognition": 0.64, "ded11": 168.895, "gap11": 0.00114}
    n20, n11 = B.core_form(bv=756.8, reserve=-4.6, payable=4.8, pre_dividend=False, t2=123.182, at1=0.0, rwa=5287.303,
                           unaudited=98.589488, keys=keys)
    assert abs(n20 - 0.1293) < 5e-6 and abs(n11 - 0.0940) < 5e-6
    with_dividend, _ = B.core_form(bv=756.8, reserve=-4.6, payable=4.8, pre_dividend=True, t2=123.182, at1=0.0, rwa=5287.303,
                                   unaudited=98.589488, keys=keys)
    assert abs(with_dividend - n20 - 4.8 / 5287.303) < 1e-9, "норматив до вычета дивиденда возвращает остаток к выплате"


def test_small_helpers():
    assert B.dividend_period({"fiscal_period": "2024Q1-Q3"}) == "2024Q3" and B.dividend_period({"fiscal_period": "2026Q2"}) == "2026Q2"
    assert B.page_words("6") == "с. 6" and B.page_words("22, 84") == "с. 22, 84" and B.page_words("PL!AZ107") == "PL!AZ107"
    assert B.page_words("прим. 19") == "прим. 19" and B.page_words("1–2") == "с. 1–2"
    assert B.ru(6272.1) == "6 272,1" and B.ru(-0.5, 2) == "−0,50" and B.pct(0.1293) == "12,93 %"
    assert B.d_ru("2026-10-12") == "12.10.2026" and B.d_words("2026-10-12") == "12 октября 2026 года"
    assert B.dedup("a; b; a") == "a; b" and B.na("причина") == {"v": None, "calc": "причина"}
    assert abs(B.detrended_sd([1.0, 2.0, 3.0, 4.0])) < 1e-12 and B.detrended_sd([0.0, 1.0, 0.0, 1.0]) > 0.5
    with pytest.raises(B.BuildError):
        B.node(None, "документ")
    with pytest.raises(B.BuildError):
        B.node(1.0)


def test_document_titles():
    assert "шесть месяцев 2026 года" in B.doc_title("primary/2026Q2_ifrs_fs.pdf", None)
    assert "за 2025 год" in B.doc_title("primary/FY2025_ifrs_fs.pdf", "x")
    assert B.doc_title("primary/other.pdf", "заголовок; запись — MANIFEST-x.md") == "заголовок"
    assert B.doc_title(None, None) is None
    docs = json.loads((FACTS / "anchor.json").read_text(encoding="utf-8"))["documents"]
    assert not [d["key"] for d in docs if "MANIFEST" in d["title"]], "в заголовках реестра — рабочие пометки манифестов"


# ------------------------------------------------------------------ файл отчёта квартала

def test_quarter_report_from_the_committed_facts():
    """Файл отчёта квартала для перезаякоривания: форма семейства с отличиями эмитента — период дивиденда вместо
    года, слоты нормативов банковской группы и флаг оценки, акции одной категории."""
    f = facts()
    r = B.report_from_facts(f, source="тест")
    assert r["schema"] == "quarter-report/1" and r["period"] == f["anchor"]["period"] and r["as_of"] == f["anchor"]["as_of"]
    assert tuple(r["balance"]["books"]) == BOOKS == tuple(r["interest"])
    b = r["balance"]
    assert "dividends_payable_year" not in b and isinstance(b["dividends_payable_declared"], list)
    assets = sum(b["books"][x] for x in BOOKS[:8]) - b["allowance"] + b["other_assets"]
    claims = sum(b["books"][x] for x in BOOKS[8:]) + b["other_liabilities"] + b["dividends_payable"] + b["bv_common"] + b["at1"] + b["nci"]
    assert abs(assets - claims) < 0.2 and abs(assets - f["balance"]["total_assets"]["v"]) < 1e-6
    assert b["fvoci"] == f["balance"]["securities"]["fvoci_debt"]["v"] + f["balance"]["securities"]["fvoci_repo"]["v"]
    p = r["pnl"]
    assert abs(sum(p[k] for k in ("nii", "llp_debt_fa", "fees_net", "insurance_net", "noncore_net", "opex", "misc_net")) - p["pbt"]) < 2e-6
    assert "estimated" not in p or p["estimated"] is True
    c = r["capital"]
    assert c["n20_pre_dividend"] is False and isinstance(c["estimated"], bool) and ("estimate" in c) == c["estimated"]
    assert c["n20_0"] == f["capital"]["n20_0"]["value"]["v"] and c["n1_1_bank"] == f["capital"]["n1_1_bank"]["value"]["v"]
    assert c["basel_cet1"] == f["capital"]["basel"]["cet1"]["v"] and c["t2"] == f["capital"]["t2_recognized"]["v"]
    assert set(r["shares"]) == {"issued_total", "outstanding_total", "economic_treasury", "issued_ordinary", "outstanding_ordinary"}
    assert set(r["market"]["ofz_curve"]) == {"1", "3", "5", "10"} and r["market"]["key_avg"] == f["nii_books"]["key_avg_anchor_q"]["v"]
    m = f["mgmt_quarterly"]["quarters"][r["period"]]
    assert r["mgmt"]["nim"] == (m["nim_exact"]["v"] if m["nim_exact"]["v"] is not None else m["nim"]["v"])
    assert abs(sum(r["interest"][x] for x in BOOKS[:8]) - sum(r["interest"][x] for x in BOOKS[8:]) - r["dia"]
               + f["nii_books"]["other_interest_net_q"]["v"] - p["nii"]) <= 0.15


def test_quarter_report_refuses_what_does_not_add_up():
    r = B.report_from_facts(facts(), source="тест")
    for change, why in ((lambda x: x["balance"].__setitem__("other_assets", x["balance"]["other_assets"] + 10), "баланс"),
                        (lambda x: x["pnl"].__setitem__("misc_net", x["pnl"]["misc_net"] + 1), "ОПУ"),
                        (lambda x: x["balance"]["books"].pop("cards"), "balance.books.cards"),
                        (lambda x: x.pop("shares"), "shares"),
                        (lambda x: x["balance"].__setitem__("dividends_payable_declared", [{"period": "2026Q1", "amount": 99.0}]), "объявленные")):
        bad = copy.deepcopy(r)
        change(bad)
        with pytest.raises(B.BuildError, match=why):
            B.check_report(bad)


def test_cli_report_from_ready_facts(tmp_path):
    """`--report ФАЙЛ --facts КАТАЛОГ` пишет отчёт квартала без папки передачи; чужой якорь — отказ."""
    out = tmp_path / "report.json"
    env = {k: v for k, v in os.environ.items() if k != "BANK_HANDOFF_DIR"} | {"PYTHONIOENCODING": "utf-8"}
    run = lambda *a: subprocess.run([sys.executable, "-B", str(BUILDER), *a], cwd=ROOT, env=env, capture_output=True,   # noqa: E731
                                    text=True, encoding="utf-8")
    res = run("--report", str(out), "--facts", str(FACTS))
    assert res.returncode == 0, res.stderr[-1500:]
    got = json.loads(out.read_text(encoding="utf-8"))
    assert got == B.report_from_facts(facts(), source=got["source"]) and b"\r\n" not in out.read_bytes()
    res = run("--report", str(out), "--facts", str(FACTS), "--anchor", "2019Q1")
    assert res.returncode == 1 and "ПРОВАЛ" in res.stderr


def test_cli_without_handoff_dir_refuses(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "BANK_HANDOFF_DIR"}
    res = subprocess.run([sys.executable, "-B", str(BUILDER), "--out", str(tmp_path)], cwd=ROOT, env=env,
                         capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 1 and "BANK_HANDOFF_DIR" in res.stderr and not list(tmp_path.iterdir())


def test_cli_help_names_the_arguments():
    res = subprocess.run([sys.executable, "-B", str(BUILDER), "--help"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0
    for arg in ("--anchor", "--out", "--check", "--report", "--facts"):
        assert arg in res.stdout, arg
