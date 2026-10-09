"""Литералы в `model/`: нет годов, дат, чисел книги и фактов, имени, тикеров и регномера эмитента (М§0.6, §18).

Эмитент — по книге (`meta.company`): имя, начало имени, регномер и тикеры. Тикер из трёх и более знаков
ищется границей слова; короче — только строковым литералом в кавычках (однобуквенный тикер совпал бы с
каждой переменной и обозначением формулы). Прежние имена эмитента и шаблон прежней копии кода
(`PREVIOUS_COPY`) запрещены при любой книге. Строковый литерал кода, совпавший с коротким тикером, —
в `NAMED_STRINGS` с причиной. Сканер проверяется на обеих формах эмитента: два тикера (фикстура `core`)
и один короткий (фикстура `core_t`).

Годы — сторож по образцу Ленты (`test_no_year_literals`): ни одного целого 2000…2100 вне
комментариев и строк (разбор AST). Числа книги и фактов — по образцу Ленты
(`test_no_literals`): дробные и крупные литералы кода сверяются со всеми числами книги
и фактов; совпадение разрешено только названным литералом ПО ФАЙЛУ И ЗНАЧЕНИЮ с
причиной (технические константы: четверть года, допуски, коридор массы гейта).
Модуль другого потока может назвать свои технические литералы словарём
`NAMED_LITERALS = {значение: "причина"}` в самом модуле — список виден в диффе.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
import yaml

from tests.support_core import FIXTURE_BOOK, FIXTURE_FACTS, REAL_BOOK, REAL_FACTS, real_facts_ready
from tests.support_core_t import FIXTURE_T_BOOK, FIXTURE_T_FACTS

pytestmark = pytest.mark.tact            # быстрые тесты ядра — в такте сервера (W1/C1)

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "model"
YEARS = range(2000, 2101)

# (файл, значение) → почему это не второй экземпляр допущения.
NAMED_LITERALS: dict[tuple[str, float], str] = {
    ("timeline.py", 0.25): "QUARTER_YEARS: четверть года на линейке дисконта (М§0.2)",
    ("checks.py", 1e-09): "REL_TOL: относительный допуск тождеств BV, баланса и ОПУ (М§14.1)",
    ("checks.py", 0.4): "MASS_LOW: нижний множитель коридора ожидаемой массы гейта (М§14.2)",
    ("checks.py", 0.02): "MASS_LOW/MASS_HIGH: прибавка ±0,02 коридора массы гейта (М§14.2)",
    ("checks.py", 1.5): "MASS_HIGH: верхний множитель коридора массы гейта (М§14.2)",
    ("dividends.py", 1e-09): "допуск сравнения base_div с пулом (флаг dividend_cut)",
    ("book_schema.py", 1e-09): "допуск правила «ключ года = среднее кварталов» (М§0.4)",
    ("book_schema.py", 0.5): "граница схемы: поправка делителя valuation.share_count_adj — между −0,5 и 0,5 (М§8.4)",
    ("valuation.py", 0.0001): "G_BELOW_K: защита роста терминала g_T = k_T − 1 б.п. (М§7)",
    ("grid.py", 0.5): "показатель гауссова правдоподобия A-P2u: exp(−½ × error² / дисперсия) (М§12)",
    ("grid.py", 1e-09): "SIGN_TOL: «не снижает точку» теста знака — с точностью счёта, ₽ (М§4.5)",
}

# Мелочь, которая встречается и в книге, и в любой арифметике. Половины (0,5) здесь нет: у книги десяток
# ключей, равных 0,5 (λ, ε, доли), — она разрешается только по файлу и значению с причиной.
TRIVIAL = {0.0, 1.0, 2.0}


def _numbers(value, out: set) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        out.add(round(float(value), 9))
    elif isinstance(value, dict):
        for k, v in value.items():
            _numbers(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _numbers(v, out)


def _sources():
    book_path = REAL_BOOK if REAL_BOOK.exists() else FIXTURE_BOOK
    facts_dir = REAL_FACTS if real_facts_ready() else FIXTURE_FACTS
    text = book_path.read_text(encoding="utf-8")
    book = json.loads(text) if book_path.suffix == ".json" else yaml.safe_load(text)
    facts = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(facts_dir.glob("*.json"))]
    return book, facts


def _t_sources():
    """Книга и факты фикстуры формы Т: числа второй формы эмитента сверяются с кодом при любой книге в data/."""
    book = json.loads(FIXTURE_T_BOOK.read_text(encoding="utf-8"))
    facts = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(FIXTURE_T_FACTS.glob("*.json"))]
    return book, facts


@pytest.fixture(scope="module")
def source_numbers() -> set:
    out: set = set()
    for book, facts in (_sources(), _t_sources()):
        _numbers(book, out)
        for f in facts:
            _numbers(f, out)
    return {v for v in out if v not in TRIVIAL and v != 0}


def _files():
    return sorted(p for p in MODEL.glob("*.py"))


def _module_named(tree: ast.AST) -> dict[float, str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "NAMED_LITERALS"
                                                for t in node.targets):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return {}
            return {round(float(k), 9): str(v) for k, v in value.items()}
    return {}


def year_literals(source: str) -> list[tuple[int, int]]:
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and type(node.value) is int and node.value in YEARS:
            out.append((node.lineno, node.value))
    return out


def literals_of(path: Path) -> list[tuple[int, float, str]]:
    """Дробные и крупные (≥ 10 000) числовые литералы файла."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and not isinstance(node.value, bool) \
                and isinstance(node.value, (int, float)):
            value = round(float(node.value), 9)
            if value != int(value) or abs(value) >= 10_000:
                out.append((node.lineno, value, lines[node.lineno - 1].strip()))
    return out


