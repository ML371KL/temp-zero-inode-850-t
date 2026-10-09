# -*- coding: utf-8 -*-
"""Инструменты оператора `ops/tools/`: числа в документах, прогулка книги,
миры семейства, проба источников (адрес PDF эмитента — из затравки, дымовая проверка
распознавания), замер времени и памяти команды, худший по времени случай сборки
(цена у медианы). Сети нет: проба ходит в фикстуры индикаторов. Инструмент бюджета
проверяют tests/test_ops_units.py и tests/test_ops_ci.py."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "ops" / "tools"
FIXTURE_BOOK = ROOT / "tests" / "fixtures" / "core" / "book.json"
FIXTURE_FACTS = ROOT / "tests" / "fixtures" / "core" / "facts"
BOOK = ROOT / "data" / "assumptions"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"tool_{name}", TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------ render_numbers

render_numbers = _load("render_numbers")
RESULTS = {"headline": {"printed_median": 350.0, "band80": [300.25, 410.0], "p_below": 0.123},
           "reverse_dcf": {"rows": [{"axis": "ERP", "value": -0.0186}, {"axis": "ROE", "value": None}]},
           "cells": [{"cell": {"world": "M", "regime": "norm"}, "v": 12345.678}]}


@pytest.mark.parametrize("path,fmt,text", [
    ("headline.printed_median", "r0", "350"),
    ("headline.band80[0]", "r1", "300,2"),
    ("headline.p_below", "p1", "12,3"),
    ("reverse_dcf.rows[axis=ERP].value", "sp2", "−1,86"),
    ("reverse_dcf.rows[axis=ROE].value", "sp2n", "недостижимо"),
    ("cells[cell.world=M&cell.regime=norm].v", "r0", "12 346"),
])
def test_marks_resolve_and_format_like_the_documents(path, fmt, text):
    assert render_numbers.formatted(render_numbers.resolve(RESULTS, path), fmt) == text


def test_render_rewrites_values_and_reports_broken_marks():
    doc = "Медиана ≈<!--=headline.printed_median r0-->1<!--/--> ₽, `<!--=x r0-->пример<!--/-->`.\n"
    new, errors = render_numbers.render(doc, RESULTS)
    assert errors == [] and "<!--=headline.printed_median r0-->350<!--/-->" in new
    assert "`<!--=x r0-->пример<!--/-->`" in new, "метка в коде — пример синтаксиса"
    _, errors = render_numbers.render("x <!--=нет.пути r0-->1<!--/-->\n", RESULTS)
    assert errors and "нет ключа" in errors[0]
    _, errors = render_numbers.render("<!--=headline.printed_median r0-->1<!--/--> в начале\n", RESULTS)
    assert errors and "в начале строки" in errors[0]


def test_render_check_on_a_tree(tmp_path, capsys):
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    assert render_numbers.main(["--check", "--root", str(root)]) == 0, "меток нет — сверять нечего"
    doc = root / "docs" / "X.md"
    doc.write_text("Медиана ≈<!--=headline.printed_median r0-->1<!--/--> ₽\n", encoding="utf-8")
    assert render_numbers.main(["--check", "--root", str(root)]) == 1, "метки есть, результатов нет"
    (root / "data" / "assumptions").mkdir(parents=True)
    (root / "data" / "assumptions" / "results.json").write_text(json.dumps(RESULTS), encoding="utf-8")
    assert render_numbers.main(["--check", "--root", str(root)]) == 1
    assert "устарел: docs/X.md" in capsys.readouterr().err
    assert render_numbers.main(["--root", str(root)]) == 0
    assert "≈<!--=headline.printed_median r0-->350<!--/--> ₽" in doc.read_text(encoding="utf-8")
    assert render_numbers.main(["--check", "--root", str(root)]) == 0


# ------------------------------------------------------------ walk_book

@pytest.fixture(scope="module")
def walk_book():
    return _load("walk_book")


def _steps(tmp_path: Path, steps) -> Path:
    path = tmp_path / "steps.yaml"
    path.write_text(yaml.safe_dump(steps, allow_unicode=True), encoding="utf-8")
    return path


def test_the_walk_between_two_books_converges(tmp_path, walk_book, capsys):
    end = json.loads(FIXTURE_BOOK.read_text(encoding="utf-8"))
    end["valuation"]["beta_e"] = round(end["valuation"]["beta_e"] + 0.05, 4)
    end["valuation"]["erp"] = round(end["valuation"]["erp"] + 0.003, 5)
    (tmp_path / "end.json").write_text(json.dumps(end, ensure_ascii=False), encoding="utf-8")
    steps = _steps(tmp_path, [{"name": "β", "from_end": ["valuation.beta_e"]},
                              {"name": "ERP", "from_end": ["valuation.erp"]}])
    code = walk_book.main(["--start", str(FIXTURE_BOOK), "--end", str(tmp_path / "end.json"),
                           "--steps", str(steps), "--facts", str(FIXTURE_FACTS),
                           "--json", str(tmp_path / "walk.json")])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "последний шаг = прямой расчёт конечной книги: ДА" in out
    assert "книга после шагов = конечная книга целиком: ДА" in out
    rows = json.loads((tmp_path / "walk.json").read_text(encoding="utf-8"))["rows"]
    assert [r["step"] for r in rows] == ["старт", "β", "ERP"]
    assert rows[1]["point"] < rows[0]["point"], "выше β — выше стоимость капитала, ниже точка"

    partial = _steps(tmp_path, [{"name": "только β", "from_end": ["valuation.beta_e"]}])
    code = walk_book.main(["--start", str(FIXTURE_BOOK), "--end", str(tmp_path / "end.json"),
                           "--steps", str(partial), "--facts", str(FIXTURE_FACTS)])
    assert code == 1 and "конечная книга целиком: НЕТ" in capsys.readouterr().out


def test_a_step_that_breaks_the_book_is_refused(tmp_path, walk_book, capsys):
    steps = _steps(tmp_path, [{"name": "незнакомый ключ", "set": {"valuation.no_such_key": 1}}])
    code = walk_book.main(["--start", str(FIXTURE_BOOK), "--end", str(FIXTURE_BOOK),
                           "--steps", str(steps), "--facts", str(FIXTURE_FACTS)])
    assert code == 2
    assert "шаг 1 «незнакомый ключ»" in capsys.readouterr().err
    bad = _steps(tmp_path, [{"name": "без правок"}])
    assert walk_book.main(["--start", str(FIXTURE_BOOK), "--end", str(FIXTURE_BOOK),
                           "--steps", str(bad), "--facts", str(FIXTURE_FACTS)]) == 2


# ------------------------------------------------------------ refresh_worlds

@pytest.fixture(scope="module")
def refresh_worlds():
    return _load("refresh_worlds")


def _needs_book():
    if not (BOOK / "assumptions.yaml").exists() or not (BOOK / "worlds_source.json").exists():
        pytest.skip("книги 1.0 ещё нет в data/assumptions/ (поток book)")


def test_the_world_canon_holds(refresh_worlds, capsys):
    _needs_book()
    assert refresh_worlds.main(["--check"]) == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    assert "рецепт воспроизводит worlds_source.json" in out and "воспроизводится сборкой" in out


def test_a_broken_record_breaks_the_canon(refresh_worlds, tmp_path):
    _needs_book()
    book = tmp_path / "assumptions"
    shutil.copytree(BOOK, book, ignore=shutil.ignore_patterns("evidence", "__pycache__"))
    record = json.loads((book / "worlds_source.json").read_text(encoding="utf-8"))
    record["rows"][0]["key_avg"] = record["rows"][0]["key_avg"] + 1.0
    (book / "worlds_source.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    problems, _ = refresh_worlds.check_canon(book)
    assert any("рецепт не воспроизводит" in p for p in problems), problems
    assert any("sha256" in p for p in problems), problems


def test_a_candidate_of_the_same_record_changes_nothing(refresh_worlds, tmp_path):
    _needs_book()
    record = tmp_path / "record"
    record.mkdir()
    shutil.copyfile(BOOK / "worlds_source.json", record / "worlds_source.json")
    before = {p.name: p.read_bytes() for p in BOOK.iterdir() if p.is_file()}
    out = tmp_path / "candidate"
    assert refresh_worlds.main(["--record", str(record), "--out", str(out)]) == 0
    assert (out / "assumptions.candidate.yaml").read_text(encoding="utf-8") == \
        (BOOK / "assumptions.yaml").read_text(encoding="utf-8")
    report = (out / "CANDIDATE.md").read_text(encoding="utf-8")
    assert "Что меняется в записи (0)" in report and "| точка при λ книги, ₽ |" in report
    assert {p.name: p.read_bytes() for p in BOOK.iterdir() if p.is_file()} == before, "книга не тронута"


def test_the_candidate_never_writes_into_the_book(refresh_worlds, tmp_path, capsys):
    _needs_book()
    record = tmp_path / "record"
    record.mkdir()
    shutil.copyfile(BOOK / "worlds_source.json", record / "worlds_source.json")
    assert refresh_worlds.main(["--record", str(record), "--out", str(BOOK / "candidate")]) == 1
    assert "не пишет в книгу" in capsys.readouterr().err
    assert not (BOOK / "candidate").exists()


def test_the_candidate_template_changes_only_the_record_lines(refresh_worlds):
    _needs_book()
    text = (BOOK / "assumptions_template.yaml").read_text(encoding="utf-8")
    new = refresh_worlds.candidate_template(text, sha="f" * 64, asof="2026-10-24", curve_date="2026-10-23")
    changed = [(a, b) for a, b in zip(text.splitlines(), new.splitlines()) if a != b]
    assert len(text.splitlines()) == len(new.splitlines())
    assert {a.split(":")[0].strip() for a, _ in changed} <= {"sha256", "record_asof", "curve_date", "curve_as_of"}
    assert any('"' + "f" * 64 + '"' in b for _, b in changed)


# ------------------------------------------------------------ probe

@pytest.fixture
def probe(monkeypatch, tmp_path):
    from tests.support_ind import use_fixtures

    use_fixtures(monkeypatch, tmp_path, token=False)
    return _load("probe")


def _fake_tls(host, context):
    if context is None:
        import ssl

        raise ssl.SSLCertVerificationError(1, "unable to get local issuer certificate")
    return "Russian Trusted Root CA"


PDF = b"%PDF-1.7 fixture"
DOCS = {"dataservice": b'[{"id": 1, "category_name": "x"}]', "/static/documents/": PDF}


def test_the_probe_walks_every_source_through_the_collector_road(probe, monkeypatch):
    from tests.support_ind import FakeGetter

    getter = FakeGetter(overrides=DOCS)
    rows = probe.run(getter=getter, tls=_fake_tls)
    by = {(r.probe, r.what): r for r in rows}
    assert {r.probe for r in rows} == set(probe.PROBES)
    forms = [r for r in rows if r.probe == "cbr_forms"]
    assert len(forms) == 4 and all(r.ok for r in forms), [r.note for r in forms]
    assert {r.what.split()[0] for r in forms} == {f"GetDatesForF{f}" for f in probe.FORMS}
    for r in rows:
        if r.probe != "tinvest":
            assert r.ok, (r.probe, r.what, r.note)
    assert by[("tinvest", "TLS с закреплённым корнем")].ok
    assert "как ожидается" in by[("tinvest", "TLS без закреплённого корня (справочно)")].note
    share = by[("tinvest", "ShareBy главного тикера (токен из окружения)")]
    assert not share.ok and "TINVEST_TOKEN" in share.note
    table = probe.table(rows)
    assert table.count("\n") == len(rows) + 1 and "| НЕТ " in table
    assert all("?" not in r.target for r in rows), "адреса без строки запроса"


def test_the_probe_of_the_group_forms_needs_numbers_not_a_status_code(probe):
    """Формы банковской группы: код организации, перечень периодов, форма 0409805 за последний период —
    проба засчитана, только когда в форме есть итог капитала и Н20.0 числами."""
    from tests.support_ind import FIX, FakeGetter

    rows = probe.run(["cbr_group"], getter=FakeGetter(), tls=_fake_tls)
    assert [r.what.split()[0].rstrip(":") for r in rows] == ["RegNumToIntCode", "GetPeriodsOfDocuments", "GetF805Xml"]
    assert all(r.ok for r in rows), [r.note for r in rows]
    assert "последний 2026Q2" in rows[1].note and "0409805 — 10" in rows[1].note
    assert "капитал 680.0 млрд ₽" in rows[2].note and "Н20.0 12.80%" in rows[2].note
    empty = {("CreditOrgInfo", "<par>1</par>"): (FIX / "cbr_group/f805_absent_par1.xml").read_bytes(),
             ("CreditOrgInfo", "<par>4</par>"): (FIX / "cbr_group/f805_absent_par4.xml").read_bytes()}
    rows = probe.run(["cbr_group"], getter=FakeGetter(overrides=empty), tls=_fake_tls)
    assert [r.ok for r in rows] == [True, True, False] and "чисел в форме нет" in rows[2].note      # код ответа — 200
    stub = probe.run(["cbr_group"], getter=FakeGetter(overrides={"GetPeriodsOfDocuments": b"<html>stub</html>"}),
                     tls=_fake_tls)
    assert [r.ok for r in stub] == [True, False, False] and "не перечень" in stub[1].note


def test_the_probe_of_the_issuer_documents(probe, tmp_path):
    """Документы эмитента: страница пресс-релизов, каждая папка двери на рабочем хосте, первая папка — на
    запасном хосте с закреплённым корнем, документ месячного релиза с рабочего хоста."""
    from indicators import config, http
    from tests.support_ind import FakeGetter

    cfg = config.sources()
    getter = FakeGetter(overrides=DOCS)
    rows = probe.probe_issuer_docs(getter, cfg=cfg, state=tmp_path / "нет")
    assert all(r.ok and r.probe == "issuer_docs" for r in rows), [(r.what, r.note) for r in rows if not r.ok]
    whats = [r.what for r in rows]
    folders = cfg["issuer_docs"]["door"]["folders"]
    assert whats[0] == "страница пресс-релизов" and len([w for w in whats if w.startswith("дверь документов: ")]) == len(folders)
    assert "записей 3, месячных релизов 1" in rows[0].note
    spare = next(r for r in rows if "запасном хосте" in r.what)
    assert spare.target.startswith("cfg.tbank.ru/")
    assert http.tls_context("https://cdn.tbank-online.com/x") is None          # рабочим хостам чужой корень не нужен
    doc = rows[-1]
    assert doc.what == probe.DOCS_WHAT and doc.target.startswith("cdn.tbank-online.com/static/documents/")
    assert "адрес из списка эмитента (2026M09)" in doc.note and "PDF, sha256" in doc.note
    assert all("?" not in r.target for r in rows)
    # порядок адреса: --pdf → состояние сборщика → список эмитента
    listed = [{"url": "https://cdn.tbank-online.com/static/documents/a.pdf", "kind": "ops_release", "date": "2026-10-23",
               "period": "2026M09"},
              {"url": "https://cdn.tbank-online.com/static/documents/b.pdf", "kind": "ifrs_press", "date": "2026-11-19"}]
    empty = tmp_path / "state"
    assert probe.doc_address(cfg, state=empty, listed=listed) == (listed[0]["url"], "адрес из списка эмитента (2026M09)")
    assert probe.doc_address(cfg, state=empty, listed=listed[1:]) == (None, "адреса нет")
    (empty / "issuer_docs").mkdir(parents=True)
    known = "https://cdn.tbank-online.com/static/documents/c.pdf"
    (empty / "issuer_docs" / "index.json").write_text(json.dumps({
        known: {"kind": "ops_release", "listed": "2026-11-24"},
        "https://cdn.tbank-online.com/static/documents/d.pdf": {"kind": "meeting_minutes", "listed": "2026-12-20"}}),
        encoding="utf-8")
    assert probe.doc_address(cfg, state=empty, listed=listed) == (known, "адрес сборщика (состояние)")
    assert probe.doc_address(cfg, pdf="https://cdn.tbank-online.com/x.pdf", state=empty, listed=listed) == (
        "https://cdn.tbank-online.com/x.pdf", "адрес из --pdf")
    # страница вместо файла, чужой хост и молчащий источник — строка «НЕТ» с причиной, а не падение
    page = probe.probe_issuer_docs(FakeGetter(overrides={"/static/documents/": b"<html>404</html>"}), cfg=cfg,
                                   state=tmp_path / "нет")
    assert not page[-1].ok and "ответ не PDF" in page[-1].note
    alien = probe.probe_issuer_docs(FakeGetter(overrides=DOCS), cfg=cfg, pdf="https://files.example.org/x.pdf")
    assert not alien[-1].ok and "не на хосте эмитента" in alien[-1].note
    dead = FakeGetter(overrides={"/press-releases/": http.FetchError("x", 503, "HTTP 503"),
                                 "getFolderTree": http.FetchError("x", 503, "HTTP 503")})
    rows = probe.probe_issuer_docs(dead, cfg=cfg, state=tmp_path / "нет")
    assert not any(r.ok for r in rows) and "--pdf" in rows[-1].note and rows[0].status == "503"


def test_the_probe_names_a_failure_instead_of_falling(probe):
    from tests.support_ind import FakeGetter
    from indicators import http

    getter = FakeGetter(overrides={"iss.moex.com": http.FetchError("https://iss.moex.com/x", 503, "HTTP 503"),
                                   "/static/documents/": http.FetchError("https://cdn.example/x.pdf", 404, "HTTP 404")})
    rows = probe.run(["iss", "issuer_docs"], getter=getter, tls=_fake_tls)
    iss_rows = [r for r in rows if r.probe == "iss"]
    assert iss_rows and all(not r.ok and r.status == "503" for r in iss_rows)
    doc = [r for r in rows if r.probe == "issuer_docs"][-1]
    assert not doc.ok and doc.status == "404", "файл не отдаётся — строка «НЕТ» с кодом, а не падение"


@pytest.mark.tact
def test_the_probe_passes_on_the_empty_state_of_a_fresh_server(monkeypatch, tmp_path, capsys):
    """Приёмка установки: проба без аргументов на пустом состоянии кончается кодом 0, когда источники
    исправны, — адрес документа эмитента берётся из только что снятого списка, и строка таблицы говорит,
    откуда он. Пробы распознавания нет: документы эмитента с текстовым слоем."""
    from tests.support_ind import FakeGetter, use_fixtures

    state = use_fixtures(monkeypatch, tmp_path, token=True)
    probe = _load("probe")
    assert not state.exists(), "состояние пусто: сборщик ничего не находил"
    rows = probe.run(getter=FakeGetter(overrides=DOCS), tls=_fake_tls)
    assert all(r.ok for r in rows), [(r.probe, r.what, r.note) for r in rows if not r.ok]
    doc = [r for r in rows if r.probe == "issuer_docs"][-1]
    assert "адрес из списка эмитента" in doc.note
    assert probe.EXTRA_PROBES == () and {"issuer_docs", "cbr_group"} <= set(probe.PROBES)
    monkeypatch.setattr(probe, "run", lambda only, pdf=None: rows)
    assert probe.main([]) == 0
    assert f"проб {len(rows)}, прошли {len(rows)}" in capsys.readouterr().out


def test_the_probe_never_prints_the_token(probe, monkeypatch, capsys):
    from tests.support_ind import FAKE_TOKEN, FakeGetter

    monkeypatch.setenv("TINVEST_TOKEN", FAKE_TOKEN)
    rows = probe.run(["tinvest"], getter=FakeGetter(), tls=_fake_tls)
    assert all(r.ok for r in rows), [r.note for r in rows]
    text = probe.table(rows) + json.dumps([r.__dict__ for r in rows], ensure_ascii=False)
    assert FAKE_TOKEN not in text


def test_the_probe_command_line(probe, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(probe, "run", lambda only, pdf=None: [
        probe.Row("iss", "котировки", "iss.moex.com/x", True, "200", 0.1, 10, "ок")])
    assert probe.main(["--only", "iss", "--json", str(tmp_path / "p.json")]) == 0
    assert "проб 1, прошли 1" in capsys.readouterr().out
    assert json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))[0]["probe"] == "iss"
    assert probe.main(["--only", "нет_такой"]) == 64
    assert probe.main(["--only", "issuer_docs", "cbr_group"]) == 0


# ------------------------------------------------------------ measure

def test_the_measure_reports_time_and_the_memory_of_the_process_tree(tmp_path, capsys):
    """Замер сборки до установки юнитов (ops/README.md §5): время, пик памяти дерева процессов — команды
    вместе с дочерними, — наибольший процесс; код возврата — код самой команды."""
    measure = _load("measure")
    child = "import time; held = bytearray(b'x') * (48 * 2**20); time.sleep(1.5)"
    parent = ("import subprocess, sys, time; held = bytearray(b'x') * (24 * 2**20); "
              f"child = subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(1.0); child.wait(); sys.exit(3)")
    out = tmp_path / "measure.json"
    code = measure.main(["--json", str(out), "--every", "0.1", "--", sys.executable, "-c", parent])
    result = json.loads(out.read_text(encoding="utf-8"))
    assert code == 3 == result["returncode"] and result["command"][-1] == parent
    assert result["peak_processes"] >= 2 and result["peak_process_mb"] >= 40
    assert result["peak_tree_mb"] >= result["peak_process_mb"] + 20, "память дерева — сумма по процессам"
    assert 1.0 <= result["seconds"] < 60 and result["memory"] in ("pss", "rss", "working_set")
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert line.startswith("замер: ") and "пик памяти дерева" in line and line.endswith("код команды 3")
    assert measure.report({**result, "workers": "4"}).count("; BANK_WORKERS=4; код команды 3") == 1
    # дерево — процесс и все его потомки; чужие процессы в него не входят
    assert measure.tree(1, {2: 1, 3: 2, 4: 9, 9: 9}) == [1, 2, 3]
    assert measure.main(["--", "команды-с-таким-именем-нет"]) == 127
    with pytest.raises(SystemExit):
        measure.main(["--json", str(out)])


# ------------------------------------------------------------ worst_build

def test_the_worst_build_bound_completes_the_refinement_steps():
    """Оценка сверху времени сборки (ops/README.md §9): каждая строка обратного расчёта, уточнённая на полной
    полосе, — с полным числом шагов уточнения. Недостающие полосы добавляются временем одной полной полосы;
    уже посчитанные второй раз не считаются."""
    worst = _load("worst_build")
    # пять строк в диапазоне, шагов до двух — десять полос; посчитано семь (14 000 сеток по 2 000) — не хватает трёх
    assert worst.upper_bound(900.0, 5, 14000, draws=2000, refine=2, band_seconds=90.0) == pytest.approx(1170.0)
    assert worst.upper_bound(900.0, 5, 20000, draws=2000, refine=2, band_seconds=90.0) == 900.0   # все шаги сделаны
    assert worst.upper_bound(270.0, 0, 0, draws=2000, refine=2, band_seconds=90.0) == 270.0       # уточнять нечего
    payload = {"reverse_dcf": {"rows": [{"gap_basis": "full"}, {"gap_basis": "subsample"}],
                               "bank_rows": [{"key": "строка банка"}], "full_grids": 4000}}
    assert worst.refined(payload) == (2, 1, 4000) and worst.refined({}) == (0, 0, 0)   # банковские строки — не поиск
    assert worst.DEFAULT_STOPS > 1, "ближе одного стопа к медиане поиска нет: это лучший случай, а не худший"


@pytest.mark.ci_only
def test_the_worst_build_runs_in_memory_at_the_prices_near_the_median(tmp_path, monkeypatch, capsys):
    """Худший случай сборки меряется подменой цены (ops/README.md §5, шаг 8): инструмент ставит цену главного
    тикера книги рядом с медианой — выше и ниже, дальше стопа поиска — и собирает выпуск в памяти, не трогая
    состояние. Быстрая сборка проверяет сам инструмент; цену ближе одного стопа он не ставит."""
    worst = _load("worst_build")
    state = tmp_path / "state"
    monkeypatch.setenv("BANK_STATE_DIR", str(state))
    out = tmp_path / "worst.json"
    assert worst.main(["--fast", "--json", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    up, down = result["builds"]
    assert result["fast"] and result["stop"] > 0 and result["refine"] >= 1
    assert up["price"] == pytest.approx(result["median"] + worst.DEFAULT_STOPS * result["stop"], abs=1e-3)
    assert down["price"] == pytest.approx(result["median"] - worst.DEFAULT_STOPS * result["stop"], abs=1e-3)
    assert result["worst_seconds"] >= max(up["bound"], down["bound"]) >= max(up["seconds"], down["seconds"])
    assert up["reverse_rows"] == down["reverse_rows"] > 0
    assert not state.exists() or not any(state.iterdir()), "сборка в памяти: каталог состояния не тронут"
    text = capsys.readouterr().out
    assert text.count("\nцена ") == 2 and "замером худшего случая это не служит" in text
    assert worst.main(["--fast", "--stops", "1"]) == 2 and "поиска не запускает" in capsys.readouterr().err
    assert worst.main(["--fast", "--price", "0"]) == 2 and "не положительное число" in capsys.readouterr().err
