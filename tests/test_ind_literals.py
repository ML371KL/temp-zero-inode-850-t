"""В коде индикаторов нет литералов эмитента, годов и чисел книги и фактов (INTERFACES §0 п. 4, М§0.6).

Имя, тикеры и регномер — из `meta.company` книги; строки поиска, хосты и шаблоны документов эмитента,
заголовок запросов — из `data/indicators/sources.yaml`; подписи — из `meta.labels` книги; числа — из
книги, фактов и истории `data/indicators/seed/`. Технические константы (допуски, окна дней, коридоры
правдоподобия) совпасть с числом книги могут — тогда они названы здесь с причиной, по файлу: список
виден в диффе, и добавить в него число молча нельзя.

Эмитент проверяется дважды: по книге репозитория и по заглушке книги тестов (в ней тот же эмитент).
Заглушка держит проверку и на дереве с книгой другой копии: слой общий, и его литералы от книги в
`data/` не зависят. Голый тикер короче трёх знаков границей слова не проверяется (буква совпадает с
частью чужих имён: «T-Invest», `T1`); имя образца семейства ищется своим шаблоном. Префикс окружения
проверяется по именам переменных, не подстрокой.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CODE = sorted((ROOT / "indicators").glob("*.py"))
FIXTURE_BOOK = ROOT / "tests/fixtures/ind/book_meta.yaml"
YEARS = range(2000, 2101)
MIN_BARE_TICKER = 3                 # тикер короче — границей слова не проверяется
# Образец семейства (первая панель банков): его имя, тикер и регномер в общем слое остаться не должны.
PREVIOUS_COPY = re.compile(r"сбер|sber|\b1481\b", re.I)
# Хосты и имена эмитента этой копии живут в sources.yaml; в коде остаётся только адрес API брокера.
BROKER_API = re.compile(r"invest-public-api\.(?:tinkoff|tbank)\.ru(?:/rest/tinkoff\.public\.invest\.api[\w.]*)?")
ISSUER_WORDS = re.compile(r"tbank|тбанк|т-банк|т‑банк|tinkoff|тинькофф|t-technologies|росбанк", re.I)

# (файл, значение) → почему это не второй экземпляр числа книги или фактов.
NAMED_LITERALS: dict[tuple[str, float], str] = {
    ("cbr.py", 0.03): "нижняя граница коридора правдоподобия ставки (3 % годовых), как у прочих панелей семейства",
    ("iss.py", 0.03): "нижняя граница коридора правдоподобия узла кривой",
    ("cbr.py", 0.4): "верхняя граница коридора правдоподобия ставки (40 % годовых)",
    ("iss.py", 0.4): "верхняя граница коридора правдоподобия узла кривой",
    ("journal.py", 0.8): "порог правила допуска (MSE ≤ 0,8 лучшего эталона) — решение владельца",
    ("journal.py", 1.0): "порог понижения правила допуска",
    ("record.py", 0.5): "доля больше 0,5 без «%» — почти наверняка проценты (проверка ввода)",
    ("release_watch.py", 0.15): "допуск совпадения двух источников по умолчанию, млрд ₽ (sources.yaml)",
    ("release_watch.py", 0.35): "допуск тождества НМ по умолчанию, млрд ₽ (sources.yaml)",
    ("outputs.py", 0.15): "допуск сверки с формой 0409102 по умолчанию, млрд ₽ (sources.yaml)",
    ("http.py", 45.0): "тайм-аут запроса, с",
    ("http.py", 3.0): "пауза перед второй попыткой, с",
    ("http.py", 10.0): "пауза перед третьей попыткой, с",
    ("http.py", 0.35): "пауза между запросами к хосту T-Invest, с (лимит 200 в минуту)",
    ("nowcast.py", 1.0): "интервал — прогноз ± одна стандартная ошибка; w = 1 без ожидания модели",
    ("register.py", 0.005): "допуск совпадения DPS источников реестра по умолчанию — копейка (sources.yaml)",
    ("release_watch.py", 0.0005): "допуск совпадения долей двух источников по умолчанию — 0,05 п.п. (sources.yaml)",
    ("http.py", 0.5): "пауза между запросами к хосту ISS, с",
}
# 0,5 здесь нет нарочно: в книге десяток ключей, равных 0,5, — половина разрешается только по файлу.
TRIVIAL = {0.0, 1.0, 2.0, 100.0, 1000.0, 1e-6, 1e-9, 1e-12}

pytestmark = pytest.mark.tact


def _company(path: Path) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {})["meta"]["company"]


def _issuers() -> list[dict]:
    """Эмитент заглушки книги тестов и эмитент книги репозитория (машинной, без неё — её исходника)."""
    out = [_company(FIXTURE_BOOK)]
    for name in ("assumptions.yaml", "assumptions.draft.yaml"):
        book = ROOT / "data" / "assumptions" / name
        if book.exists():
            out.append(_company(book))
            break
    return out


def _numbers(obj, out: set[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _numbers(v, out)


def _data_numbers() -> set[float]:
    out: set[float] = set()
    for book in (ROOT / "data/assumptions/assumptions.yaml", ROOT / "data/assumptions/assumptions.draft.yaml"):
        if book.exists():
            _numbers(yaml.safe_load(book.read_text(encoding="utf-8")), out)
    for path in sorted((ROOT / "data" / "facts").glob("*.json")) + sorted((ROOT / "data/indicators/seed").glob("*.json")):
        _numbers(json.loads(path.read_text(encoding="utf-8")), out)
    return out


def _constants(source: str) -> list[tuple[int, float]]:
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            out.append((node.lineno, node.value))
    return out


def issuer_patterns(company: dict) -> list[re.Pattern]:
    """Шаблоны эмитента: тикеры от трёх знаков — целым словом, регномер, начало имени."""
    patterns = [re.compile(rf"\b{re.escape(str(t))}\b") for t in company["tickers"] if len(str(t)) >= MIN_BARE_TICKER]
    patterns.append(re.compile(rf"\b{re.escape(str(company['cbr_regnum']))}\b"))
    patterns.append(re.compile(re.escape(str(company["name"])[:4]), re.I))
    return patterns


def test_no_year_literals_in_indicators():
    found = {p.name: [(ln, v) for ln, v in _constants(p.read_text(encoding="utf-8"))
                      if type(v) is int and v in YEARS] for p in CODE}
    found = {k: v for k, v in found.items() if v}
    assert not found, f"литералы года в indicators/: {found}"


def test_no_issuer_literals_in_indicators():
    patterns = [pat for company in _issuers() for pat in issuer_patterns(company)]
    cfg = yaml.safe_load((ROOT / "data/indicators/sources.yaml").read_text(encoding="utf-8"))
    for ch in cfg["news"]["telegram_channels"]:
        patterns.append(re.compile(re.escape(ch["name"] if isinstance(ch, dict) else ch)))
    for host in cfg["issuer_docs"]["hosts"] + cfg["issuer_docs"]["fallback_hosts"]:
        patterns.append(re.compile(re.escape(host), re.I))
    patterns += [PREVIOUS_COPY, ISSUER_WORDS]
    bad = []
    for p in CODE:
        text = BROKER_API.sub("<адрес API брокера>", p.read_text(encoding="utf-8"))
        for pat in patterns:
            for m in pat.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                bad.append(f"{p.name}:{line}: {m.group(0)}")
    assert not bad, "литералы эмитента в indicators/ (им место — книга и sources.yaml): " + "; ".join(sorted(set(bad)))


def test_the_issuer_scanner_has_teeth_and_skips_a_bare_short_ticker():
    short = {"name": "Т-Технологии", "tickers": ["T"], "cbr_regnum": 2673}
    hits = lambda text: [m.group(0) for pat in issuer_patterns(short) for m in pat.finditer(text)]  # noqa: E731
    assert hits('SOURCE = "T-Invest"; T1 = 1; TOKEN_ENV = "TINVEST_TOKEN"') == []      # буква тикера — не литерал
    assert hits("regnum = 2673") == ["2673"] and hits("# т-технологии") == ["т-те"]
    long = {"name": "Банк Пример", "tickers": ["PRMR"], "cbr_regnum": 1}
    assert [m.group(0) for pat in issuer_patterns(long) for m in pat.finditer('t = "PRMR"; x = "PRMRP"')] == ["PRMR"]
    assert PREVIOUS_COPY.search("indicators.sber_pdf") and PREVIOUS_COPY.search("регномер 1481")
    assert not PREVIOUS_COPY.search("x = 14810") and ISSUER_WORDS.search("https://cdn.tbank.ru/a.pdf")


def test_the_scanner_has_teeth():
    assert _constants("x = 2027 if y else 2.5\n'2028'\n") == [(1, 2027), (1, 2.5)]


def test_no_numbers_of_the_book_or_facts_in_code():
    data = _data_numbers()
    bad = []
    for p in CODE:
        for ln, v in _constants(p.read_text(encoding="utf-8")):
            if type(v) is int and abs(v) < 10_000:
                continue                      # счётчики, дни, коды — не числа книги
            fv = float(v)
            if fv in TRIVIAL or fv not in data:
                continue
            if (p.name, fv) in NAMED_LITERALS:
                continue
            bad.append(f"{p.name}:{ln}: {v}")
    assert not bad, "числа книги, фактов или истории в indicators/: " + "; ".join(bad)


def test_half_is_not_trivial_and_is_allowed_by_file_only():
    """0,5 — число книги (ключи, равные половине): сканер его видит, разрешение — по файлу с причиной."""
    assert 0.5 not in TRIVIAL
    allowed = {name for (name, value) in NAMED_LITERALS if value == 0.5}
    seen = {p.name for p in CODE if 0.5 in {float(v) for _, v in _constants(p.read_text(encoding="utf-8"))}}
    assert seen == allowed, f"0,5 в коде без названной причины: {sorted(seen - allowed)}"


def test_the_integer_key_of_the_book_is_read_not_hardcoded(monkeypatch, tmp_path):
    """Целые сканер не ловит — их проверяет чувствительность: лаг решения книги двигает тревогу реестра."""
    from datetime import date

    from indicators import collect, config
    from indicators.store import Store

    book = yaml.safe_load(FIXTURE_BOOK.read_text(encoding="utf-8"))
    seen = {}
    for lag in (1, 2):
        book["dividends"]["calendar"]["decision_lag_quarters"] = lag
        path = tmp_path / f"book{lag}.yaml"
        path.write_text(yaml.safe_dump(book, allow_unicode=True), encoding="utf-8")
        monkeypatch.setattr(config, "BOOK_PATH", path)
        monkeypatch.setattr(config, "FACTS_DIR", ROOT / "tests/fixtures/ind/facts")
        store = Store(tmp_path / f"state{lag}")
        # первый открытый квартал закрыт выплаченной записью: решает лаг второго
        store.write_state("manual/dividends.json", {"records": [
            {"year": 2026, "period": "2026Q1", "dps": 4.6, "status": "declared", "record_date": "2026-08-10",
             "pay_date": "2026-08-24", "decided_date": "2026-07-30", "source": "протокол", "origin": "issuer_docs",
             "recorded_at": "2026-08-01T07:00:00+00:00"}]})
        ctx = collect.context(store, date(2026, 10, 15))
        seen[lag] = collect.register_check(ctx).status
    # 15.10: квартал решения за второй квартал при лаге 1 (третий квартал) кончился, при лаге 2 — нет
    assert seen == {1: "degraded", 2: "ok"}


def test_every_named_literal_still_exists():
    for (name, value), why in NAMED_LITERALS.items():
        consts = {float(v) for _, v in _constants((ROOT / "indicators" / name).read_text(encoding="utf-8"))}
        assert value in consts, f"{name}: {value} больше нет — уберите из NAMED_LITERALS ({why})"


def test_environment_variables_have_no_bank_prefix():
    """Копия ядра под другой банк меняет только книгу и факты — переменные `BANK_*` и `TINVEST_TOKEN`.
    Проверяются имена переменных окружения (константы `*_ENV` и строки в обращениях к `environ`), а не
    подстрока «<тикер>_» в тексте: у короткого тикера она совпала бы с обычными именами."""
    from indicators import config, tinvest

    assert (config.STATE_ENV, config.HANDOFF_ENV, tinvest.TOKEN_ENV) == (
        "BANK_STATE_DIR", "BANK_HANDOFF_DIR", "TINVEST_TOKEN")
    names = set()
    for p in CODE:
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            # имя переменной — константа `*_ENV = "…"` или строка прямо в `os.environ.get("…")`
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and any(
                    isinstance(t, ast.Name) and t.id.endswith("_ENV") for t in node.targets):
                names.add(node.value.value)
            if isinstance(node, ast.Call) and "environ" in ast.unparse(node.func) and node.args \
                    and isinstance(node.args[0], ast.Constant):
                names.add(node.args[0].value)
    assert names == {"BANK_STATE_DIR", "BANK_HANDOFF_DIR", "TINVEST_TOKEN"}, names
    prefixes = {str(t).upper() + "_" for company in _issuers() for t in company["tickers"]} | {"TTECH_"}
    bad = sorted(n for n in names if any(n.startswith(x) for x in prefixes) and n != "TINVEST_TOKEN")
    assert not bad, "переменные окружения с префиксом банка в indicators/: " + ", ".join(bad)
