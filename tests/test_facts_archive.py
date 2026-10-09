"""Факты против папки передачи (маркер archive; в CI пропускается).

Сборщик воспроизводит data/facts байт в байт и печатает сверки без сбоев; sha256 каждого документа реестров
(anchor.json → documents, sources календаря и аналогов) совпадает с файлом в папке передачи; файл отчёта квартала
из сборки равен файлу из закоммиченных фактов; якорь без листов — отказ.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "data" / "facts"
BUILDER = ROOT / "ops" / "tools" / "build_facts.py"
BUILT = ("anchor", "balance", "nii_books", "pnl_quarterly", "capital", "shares", "dividends",
         "bridge_mgmt_ifrs", "bridge_ras_ifrs", "mgmt_quarterly", "guidance")
# Сверки, которые сборщик обязан напечатать (сводка этапа 1, раздел 4, п. 4): слова из названия сверки.
CHECKS = ("баланс якоря: Σ книг активов − резерв + прочие активы = активы", "состав книг (таблица 1) = листу книг",
          "проценты книг − страхование вкладов + проценты вне книг = ЧПД", "отчётная прибыль акционеров = операционная + блок пакета",
          "прибыль движка квартала якоря = операционной прибыли эмитента", "сумма прибыли движка за", "нормативы формой ядра",
          "дивиденды: решения после дробления", "дивиденды: сверка с брокерским календарём", "мосты упр. ↔ движок")

pytestmark = pytest.mark.archive


def handoff() -> Path:
    root = os.environ.get("BANK_HANDOFF_DIR")
    if not root or not Path(root).is_dir():
        pytest.skip("нет папки передачи (BANK_HANDOFF_DIR)")
    return Path(root)


def run(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, BANK_HANDOFF_DIR=str(handoff()), PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-B", str(BUILDER), *args], cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8")


def test_builder_reproduces_facts_and_prints_the_checks(tmp_path):
    res = run("--out", str(tmp_path))
    assert res.returncode == 0, res.stdout[-2000:] + res.stderr[-2000:]
    assert "СБОЙ" not in res.stdout
    missing = [c for c in CHECKS if c not in res.stdout]
    assert not missing, f"сборщик не напечатал сверки: {missing}"
    diff = [n for n in BUILT if (tmp_path / f"{n}.json").read_bytes() != (FACTS / f"{n}.json").read_bytes()]
    assert not diff, f"пересборка расходится с data/facts: {diff}"
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(f"{n}.json" for n in BUILT), "ручные файлы сборщик не пишет"


def test_builder_check_mode(tmp_path):
    assert run("--check").returncode == 0
    res = run("--check", "--out", str(tmp_path))          # пустой каталог: расхождение, файлы не пишутся
    assert res.returncode == 1 and "РАСХОЖДЕНИЕ" in res.stderr and not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", ("anchor", "calendar", "peers"))
def test_registry_sha256_matches_files(name):
    root = handoff()
    data = json.loads((FACTS / f"{name}.json").read_text(encoding="utf-8"))
    docs = data["documents"] if name == "anchor" else data["sources"]
    bad, checked = [], 0
    for d in docs:
        f = d.get("file")
        if not f:
            continue
        path = root / f
        if not path.is_file():
            bad.append(f"{d['key']}: нет файла {f}")
            continue
        checked += 1
        if hashlib.sha256(path.read_bytes()).hexdigest() != d["sha256"]:
            bad.append(f"{d['key']}: sha256 не совпал")
    assert not bad, "\n".join(bad)
    assert checked >= 0.9 * len(docs), f"{name}: у большинства документов нет файла в папке передачи"


def test_anchor_argument_reproduces_and_refuses_a_quarter_without_sheets(tmp_path):
    anchor = json.loads((FACTS / "anchor.json").read_text(encoding="utf-8"))["period"]
    res = run("--anchor", anchor, "--out", str(tmp_path / "same"))
    assert res.returncode == 0, res.stderr[-1500:]
    assert (tmp_path / "same" / "balance.json").read_bytes() == (FACTS / "balance.json").read_bytes()
    res = run("--anchor", "2031Q4", "--out", str(tmp_path / "far"))
    assert res.returncode == 1 and "нет листа якоря" in res.stderr and not (tmp_path / "far").exists()
    res = run("--anchor", "26Q2", "--out", str(tmp_path / "bad"))
    assert res.returncode == 1 and "якорь" in res.stderr


def test_report_from_the_build_equals_report_from_the_facts(tmp_path):
    a, b = tmp_path / "from-build.json", tmp_path / "from-facts.json"
    assert run("--out", str(tmp_path / "facts"), "--report", str(a)).returncode == 0
    assert run("--report", str(b), "--facts", str(FACTS)).returncode == 0
    ra, rb = json.loads(a.read_text(encoding="utf-8")), json.loads(b.read_text(encoding="utf-8"))
    ra.pop("source"), rb.pop("source")
    assert ra == rb


def test_key_rate_sheet_lives_in_the_stage_folder():
    """Ряд ключевой ставки по кварталам — лист этапа 1 (каталог рынка), а не файл исследования."""
    nb = json.loads((FACTS / "nii_books.json").read_text(encoding="utf-8"))
    assert "stage1/market/cbr_key_rate_quarterly.csv" in nb["key_avg_anchor_q"]["src"]
    assert (handoff() / "stage1" / "market" / "cbr_key_rate_quarterly.csv").is_file()