def test_model_has_no_year_literals():
    found = {p.name: year_literals(p.read_text(encoding="utf-8")) for p in _files()}
    found = {k: v for k, v in found.items() if v}
    assert not found, f"литералы года в model/*.py: {found} — год правила обязан быть ключом книги"


def test_year_scanner_sees_a_year_but_not_comments_or_strings():
    source = ('"""Докстрока про 2026 год."""\n'
              "x = 1 if year <= 2027 else 2   # комментарий 2028\n"
              "label = '2029'\n"
              "flag, share = True, 2030.5\n")
    assert year_literals(source) == [(2, 2027)]


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.name)
def test_no_book_or_fact_number_is_retyped(path, source_numbers):
    named = _module_named(ast.parse(path.read_text(encoding="utf-8")))
    offenders = []
    for lineno, value, line in literals_of(path):
        if value in source_numbers and (path.name, value) not in NAMED_LITERALS and value not in named:
            offenders.append(f"{path.name}:{lineno}: {value} — {line[:90]}")
    assert not offenders, ("эти числа есть в книге или фактах и должны читаться оттуда; если это "
                           "параметр проверки или арифметики — назовите его в NAMED_LITERALS:\n"
                           + "\n".join(offenders))


def test_the_scanner_sees_one_half():
    """0,5 — число книги (λ, ε): захардкоженная половина без названной причины — находка, а не «мелочь»."""
    assert 0.5 not in TRIVIAL
    from model import live, payload
    assert 0.5 in live.NAMED_LITERALS and 0.5 in payload.NAMED_LITERALS and ("grid.py", 0.5) in NAMED_LITERALS


def test_every_named_literal_still_exists():
    actual = {(p.name, v) for p in _files() for _, v, _ in literals_of(p)}
    stale = [k for k in NAMED_LITERALS if k not in actual]
    assert not stale, f"разрешения ни к чему не относятся: {stale}"


SHORT_TICKER = 3                         # тикер короче трёх знаков границей слова не ищется
# Прежние имена эмитента второй формы: ни в одном регистре, ни частью слова.
FORMER_NAMES = ("тинькоф", "tinkoff", "ткс", "tcs")
# Шаблон прежней копии кода: имя, тикеры и регномер эмитента образца.
PREVIOUS_COPY = re.compile(r"сбер|sber|1481", re.IGNORECASE)
# (файл, строковый литерал) → почему это не тикер эмитента.
NAMED_STRINGS: dict[tuple[str, str], str] = {
    ("grid.py", "T"): "ключ таблицы локальной передачи T(W) в выводимых величинах книги (results.json → derived)",
    ("book_results.py", "T"): "чтение той же таблицы T(W) для строки run_output.txt",
}


def string_literals(source: str) -> list[tuple[int, str]]:
    """Строковые литералы кода (не докстринги и не комментарии): (строка, значение)."""
    tree = ast.parse(source)
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def issuer_literals(name: str, source: str, company: dict) -> list[str]:
    """Литералы эмитента в исходнике `name`: имя и его начало, регномер, тикеры, прежние имена, шаблон
    прежней копии. Возвращает находки строками."""
    out = []
    issuer = str(company["name"])
    words = [issuer, str(company["cbr_regnum"])] + [str(t) for t in company["tickers"] if len(str(t)) >= SHORT_TICKER]
    for w in words:
        if re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", source):
            out.append(f"{name}: «{w}»")
    if re.search(re.escape(issuer[:4]), source, flags=re.IGNORECASE):
        out.append(f"{name}: «{issuer[:4]}…»")
    short = {str(t) for t in company["tickers"] if len(str(t)) < SHORT_TICKER}
    for lineno, value in string_literals(source) if short else ():
        if value in short and (name, value) not in NAMED_STRINGS:
            out.append(f"{name}:{lineno}: тикер «{value}» строковым литералом")
    low = source.lower()
    out += [f"{name}: прежнее имя «{w}…»" for w in FORMER_NAMES if w in low]
    m = PREVIOUS_COPY.search(source)
    if m:
        out.append(f"{name}: литерал прежней копии «{m.group(0)}»")
    return out


