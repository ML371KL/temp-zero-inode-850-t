# -*- coding: utf-8 -*-
"""Доказательные листы книги воспроизводимы: скрипты области в копии листа (tmp_path) дают те же выходы, что лежат в
evidence/<область>/out/, и те же числа, что в книге (код выхода 0 — сверка с шаблоном без расхождений). Архивные тесты
(маркер archive, нужна папка передачи) сверяют малые входы с листами этапа 1 и выходы перенесённых листов — с выходами
этапа 1. Метка `tact` — у сверок без запуска листов (прогон листов ≈ 10 с идёт в CI и полном наборе): числа книги в
лежащих выходах, целостность малых входов по описи, отсутствие ответов брокерского API (файлом, таблицей или выпиской
его полей) во входах и выходах, готовность листа вывода на ядре."""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pytest

try:
    from tests import support_book as S
except ImportError:                      # прогон без pytest.ini (pythonpath = .) и без tests/__init__.py
    import support_book as S

AREAS = {                                 # область → скрипты по порядку (быстрые, без сети)
    "regulation": ("floors.py",),
    "capital": ("capital_calib.py", "capital_book.py"),
    "pnl": ("run_all.py", "pnl_book.py"),
    "nii": ("nii_book.py",),
    "regimes": ("regimes_book.py",),
    "market": ("beta_t.py", "dividends_book.py"),
    "governance": ("governance_book.py",),
}
# Выходы перенесённых листов этапа 1: область → (каталог листа в папке передачи, {выход листа: файл этапа 1})
STAGE1_OUTPUTS = {
    "capital": ("stage1/calib/capital", {"out.txt": "out.txt", "trial_out.txt": "trial_out.txt",
                                         "book_keys_capital_proposal.yaml": "book_keys_capital_proposal.yaml",
                                         "facts_capital_proposal.json": "facts_capital_proposal.json",
                                         "keys_table.csv": "out/keys_table.csv", "p1_n20_static.csv": "out/p1_n20_static.csv",
                                         "p2_density_anchor.csv": "out/p2_density_anchor.csv", "p3_floors.csv": "out/p3_floors.csv",
                                         "p4_buffer_readings.csv": "out/p4_buffer_readings.csv",
                                         "p5_trial_summary.csv": "out/p5_trial_summary.csv"}),
    "pnl": ("stage1/calib/pnl", {"op_basis_quarterly.csv": "op_basis_quarterly.csv",
                                 "book_keys_pnl_proposal.yaml": "book_keys_pnl_proposal.yaml",
                                 "bridge_values.json": "out/bridge_values.json", "misc_tax_nci.json": "out/misc_tax_nci.json",
                                 "noncore_center.json": "out/noncore_center.json", "opex_calibration.json": "out/opex_calibration.json",
                                 "dividend_payout.csv": "out/dividend_payout.csv", "s3_out.txt": "out/s3_out.txt"}),
    "market": ("stage1/market", {"beta_summary.json": "beta/out/beta_summary.json", "beta_results.csv": "beta/out/beta_results.csv",
                                 "beta_out.txt": "beta/out/beta_out.txt",
                                 "price_T_daily_split_adjusted.csv": "price_T_daily_split_adjusted.csv"}),
}
# Признаки сырого ответа брокерского API (конверт запроса, заголовки, поля): во входах листов их быть не должно.
# Строки собраны из частей: сам тест — не «сырой ответ» для общего теста гигиены репозитория
T_RAW_MARKERS = ("x-rate" + "limit", "headers_" + "kept", "instrument" + "Id", "dividend" + "Net",
                 "recommendation" + "Date", "target" + "Price", '"na' + 'no"')
T_ANSWER_WORDS = tuple(a + b for a, b in (("dividend", "Net"), ("record", "Date"), ("lastBuy", "Date"), ("payment", "Date"),
                                          ("declared", "Date"), ("Get", "Dividends"), ("Instruments", "Service"),
                                          ("tinvest_", "samples")))
