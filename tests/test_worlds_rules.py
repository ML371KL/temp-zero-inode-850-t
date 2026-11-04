# -*- coding: utf-8 -*-
"""Правила книги для чисел, зависящих от миров (ops/tools/worlds_rules.py): на записи миров книги каждое правило даёт
шаблон — числа и числа правил в комментариях — бит в бит; файлы шагов (пути миров у листов) — функция записи.

ЗАЧЕМ. Команда приёма миров (ops/tools/adopt_worlds.py) пересчитывает только то, что названо в манифесте, и пишет
выход правил в шаблон. Правило, которое на своей записи не воспроизводит шаблон, при следующей версии миров запишет
не то число: красный тест здесь — до приёма, а не после."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "tools"))
import adopt_worlds as A  # noqa: E402
import worlds_rules as R  # noqa: E402

pytestmark = pytest.mark.tact

MANIFEST = A.load_manifest(ROOT)
RULES = [s for s in MANIFEST["steps"] if s["kind"] == "rule"]


@pytest.fixture(scope="module")
def ctx():
    state = A.read_state(ROOT)
    return A.RuleContext(tree=ROOT, entry=None, version=state["version"], manifest=MANIFEST)


@pytest.mark.parametrize("step", RULES, ids=[s["id"] for s in RULES])
def test_the_rule_gives_the_template_on_the_record_of_the_book(step, ctx):
    bad, n = [], 0
    for target in A.call_rule(ROOT, step, ctx):
        path = ROOT / target["file"]
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) if target.get("values") else None
        for k, want in (target.get("values") or {}).items():
            n += 1
            have = A.get(doc, A._path(k))
            if not (A.same(have, want) and type(have) is type(want)):
                bad.append((A._dotted(A._path(k)), have, want))
        bad += [("текст", p[0][:80], p[1][:80]) for p in target.get("replace") or [] if p[0] != p[1]]
    assert not bad, bad[:10]
    assert n or any(t.get("replace") for t in A.call_rule(ROOT, step, ctx)), step["id"]


def test_the_rules_cover_what_the_inventory_names(ctx):
    """Ключи, зависящие от миров (опись книги, раздел 2): спреды 9 книг (2026, 2027, 2028–LT у книг активов, LT
    оптового), фактический ключ оттока обоих сегментов, путь пакета, выведенные на ядре ключи — все пишут правила."""
    written = set()
    for step in RULES:
        for target in A.call_rule(ROOT, step, ctx):
            written |= {A._dotted(A._path(k)) for k in (target.get("values") or {})}
    book = yaml.safe_load((ROOT / MANIFEST["template"]).read_text(encoding="utf-8"))
    for b, spec in book["nii"]["books"].items():
        if isinstance(spec["spread"], dict):
            assert {f"nii.books.{b}.spread.{k}" for k in spec["spread"] if k != "LT_from"} <= written, b
    first = book["meta"]["first_period"]
    assert {f"volumes.funds_share_drift.{s}.{first}" for s in ("retail", "corporate")} <= written
    assert {f"noncore.result_real.{k}" for k in book["noncore"]["result_real"]} <= written
    for key in ("nii.sigma0_split", "nii.phi_split", "regimes.near_nim_shift.2026Q3", "capital.n20.t2.LT",
                "other.misc_net_real.LT", "fees.growth_vs_wages.2026", "opex.real_growth.LT", "meta.version"):
        assert key in written, key


def test_the_world_paths_of_the_sheets_are_the_record():
    record = json.loads((ROOT / "data/assumptions/worlds_source.json").read_bytes().decode("utf-8"))
    body = R.world_paths_csv(record)
    for area in ("nii", "pnl", "regimes"):
        base = ROOT / "data/assumptions/evidence" / area / "inputs"
        assert (base / "stage1/worlds/world_paths_quarterly.csv").read_bytes() == body, area
        row = next(f for f in json.loads((base / "SOURCES.json").read_text(encoding="utf-8"))["files"]
                   if f["path"] == "stage1/worlds/world_paths_quarterly.csv")
        assert row["sha256_input"] == hashlib.sha256(body).hexdigest() == row["sha256_full"], area


def test_the_version_rule_bumps_only_a_released_version(ctx, monkeypatch):
    """Номер версии: младший разряд + 1, только если книга с этим номером выпущена на другой записи миров."""
    book = yaml.safe_load((ROOT / MANIFEST["template"]).read_text(encoding="utf-8"))
    cur = str(book["meta"]["version"])
    monkeypatch.setattr(R, "released_record", lambda root, v: "0" * 64)
    head, _, minor = cur.rpartition(".")
    assert R.book_version(ctx)[0]["values"][("meta", "version")] == f"{head}.{int(minor) + 1}"
    monkeypatch.setattr(R, "released_record", lambda root, v: book["worlds"]["source"]["sha256"])
    assert R.book_version(ctx)[0]["values"][("meta", "version")] == cur
    monkeypatch.setattr(R, "released_record", lambda root, v: None)
    assert R.book_version(ctx)[0]["values"][("meta", "version")] == cur


def test_the_point_writer_keeps_the_text_and_writes_inside_lists(tmp_path):
    """Точечная запись команды: число внутри списка (ось) и ключ с точкой (подмена варианта) — без правки остального
    текста; замена текста правила не трогает данные."""
    p = tmp_path / "t.yaml"
    p.write_text('axes:\n  - {name: "a", low: {x.y: 0.1, z: 2}, high: 1.0}   # c 0,1\nk: 3  # к\n', encoding="utf-8")
    ch = A.set_values(p, {("axes", 0, "low", "x.y"): 0.25, ("k",): 4}, {("axes", 0, "low", "x.y"): 5})
    assert set(ch) == {"axes.0.low.x.y", "k"}
    assert p.read_text(encoding="utf-8") == 'axes:\n  - {name: "a", low: {x.y: 0.25, z: 2}, high: 1.0}   # c 0,1\nk: 4  # к\n'
    assert A.replace_text(p, [["# c 0,1", "# c 0,25"]]) == 1
    with pytest.raises(A.Stop):
        A.replace_text(p, [["k: 4", "k: 5"]])                   # данные — только значениями