@pytest.mark.parametrize("sources", [_sources, _t_sources], ids=["книга", "форма Т"])
def test_no_issuer_name_tickers_or_regnum_in_model(sources):
    """Ни имени, ни регномера, ни тикеров эмитента — ни по книге репозитория, ни по второй форме (фикстура
    `core_t`: один короткий тикер); прежних имён и литералов прежней копии нет при любой книге."""
    book, _ = sources()
    offenders = [x for p in _files() for x in issuer_literals(p.name, p.read_text(encoding="utf-8"),
                                                              book["meta"]["company"])]
    assert not offenders, "литералы эмитента в model/: " + ", ".join(offenders)


def test_issuer_scanner_sees_a_short_ticker_only_as_a_string_literal():
    """Короткий тикер: переменная и обозначение формулы — не находка, строковый литерал — находка; длинный
    тикер, имя, регномер, прежнее имя и литерал прежней копии ловятся в любом месте исходника."""
    one = {"name": "Т-Технологии", "tickers": ["T"], "cbr_regnum": 2673}
    two = {"name": "Образец", "tickers": ["OBRZ", "OBRZP"], "cbr_regnum": 9999}
    clean = ('"""Передача T(W) = dNss/dkey; T_real — реализованная."""\n'
             "T_real = 1.0   # T — обозначение\n"
             "def f(T, n_iss):\n    return T * n_iss\n")
    assert issuer_literals("x.py", clean, one) == []
    assert issuer_literals("x.py", clean + 'prices = {"T": 330.0}\n', one) == ["x.py:5: тикер «T» строковым литералом"]
    assert issuer_literals("grid.py", clean + 'out = {"T": 1}\n', one) == []          # названный литерал
    assert issuer_literals("x.py", "regnum = 2673\n", one) == ["x.py: «2673»"]
    assert issuer_literals("x.py", "# банк Т-Технологии\n", one) == ["x.py: «Т-Технологии»", "x.py: «Т-Те…»"]
    assert issuer_literals("x.py", "x = prices[OBRZ]  # OBRZP\n", two) == ["x.py: «OBRZ»", "x.py: «OBRZP»"]
    assert issuer_literals("x.py", "url = 'tinkoff.example'\n", two) == ["x.py: прежнее имя «tinkoff…»"]
    for text in ("SCHEMA = 'sber-v1'\n", "# Сбербанк\n", "regnum = 1481\n"):
        assert any("прежней копии" in x for x in issuer_literals("x.py", text, two)), text


def test_every_named_string_still_exists():
    actual = {(p.name, v) for p in _files() for _, v in string_literals(p.read_text(encoding="utf-8"))}
    stale = [k for k in NAMED_STRINGS if k not in actual]
    assert not stale, f"разрешения ни к чему не относятся: {stale}"


def test_dates_are_not_hardcoded():
    offenders = []
    for p in _files():
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "date" \
                    and node.args and isinstance(node.args[0], ast.Constant):
                offenders.append(f"{p.name}:{node.lineno}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{4}Q[1-4]|\d{4}H[12]", node.value):
                offenders.append(f"{p.name}:{node.lineno}: {node.value}")
    assert not offenders, "даты и периоды в коде ядра: " + ", ".join(offenders)


ENV_ALLOWED = {"BANK_STATE_DIR", "BANK_DATA_REPO_DIR", "BANK_WORKERS", "GITHUB_SHA"}


def test_environment_names_have_no_bank_prefix():
    """Переменные окружения ядра — без префикса банка (М§0.6, INTERFACES §8; W1/C5): копия ядра
    под другой банк меняет только книгу и факты. Префикс тикера (`<тикер>_…`) запрещён у имён переменных
    окружения — и по книге репозитория, и по второй форме эмитента; в прочем коде короткий тикер совпал бы
    с обозначениями формул (`T_real`)."""
    tickers = sorted({str(t) for sources in (_sources, _t_sources) for t in sources()[0]["meta"]["company"]["tickers"]})
    names = set()
    for p in _files():
        text = p.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            # имя переменной: константа *_ENV = "…" или литерал в os.environ.get / os.getenv / os.environ[…]
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str) \
                    and any(isinstance(t, ast.Name) and t.id.endswith("_ENV") for t in node.targets):
                names.add(node.value.value)
            if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                    and ast.unparse(node.func) in ("os.environ.get", "os.getenv"):
                names.add(str(node.args[0].value))
            if isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ" \
                    and isinstance(node.slice, ast.Constant):
                names.add(str(node.slice.value))
    prefixed = sorted(n for n in names for t in tickers if n.upper().startswith(f"{t.upper()}_"))
    assert not prefixed, "префикс банка у переменных окружения model/: " + ", ".join(prefixed)
    assert names <= ENV_ALLOWED, sorted(names - ENV_ALLOWED)
    from model import live, payload, uncertainty
    assert (live.STATE_ENV, payload.DATA_REPO_ENV, uncertainty.WORKERS_ENV) == (
        "BANK_STATE_DIR", "BANK_DATA_REPO_DIR", "BANK_WORKERS")