T_TABLE_COLUMN = re.compile(r"^t_[a-z_]+$")
NUM = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
PATH_SHEET = S.EVIDENCE / "path" / "derive_on_engine.py"
PATH_RECORD = S.EVIDENCE / "path" / "out" / "derive_out.json"       # запись вывода на ядре
MARGINAL_SHEET = S.EVIDENCE / "path" / "marginal_loan.py"           # предельная доходность кредита против сегмента
MARGINAL_RECORD = S.EVIDENCE / "path" / "out" / "marginal_loan_out.json"
NEAR_SHEET = S.EVIDENCE / "path" / "near_margin.py"                 # два основания маржи квартала после якоря
NEAR_RECORD = S.EVIDENCE / "path" / "out" / "near_margin_out.json"


def copy_area(tmp: Path, area: str) -> Path:
    """Копия листа области с окружением (evlib, шаблон, запись миров, надстройка, запись вывода на ядре — её читают
    листы сверки с книгой) — тест не пишет в дерево."""
    dst_book = tmp / "assumptions"
    (dst_book / "evidence").mkdir(parents=True, exist_ok=True)
    for f in ("assumptions_template.yaml", "worlds_source.json", "worlds_bank.json"):
        shutil.copy2(S.BOOK_DIR / f, dst_book / f)
    shutil.copy2(S.EVIDENCE / "evlib.py", dst_book / "evidence" / "evlib.py")
    (dst_book / "evidence" / "path" / "out").mkdir(parents=True, exist_ok=True)
    shutil.copy2(PATH_RECORD, dst_book / "evidence" / "path" / "out" / PATH_RECORD.name)
    src_area = S.EVIDENCE / area

    def _ignore(d: str, names: list[str]) -> set[str]:     # выходы листа не копируются — их пишет прогон в копии
        skip = {n for n in names if n == "__pycache__"}
        if Path(d) == src_area:
            skip |= {n for n in names if n == "out"}
        return skip

    shutil.copytree(src_area, dst_book / "evidence" / area, ignore=_ignore)
    return dst_book / "evidence" / area


def _close_json(a, b, tol=1e-9) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_close_json(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close_json(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= tol * max(1.0, abs(a), abs(b))
    return a == b


def _close_text(a: str, b: str) -> bool:
    """Тексты равны; иначе — равны вне чисел, а числа расходятся не больше единицы последнего напечатанного знака
    (последний бит libm на другой платформе может сдвинуть округление печати)."""
    if a == b:
        return True
    if NUM.sub("#", a) != NUM.sub("#", b):
        return False
    for x, y in zip(NUM.findall(a), NUM.findall(b)):
        if x != y:
            dec = len(x.split(".")[1]) if "." in x and "e" not in x.lower() else 0
            if abs(float(x) - float(y)) > 10 ** -dec + 1e-12:
                return False
    return True


def same_output(new: Path, old: Path) -> bool:
    a, b = new.read_bytes().replace(b"\r\n", b"\n"), old.read_bytes().replace(b"\r\n", b"\n")
    if a == b:
        return True
    if new.suffix == ".json":
        return _close_json(json.loads(a), json.loads(b))
    return _close_text(a.decode("utf-8"), b.decode("utf-8"))


def _out(area: str, name: str) -> dict:
    return json.loads((S.EVIDENCE / area / "out" / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("area", list(AREAS))
def test_evidence_area_reproduces_its_outputs_and_the_book(area, tmp_path):
    work = copy_area(tmp_path, area)
    for script in AREAS[area]:
        done = S.run_script(work / script)
        assert done.returncode == 0, f"{area}/{script}:\n{done.stdout[-3000:]}\n{done.stderr[-3000:]}"
    committed = S.EVIDENCE / area / "out"
    names = sorted(p.name for p in committed.iterdir() if p.is_file())
    assert names, f"нет выходов листа {area}"
    assert sorted(p.name for p in (work / "out").iterdir() if p.is_file()) == names
    bad = [n for n in names if not same_output(work / "out" / n, committed / n)]
    assert bad == [], f"{area}: выходы не воспроизводятся: {bad}"


@pytest.mark.tact
def test_evidence_outputs_carry_the_book_numbers():
    """Выходы листов, лежащие в репозитории, согласованы с книгой (без запуска)."""
    book = S.template()
    fl = _out("regulation", "floors_out.json")
    assert fl["mismatches"] == [] and fl["book"]["strict"]["2030"]["floor20"] == 0.135 and fl["book"]["mid"]["2029"]["floor11"] == 0.095
    assert fl["glide_example"]["book"] == fl["glide_example"]["contract"]
    assert fl["book"]["schedule"]["2028"]["req20"] == pytest.approx(0.12 + book["capital"]["mgmt_buffer"]["n20_0"])
    cap = _out("capital", "capital_book_out.json")
    assert cap["book_mismatches"] == []
    assert cap["anchor"]["ded20"] == book["capital"]["n20"]["deductions_anchor"] == 197.99
    assert cap["anchor"]["ded11"] == book["capital"]["n11"]["deductions_anchor"]
    assert round(cap["anchor"]["n20_model"], 4) == 0.1293 and round(cap["anchor"]["n11_model"], 4) == 0.094
    assert cap["rwa_from_densities"]["model"] == cap["rwa_from_densities"]["implied"] == 5287.3
    assert cap["instruments_to_rwa"]["2026-06-30"] == 0.0233 and all(0.021 < v < 0.026 for v in cap["instruments_to_rwa"].values())
    assert cap["buffer"]["book"] == book["capital"]["mgmt_buffer"]["n20_0"] <= cap["buffer"]["third_reading_min"]
    assert cap["buffer"]["max_without_breach_2026Q3"] == {"schedule": 0.0243, "mid": 0.0193}
    pnl = _out("pnl", "pnl_book_out.json")
    assert pnl["book_mismatches"] == []
    assert pnl["anchor_quarter"]["ni_shareholders"] == pnl["anchor_quarter"]["issuer_op_np"] == 52.055
    assert pnl["sums"]["op_np_2025"] == 174.433 and pnl["payout"]["mean"] == 0.2586
    assert pnl["payout"]["book"] == book["dividends"]["policy"]["payout"]["LT"]
    assert pnl["nci_share"]["book"] == book["pnl"]["nci_share"] and abs(pnl["nci_share"]["h1_2026"] - 0.0245) < 1e-4
    assert pnl["bridges"]["nim_anchor_composition"] == pytest.approx(-0.0012, abs=5e-5)
    assert pnl["bridges"]["book_gates"] == book["checks"]["bridge_drift_pp"]
    nii = _out("nii", "nii_book_out.json")
    assert nii["book_mismatches"] == []
    assert nii["nii_identity"]["nii"] == nii["nii_identity"]["nii_fact"] == 157.6
    record = json.loads(PATH_RECORD.read_text(encoding="utf-8"))
    key = book["nii"]["nim_lt_target_mgmt"]                           # ключ цели ЧПМ — само суждение: стационарная маржа мира уровня
    assert nii["nim_target"]["key_book"] == key == record["level"]["key"] == round(nii["nim_target"]["rule"]["rule"], 3)
    assert nii["nim_target"]["world"] == book["nii"]["transmission"]["level_world"] == record["level"]["world"]
    assert abs(nii["nim_target"]["stationary_on_engine"] - key) <= 1e-9 and nii["nim_target"]["reference_level_on_engine"] != key
    whs = nii["wholesale_spread"]                                     # цена недостающего фондирования — правило по панели ставок окна
    assert whs["rule"] == whs["book"]["LT"] == round(whs["liquidity_lt_spread"] + whs["premium"], 5) and whs["premium"] == 0.0079
    assert whs["axis"][0] < whs["rule"] < whs["axis"][1] and len(whs["term_minus_liquid_by_quarter"]) == 7
    rule = nii["nim_target"]["rule"]                                  # числа правила маржи — из входов листа
    assert (round(rule["window_mean_mgmt"], 4), round(rule["loan_share_window"], 3), round(rule["loan_share_anchor"], 3)) == (0.1075, 0.645, 0.679)
    assert round(rule["composition_slope_pp_per_point"], 2) == 0.11 and rule["last_four"]["at_anchor_composition"] > rule["rule"]
    assert nii["funds_cost_to_key"]["book_max"] == book["checks"]["funds_cost_to_key"]["max"] == round(nii["funds_cost_to_key"]["max"], 3)
    assert nii["splits"]["phi_split"] == book["nii"]["phi_split"] <= nii["splits"]["phi_limit"]
    assert nii["transmission"]["target"] == book["nii"]["transmission"]["target"]
    assert nii["anchor"]["loans"] == 3813.1 and nii["anchor"]["funds"] == 4298.5
    assert nii["floor_headroom_min"]["gap"] >= 0
    assert cap["instrument_spread"]["to_wholesale"] == record["cost"]["spread"]["to_wholesale"] > cap["instrument_spread"]["margin_to_key"] > 0
    assert record["cost"]["spread"]["wholesale_lt_spread"] == whs["rule"]
    assert 0.4 < cap["instrument_spread"]["external_share"]["share"] == record["cost"]["external"]["share"] < 0.5
    assert pnl["links"]["book"] == {"opex.volume_link": book["opex"]["volume_link"], "fees.volume_link": book["fees"]["volume_link"]}
    assert pnl["misc"]["level"] == 21 and pnl["misc"]["book_lt"] == book["other"]["misc_net_real"]["LT"] < pnl["misc"]["level"]
    reg = _out("regimes", "regimes_out.json")
    assert reg["book_mismatches"] == [] and reg["cor_weighted"]["LT"] == 0.05605 and reg["cor_weighted"]["avg_2027_2029"] == 0.05775
    assert abs(reg["nim_shift_weighted"]["LT"]) <= 0.0003 + 1e-12 and reg["kappa"]["book"] == book["credit"]["kappa"]
    div = _out("market", "dividends_book_out.json")
    assert div["book_mismatches"] == [] and div["shares"]["exdate_jump_for_declared"] == -4.467
    assert div["dps_2025"] == 14.9 and div["dps_guidance_threshold"] == 17.88
    assert all(v["share"] <= book["dividends"]["policy"]["cap"] for v in div["cap_check"].values())
    beta = _out("market", "beta_summary.json")
    assert beta["beta_E_center_book"] == book["valuation"]["beta_e"] == round(beta["beta_E_center"], 2)
    ax = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["paths"] == ["valuation.beta_e"])
    assert ax["low"] <= beta["ci95"][0] + 0.01 and beta["ci95"][1] <= ax["high"]
    gov = _out("governance", "governance_out.json")
    assert gov["book_mismatches"] == [] and gov["total"] == book["valuation"]["governance"]["discount"] == 0.0
    assert all(ch["value_book"] == ch["value_sheet"] == 0.0 for ch in gov["channels"].values())


@pytest.mark.tact
def test_small_inputs_match_their_inventory():
    """Малые входы каждой области — те, что названы описью `inputs/SOURCES.json`: хэши совпадают, лишних файлов нет."""
    for area in AREAS:
        base = S.EVIDENCE / area / "inputs"
        src = json.loads((base / "SOURCES.json").read_text(encoding="utf-8"))
        assert src["area"] == area and src["root"] == "$BANK_HANDOFF_DIR"
        listed = {f["path"]: f for f in src["files"]}
        on_disk = {p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()} - {"SOURCES.json"}
        assert on_disk == set(listed), (area, sorted(on_disk ^ set(listed)))
        for rel, f in listed.items():
            assert S.sha256_bytes((base / rel).read_bytes()) == f["sha256_input"], (area, rel)
            assert len(f["sha256_full"]) == 64 and 0 < f["rows_kept"] <= f["rows_total"], (area, rel)


@pytest.mark.tact
def test_evidence_carries_no_broker_api_answers():
    """Во входах, выходах, текстах и коде листов нет ответов брокерского API: ни файла ответа, ни имён его полей и
    методов, ни таблицы с колонками-полями ответа. Дивиденды — лист решений собраний с документом эмитента и новостью."""
    bad = []
    for p in S.EVIDENCE.rglob("*"):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = p.relative_to(S.EVIDENCE).as_posix()
        bad += [(rel, w) for w in T_RAW_MARKERS + T_ANSWER_WORDS if w in text]
        if p.suffix == ".csv":
            head = text.splitlines()[0].lstrip("﻿").split(",") if text else []
            bad += [(rel, c) for c in head if T_TABLE_COLUMN.match(c.strip())]
    assert bad == []
    rows = (S.EVIDENCE / "market/inputs/stage1/market/dividends_public.csv").read_text(encoding="utf-8").splitlines()
    head = rows[0].split(",")
    assert {"issuer_doc_url", "issuer_doc_sha256", "news_url", "news_published", "dps", "dps_pre_split"} <= set(head)
    assert len(rows) == 9                                             # восемь решений: 9 месяцев 2024 — 2-й квартал 2026


@pytest.mark.tact
def test_the_path_sheet_answers_for_the_core_it_meets():
    """Лист вывода на ядре: пока ядро не исполняет ветви книги — код 2 и слова «нужна волна»; на готовом ядре шаги
    моста и уровня маржи печатают ключ книги — суждение, которое лист читает и не меняет."""
    done = S.run_script(PATH_SHEET, "--steps", "bridge,level", "--no-write")
    assert done.returncode in (0, 2), done.stdout + done.stderr
    if done.returncode == 2:
        assert "нужна волна" in done.stdout and "ядр" in done.stdout
        return
    key = re.search(r"nii\.nim_lt_target_mgmt: ([0-9.]+)", done.stdout)
    assert key and float(key.group(1)) == pytest.approx(S.template()["nii"]["nim_lt_target_mgmt"], abs=1e-4), done.stdout


def test_the_path_sheet_reproduces_the_frozen_numbers(tmp_path):
    """Полный вывод на ядре повторяет замороженные числа шаблона: доли σ0 и φ, ближний сдвиг ЧПМ, траекторию
    инструментов капитала и их стоимость в «прочем», спред услуг, корни расходов, концы осей (уровень маржи — само
    суждение, доля φ, связка гибкости), поля окна фактов и уровень «нужды баланса» премии средств клиентов. Запуск с чисел самой книги — ещё один круг связанных шагов: числа остаются в пределах точности
    записи, вывод сходится. Пока ядро не готово (код 2) — пропуск с названной причиной."""
    out = tmp_path / "derive_out.json"
    done = S.run_script(PATH_SHEET, "--out", str(out))
    if done.returncode == 2:
        pytest.skip("ядро ещё не исполняет ветви книги второй формы банка — лист вывода ждёт")
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    book, got = S.template(), json.loads(out.read_text(encoding="utf-8"))
    keys = got["keys"]
    assert got["convergence"]["converged"] and got["frozen_check"]["nim_stationary_ok"] and got["frozen_check"]["cir_lt_ok"]
    assert got["need"]["level"] == pytest.approx(json.loads(PATH_RECORD.read_text(encoding="utf-8"))["need"]["level"], abs=5e-4)
    assert "nii.nim_lt_target_mgmt" not in keys and got["level"]["key"] == book["nii"]["nim_lt_target_mgmt"]
    assert got["transmission"]["level_world_fixed"] is True
    assert (keys["nii.sigma0_split"], keys["nii.phi_split"]) == (book["nii"]["sigma0_split"], book["nii"]["phi_split"])
    t2, t2_book = keys["capital.n20.t2"], book["capital"]["n20"]["t2"]
    assert set(t2) == set(t2_book) and all(t2[k] == pytest.approx(t2_book[k], rel=0.01) for k in t2)
    near, near_book = keys["regimes.near_nim_shift"], book["regimes"]["near_nim_shift"]
    assert set(near) == set(near_book) and all(near[k] == pytest.approx(near_book[k], abs=2e-4) for k in near)
    misc, misc_book = keys["other.misc_net_real"], book["other"]["misc_net_real"]
    assert set(misc) == set(misc_book) and all(misc[k] == pytest.approx(misc_book[k], abs=0.05) for k in misc)
    for path in ("fees.growth_vs_wages", "opex.real_growth"):
        have, want = keys[path], S.get(book, path)
        assert set(have) == set(want) and all(have[k] == pytest.approx(want[k], abs=1e-3) for k in want), path
    axes = {a["paths"][0]: a for a in book["valuation"]["uncertainty"]["axes"]}
    margin = got["ends"]["margin_axis"]
    assert (margin["low"], margin["high"]) == (axes["nii.nim_lt_target_mgmt"]["low"], axes["nii.nim_lt_target_mgmt"]["high"])
    assert got["splits"]["axis_phi"] == [axes["nii.phi_split"]["low"], axes["nii.phi_split"]["high"]]
    window = book["checks"]["window_backtest"]
    assert got["ends"]["window"]["loans_share"]["window"] == window["loans_share"] and got["ends"]["window"]["nim"]["max"] == window["nim"][1]
    bundle = axes["opex.volume_link"]
    for end in ("low", "high"):
        assert set(got["ends"]["bundle"][end]) == set(bundle[end])
        assert all(got["ends"]["bundle"][end][p] == pytest.approx(bundle[end][p], abs=1e-3) for p in bundle[end]), end


def test_the_marginal_loan_sheet_reproduces_its_record(tmp_path):
    """Лист предельной доходности кредита повторяет свою запись на книге и ядре дерева; на записи стоят слова книги и
    объяснения гейта знака объёмных эффектов: на якоре рубль розничного кредита на базисе сегмента зарабатывает на
    капитал столько же, сколько сегмент отчётности (в пределах пункта от его нижней оценки); после фазы роста
    предельный кредит окупает капитал в мирах, где гейт печатает положительную цену, и не окупает в остальных."""
    out = tmp_path / "marginal_loan_out.json"
    done = S.run_script(MARGINAL_SHEET, "--out", str(out))
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    got, kept = json.loads(out.read_text(encoding="utf-8")), json.loads(MARGINAL_RECORD.read_text(encoding="utf-8"))
    assert _close_json(got, kept, tol=1e-6)
    assert _close_text(out.with_suffix(".txt").read_text(encoding="utf-8"), MARGINAL_RECORD.with_suffix(".txt").read_text(encoding="utf-8"))
    fact, check = got["segment"], got["anchor_check"]
    assert fact["after_tax_on_end"] < fact["after_tax_on_average"]
    assert abs(check["model_min"] - fact["after_tax_on_end"]) < 0.01 and check["model_max"] < fact["after_tax_on_average"]
    signs = json.loads((S.BOOK_DIR / "results.json").read_text(encoding="utf-8"))["sign_test"]["d_world"]
    for world, rows in got["marginal"]["all_loans"].items():
        late = [r for r in rows if r["funded_by"] == "wholesale"][-2:]       # конец фазы роста и последний год сетки
        assert len(late) == 2
        assert all((r["return_no_capital_credit"] > r["cost_of_equity"]) == (signs[world] > 0) for r in late), world
    src = {(r["doc"], r["sha256"]) for r in got["segment_sources"]}
    assert len(src) == 1 and all(len(h) == 64 for _, h in src)


@pytest.mark.docs
def test_the_near_margin_sheet_reproduces_its_record_and_the_words_of_the_book(tmp_path):
    """Лист двух оснований маржи квартала после якоря повторяет свою запись на посевах и фактах дерева; на записи
    стоят слова суждения о ближнем пути (A-C4b): оба индекса в прошлых кварталах завышали упр. маржу, оценка «к
    процентным активам» выше оценки «к портфелю», а путь книги стоит между ними — не выше оценки с поправкой «к
    процентным активам» и у верхнего края оценки с поправкой «к портфелю». Числа записи напечатаны в тексте книги."""
    out = tmp_path / "near_margin_out.json"
    done = S.run_script(NEAR_SHEET, "--out", str(out))
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    got, kept = json.loads(out.read_text(encoding="utf-8")), json.loads(NEAR_RECORD.read_text(encoding="utf-8"))
    assert _close_json(got, kept, tol=1e-9)
    assert out.with_suffix(".txt").read_text(encoding="utf-8") == NEAR_RECORD.with_suffix(".txt").read_text(encoding="utf-8")
    est, err, fixed = got["estimate"], got["errors"]["full"], got["estimate_corrected"]["full"]
    assert len(got["history"]) == 4 and est["to_loans"] < est["to_assets"]
    assert all(err[k]["min"] > 0 for k in est) and err["to_loans"]["mean"] < err["to_assets"]["mean"]
    path = json.loads(PATH_RECORD.read_text(encoding="utf-8"))["frozen_check"]["near_anchor_year"][0]
    assert fixed["to_assets"]["low"] < path < fixed["to_assets"]["high"]
    assert est["to_loans"] - err["to_loans"]["max"] < path and abs(path - fixed["to_loans"]["high"]) < 0.0005
    raw = (S.BOOK_DIR / "ASSUMPTIONS-BOOK.md").read_text(encoding="utf-8")
    text = " ".join(re.sub(r"<!--.*?-->", "", raw).split())          # без меток чисел и переносов строк
    pct = lambda v, n=2: f"{100 * v:.{n}f}".replace(".", ",")  # noqa: E731
    for words in (f"от {pct(got['anchor_nim'])} % — {pct(est['to_loans'])} %", f"оценка — {pct(est['to_assets'])} %",
                  f"с {pct(got['ras_margin_on_assets']['anchor'])} до {pct(got['ras_margin_on_assets']['known_months'])} %",
                  f"на {pct(err['to_loans']['mean'])} п.п. (от {pct(err['to_loans']['min'])} до {pct(err['to_loans']['max'])})",
                  f"на {pct(err['to_assets']['mean'])} п.п. (от {pct(err['to_assets']['min'])} до {pct(err['to_assets']['max'])})",
                  "evidence/path/near_margin.py"):
        assert words in text, words


@pytest.mark.archive
def test_small_inputs_are_the_stage1_sheets():
    """Малые входы листов — выписки листов этапа 1 из папки передачи (`extract_inputs.py --check`)."""
    if not os.environ.get("BANK_HANDOFF_DIR"):
        pytest.skip("нет BANK_HANDOFF_DIR")
    done = S.run_script(S.EVIDENCE / "extract_inputs.py", "--check")
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.archive
@pytest.mark.parametrize("area", list(STAGE1_OUTPUTS))
def test_ported_sheets_reproduce_the_stage1_outputs(area):
    """Перенесённые листы этапа 1 на малых входах дают те же выходы, что листы этапа 1 на полных."""
    root = os.environ.get("BANK_HANDOFF_DIR")
    if not root:
        pytest.skip("нет BANK_HANDOFF_DIR")
    leaf, files = STAGE1_OUTPUTS[area]
    bad = [name for name, rel in files.items()
           if not same_output(S.EVIDENCE / area / "out" / name, Path(root, *leaf.split("/"), *rel.split("/")))]
    assert bad == [], f"{area}: выходы расходятся с этапом 1: {bad}"
