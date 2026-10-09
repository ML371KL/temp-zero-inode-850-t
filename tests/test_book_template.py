# -*- coding: utf-8 -*-
"""Книга Т-Технологий: шаблон разбирается, сборка воспроизводит машинную книгу, все пути прил. A MODEL и договора
ключей есть и не null там, где ядро их читает, схема ядра принимает форму книги; вероятности, оси полосы и строки
обратного расчёта согласованы со значениями книги; решения ведущего № 1–7 и правила второй формы банка (квартальный
календарь дивидендов, рост по капиталу, премии траекториями, оси-связки, числа «выводится на ядре») — числами книги.
Быстрые — метка `tact` (такт сервера); тесты `docs` такт не гоняет. Суждения, которые проверяются прогоном ядра, —
`tests/test_book_core.py`."""
from __future__ import annotations

import json
import re
from string import Formatter

import pytest
import yaml

try:
    from tests import support_book as S
except ImportError:                      # прогон без pytest.ini (pythonpath = .) и без tests/__init__.py
    import support_book as S

pytestmark = pytest.mark.tact

MARKS = ("  #{{WORLDS}}", "#{{WORLDS_BANK}}", "#{{OVERLAY_SHA256}}")
VERSION = "1.0"
RESULTS = S.BOOK_DIR / "results.json"
# Оси, которые из полосы не выводятся никогда (MODEL §10): односторонние рисковые — по путям ключей
NEVER_OFF_BAND = ("tax.statutory", "tax.one_off.prob", "regimes.crisis.one_off_loss.amount")
CREDIT_BOOKS = ("cards", "cash_loans", "auto", "mortgage", "sme_loans", "corp_loans")
BOOKS = CREDIT_BOOKS + ("securities", "liquidity", "retail_current", "retail_term", "corp_funds", "wholesale")
# Ключи годового календаря дивидендов: в квартальном режиме не читаются и равны null (MODEL §5.7)
CALENDAR_ANNUAL = tuple(f"dividends.calendar.{k}" for k in ("agm_quarter", "reg_deduction_quarter", "payment_quarter", "checkpoints"))
# Ключи второй формы банка (договор ключей этапа 1, раздел 1): книга Т несёт их явно. «*» — любой хвост пути.
FORM_PATHS = (
    "meta.schema", "meta.labels.*", "nii.books.<b>.name", "valuation.shares_basis", "valuation.share_count_adj",
    "dividends.policy.history_test", "dividends.policy.cap", "dividends.policy.base_window_quarters",
    "dividends.calendar.frequency", "dividends.calendar.decision_lag_quarters.*",
    "dividends.calendar.reg_deduction_lag_quarters", "dividends.calendar.payment_lag_quarters",
    "dividends.calendar.checkpoints_ahead", "fees.volume_link", "other.insurance_volume_link", "opex.volume_link",
    "volumes.link_base", "volumes.loan_share_drift.{corporate,mortgage,retail_other}.*",
    "volumes.funds_share_drift.{retail,corporate}.*", "volumes.other_assets_fixed",
    "capital.rwa.density.other_assets_fixed", "regimes.crisis.rwa_density_mult.*",
    "capital.growth_constraint.{enabled,order,min_growth_scale,lookahead_quarters,glide_pp_per_quarter,catch_up_rate,tol}",
    "checks.guidance_items", "checks.growth_cut.max_cut_share", "checks.step_dividend.max_lam_drop",
    "checks.cir_lt.{target,tolerance,from_year}", "checks.wholesale_share", "checks.mix_ratio_tolerance",
    "checks.manual_overdue_days.capital_form",
    "valuation.sensitivities.buffer_pp",
)
# Подписи книги и поля подстановки каждой (договор ключей, раздел 1.3); у прочих подписей полей нет
LABEL_FIELDS = {
    "capital.anchor_src": {"date"}, "capital.anchor_src_estimated": {"date"}, "dividends.ladder_condition": {"threshold"},
    "dividends.pay_event": {"year", "period", "label"}, "register.flag_detail": {"gaps"},
    "register.gap_item": {"year", "period", "label", "decision_quarter", "end"}, "register.alert": {"detail"},
    "register.recommended_item": {"year", "period", "label", "dps"}, "register.rejected_item": {"year", "period", "label", "reason"},
    "register.overdue_item": {"year", "period", "label", "date"}, "register.record_words": {"year", "period", "label"},
    "register.collector_alarm": {"year", "period", "label", "end", "detail"},
    "gates.nim_anchor": {"value", "reported"},
    "periods.1": {"year"}, "periods.2": {"year"}, "periods.3": {"year"}, "periods.4": {"year"},
}
LABEL_GROUPS = {
    "capital": {"n20", "n11", "n11_observed", "n1_0", "n1_2", "n20_short", "n11_short", "anchor_src", "anchor_src_estimated",
                "observed_source"},
    "capital_bridge": {"dividend_accrual", "profit", "oci_other", "rwa_growth", "deductions", "other"},
    "dividends": {"ladder_condition", "ladder_residual_title", "ladder_residual_condition", "pay_event"},
    "register": {"flag_title", "flag_detail", "gap_item", "alert", "recommended_item", "rejected_item", "note", "overdue_item",
                 "record_words", "collector_alarm"},
    "flags": {"ras_mismatch"}, "gates": {"nim_anchor"}, "nowcast": {"targets", "ops_note", "absent"},
    "nextreport": {"fact_note", "guidance_note"},
    "terms": {"lt_level", "profit_short", "cir", "roe_lt", "stake"}, "corridors": {"guidance_gap"}, "periods": {"1", "2", "3", "4"},
    "basis": {"profit", "roe", "roe_issuer", "divisor", "dividend_issued", "dividend_outstanding"}, "peers": {"subject_basis"},
    "control": {"lines", "books"}, "rule_price": {"unconstrained"},
}
CONTROL_LINES = {"nii", "llp", "fvc", "fees", "opex", "misc", "noncore", "pbt", "ni_sh", "ci", "div", "bv", "rwa", "n20", "n11"}
# Ключи, значение которых зависит от пути баланса клетки или задано правилом на выведенных числах: с пометкой в шаблоне
DERIVED_ON_ENGINE = ("sigma0_split:", "phi_split:", "near_nim_shift:", "growth_vs_wages:", "real_growth: {",
                     "misc_net_real:", "t2:")
WINDOW = ("2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2")   # окно фактов: кварталы после покупки Росбанка
TERM_OVER_LIQUID = 0.0079                                     # срочные вклады окна дороже ликвидных активов (лист evidence/nii)
BUNDLE_LINKS = ("opex.volume_link", "fees.volume_link")       # главные числа оси-связки гибкости; прочие пути — спутники
PREMIUM_YEARS = ("2027", "2028", "2029", "2030", "2031")      # годы премии роста средств клиентов на оси-связке
PREMIUM_ENDS = {"2027": 0.05, "2028": 0.05, "2029": 0.04, "2030": 0.03, "2031": 0.02}
ANCHOR_YEAR_QUARTERS = ("2026Q3", "2026Q4")                   # прогнозные кварталы года якоря: ключи премии средств клиентов по факту


@pytest.fixture(scope="module")
def book() -> dict:
    return S.built_book()


@pytest.fixture(scope="module")
def template_text() -> str:
    return (S.BOOK_DIR / "assumptions_template.yaml").read_text(encoding="utf-8")


def switched_off(book: dict) -> set[str]:
    """Ключи, которые ядро не читает: под выключателями и ключи неактивного режима календаря дивидендов."""
    off = S.switched_off(book)
    if book["dividends"]["calendar"].get("frequency") == "quarterly":
        off.update(CALENDAR_ANNUAL)
    return off


def expand(token: str, book: dict) -> list[str]:
    """Шаблон пути → конкретные пути книги; незнакомая подстановка в угловых скобках — пусто (не путь книги)."""
    out = S._expand(token.replace(", ", ","), book)
    return [p for p in out if "<" not in p]


def applies(path: str, book: dict) -> bool:
    """Условные ключи книг ЧПД (пассивы, активы, кредиты, балансирующие); ключ доли кредитов по справедливой
    стоимости необязателен — у книг Т его нет."""
    if re.match(r"nii\.books\.[^.]+\.fv_share$", path):
        return S.has(book, path)
    return S._applies(path, book)


def form_paths(book: dict) -> list[str]:
    out = []
    for tok in FORM_PATHS:
        out += expand(tok, book)
    return out


# ------------------------------------------------------------------ шаблон и сборка
def test_the_template_parses_and_carries_one_of_each_build_mark(template_text):
    data = yaml.safe_load(template_text)
    assert data["meta"]["version"] == VERSION and data["meta"]["schema"] == "t-v1"
    lines = template_text.splitlines()
    assert sum(1 for ln in lines if ln == "  #{{WORLDS}}") == 1
    assert sum(1 for ln in lines if ln == "#{{WORLDS_BANK}}") == 1
    assert sum(1 for ln in lines if "#{{OVERLAY_SHA256}}" in ln) == 1
    assert set(data["worlds"]) == {"source", "build", "quarter_rule", "ids", "overlay"}   # миры вписывает сборка
    assert "worlds_bank" not in data
    assert not any("@@" in ln for ln in lines)


def test_the_build_reproduces_the_committed_machine_book():
    y, j, _ = S.build_module().render()
    assert (S.BOOK_DIR / "assumptions.yaml").read_text(encoding="utf-8") == y
    assert (S.BOOK_DIR / "assumptions.json").read_text(encoding="utf-8") == j


def test_the_build_is_deterministic_and_json_equals_yaml():
    m = S.build_module()
    y1, j1, b1 = m.render()
    y2, j2, b2 = m.render()
    assert (y1, j1) == (y2, j2)
    assert json.loads(j1) == yaml.safe_load(y1) == b1
    assert not any(ln.rstrip() in MARKS for ln in y1.splitlines())


def test_the_build_check_mode_exits_zero():
    done = S.run_script(S.BOOK_DIR / "build_assumptions.py", "--check")
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_core_schema_accepts_the_form_of_the_book(book):
    """Схема ядра принимает форму книги. Пока ядро собирается, ветвь, которую схема уже знает, а ядро ещё не исполняет,
    отказом не считается (`pending_ok`); незнакомый ключ, неверный тип и нарушение взаимных ограничений — отказ всегда.
    Когда ядро исполняет все ветви, проверка становится полной."""
    from model import book_schema

    try:
        book_schema.validate(book, pending_ok=True)
    except TypeError:                                    # ядро собрано: проверки одной формы больше нет
        book_schema.validate(book)


# ------------------------------------------------------------------ полнота ключей
def test_every_key_of_the_second_bank_form_is_in_the_book_and_not_null(book):
    """Ключи договора (квартальный календарь, делитель, связь с объёмом, премии траекториями, рост по капиталу, новые
    гейты, подписи) стоят в книге явно и не null: ось полосы и подмена пути требуют существующего ключа."""
    paths = form_paths(book)
    assert len(paths) > 45
    missing = [p for p in paths if "*" not in p and not S.has(book, p)]
    nulls = [p for p in paths if "*" not in p and S.has(book, p) and S.get(book, p) is None]
    assert missing == [] and nulls == []
    for p in (p for p in paths if "*" in p):
        assert S.get(book, p.split(".*")[0]), p


@pytest.mark.docs
def test_every_app_a_path_is_in_the_book_and_not_null(book):
    paths = [p for tok in re.findall(r"`([^`]+)`", S.app_a_text())
             for p in _app_a_token(tok, book)]
    paths = list(dict.fromkeys(paths))
    assert len(paths) > 300
    off = switched_off(book)
    missing = [p for p in paths if "*" not in p and not S.has(book, p)]
    nulls = [p for p in paths if "*" not in p and S.has(book, p) and S.get(book, p) is None and p not in off]
    assert missing == [] and nulls == []
    for p in (p for p in paths if "*" in p):                      # словарь по годам — не пуст
        assert S.get(book, p.split(".*")[0]) is not None


def _app_a_token(tok: str, book: dict) -> list[str]:
    tok = tok.strip()
    if " " in tok.replace(", ", ",") or "." not in tok or tok.split(".")[0] not in S.TOP or "/" in tok:
        return []
    return [p for p in expand(tok, book) if applies(p, book)]


@pytest.mark.docs
def test_every_leaf_of_the_book_is_named_by_app_a_or_by_the_form(book):
    """Каждый лист книги назван приложением A методики либо перечнем ключей второй формы банка."""
    paths = [p for tok in re.findall(r"`([^`]+)`", S.app_a_text()) for p in _app_a_token(tok, book)] + form_paths(book)
    exact = [p for p in paths if "*" not in p]
    star = [p.split("*")[0] for p in paths if "*" in p]
    unnamed = [path for path, _ in S.leaves(book)
               if not any(path.split("[")[0] == p or path.split("[")[0].startswith(p + ".") for p in exact)
               and not any(path.startswith(s) for s in star)]
    assert unnamed == []


def test_nulls_only_under_switched_off_keys(book):
    off = switched_off(book)
    nulls = {p for p, v in S.leaves(book) if v is None}
    assert nulls == off, sorted(nulls ^ off)
    for sw in S.SWITCHES:
        assert S.get(book, sw) is False
    assert book["capital"]["recapitalization"]["enabled"] is False
    assert book["dividends"]["buyback"]["enabled"] is False
    assert book["capital"]["growth_constraint"]["enabled"] is True


# ------------------------------------------------------------------ согласованность значений
def test_probability_tables_sum_to_one(book):
    j = book["joint"]
    tables = [j["world_prob"], j["world_prob_market_implied"], j["regime_prob"], *j["reg_prob_given_regime"].values()]
    for axis in book["valuation"]["uncertainty"]["axes"]:
        if axis["kind"] == "dict":
            tables += [axis["low"], axis["high"]]
    for t in tables:
        assert abs(sum(t.values()) - 1) < 1e-4, t
    for t in tables[:3] + list(j["reg_prob_given_regime"].values()):
        assert abs(sum(t.values()) - 1) < 1e-12, t
    assert set(j["regime_prob"]) == set(book["regimes"]["ids"])
    assert set(j["world_prob"]) == set(book["worlds"]["ids"])
    assert all(set(t) == set(book["capital"]["reg_scenarios"]["ids"]) for t in j["reg_prob_given_regime"].values())


def test_governance_discount_is_the_sum_of_channels(book):
    g = book["valuation"]["governance"]
    assert abs(g["discount"] - sum(c["sign"] * c["value"] for c in g["components"])) < 1e-12
    assert [c["id"] for c in g["components"]] == ["related_party_deals", "motivation", "depositary_block",
                                                 "liquidity_listing", "holding_layer"]
    assert g["discount"] == 0.0 and book["bridge"]["governance_applies"] is False


def test_uncertainty_axes_hold_the_book_value_inside_their_range(book):
    unc = book["valuation"]["uncertainty"]
    assert len(unc["axes"]) == 43 and unc["off_band_axes"] == []
    assert sum(1 for a in unc["axes"] if a["kind"] == "dict") == 2 and sum(1 for a in unc["axes"] if a["kind"] == "bundle") == 2
    names = [a["name"] for a in unc["axes"]]
    assert len(set(names)) == len(names)
    for a in unc["axes"] + unc["off_band_axes"]:
        assert a["dist"] == "triangular" and a["kind"] in ("value", "shift", "dict", "bundle")
        for p in a["paths"]:
            assert S.has(book, p) and S.get(book, p) is not None, (a["name"], p)
        if a["kind"] == "bundle":                                      # концы — словари ровно по путям; связи лежат между концами
            assert set(a["low"]) == set(a["high"]) == set(a["paths"]) and len(set(a["paths"])) == len(a["paths"]), a["name"]
            for p in (BUNDLE_LINKS if a["paths"][0] in BUNDLE_LINKS else a["paths"]):
                assert a["low"][p] < S.get(book, p) < a["high"][p], (a["name"], p)
        if a["kind"] == "value":
            for p in a["paths"]:
                assert a["low"] <= S.get(book, p) <= a["high"], (a["name"], p)
        elif a["kind"] == "shift":
            assert a["low"] <= 0 <= a["high"], a["name"]


def test_reverse_dcf_axes_search_covers_range(book):
    rev = book["valuation"]["reverse_dcf"]
    assert len(rev["axes"]) == 13 and rev["axis_follow"] == "both"        # ось идёт за проверяемым значением обоими концами
    assert rev["edge_refine_rub"] == book["valuation"]["headline"]["print_step"]   # решение у края диапазона — на полной полосе
    for a in rev["axes"]:
        assert a["kind"] in ("value", "shift", "mix")
        for p in a["paths"]:
            assert S.has(book, p), (a["name"], p)
        assert a["search"][0] <= a["range"][0] <= a["range"][1] <= a["search"][1], a["name"]
    names = {a["name"] for a in rev["axes"]}
    assert any("Выплата" in n for n in names) and any("Запас" in n for n in names) and any("при рыночных ставках" in n for n in names)
    assert not any("мире H" in n for n in names)                    # строка уровня маржи — о самом суждении, не об уровне мира-опоры
    mix = next(a for a in rev["axes"] if a["kind"] == "mix")
    assert set(mix["toward"]) == set(book["capital"]["reg_scenarios"]["ids"]) and mix["toward"]["strict"] == 1.0
    band = {tuple(a["paths"]): a for a in book["valuation"]["uncertainty"]["axes"]}
    for a in rev["axes"]:                                             # диапазон книги строки = ось полосы тех же путей
        if tuple(a["paths"]) in band and a["kind"] != "mix" and band[tuple(a["paths"])]["kind"] != "bundle":   # связка строкой не бывает
            assert a["range"] == [band[tuple(a["paths"])]["low"], band[tuple(a["paths"])]["high"]], a["name"]
    assert rev["bank_rows"] == ["implied_roe_through_cycle", "implied_cost_of_equity", "market_cap_minus_bv",
                                "value_without_excess_growth", "book_value_per_share", "excess_return_years"]


def test_issuer_trajectories_end_on_lt_levels_by_the_last_year(book):
    last_year = int(book["meta"]["last_period"][:4])
    for path, v in S.leaves({k: book[k] for k in book if k not in ("worlds", "worlds_bank")}):
        if path.endswith(".LT_from"):
            assert int(v) <= last_year, path
        m = re.search(r"\.(\d{4})(Q\d|H\d)$", path)
        if m:
            assert int(m.group(1)) != last_year, path                 # ключ квартала/полугодия в году last_period запрещён


def test_year_keys_are_the_means_of_their_quarter_keys(book):
    """Ключ года при четырёх квартальных ключах — их среднее (MODEL §0.4): иначе ядро отказывает."""
    def walk(node, path=""):
        if isinstance(node, dict):
            quarters: dict[str, list[float]] = {}
            for k, v in node.items():
                m = re.fullmatch(r"(\d{4})Q[1-4]", str(k))
                if m and isinstance(v, (int, float)):
                    quarters.setdefault(m.group(1), []).append(float(v))
            for y, vals in quarters.items():
                if len(vals) == 4 and y in node:
                    assert abs(sum(vals) / 4 - node[y]) < 1e-9, (path, y)
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else str(k))
    walk({k: book[k] for k in book if k not in ("worlds", "worlds_bank")})


def test_meta_company_and_prices(book):
    meta = book["meta"]
    c = meta["company"]
    assert c == {"name": "Т-Технологии", "tickers": ["T"], "main_ticker": "T", "share_classes": {"T": "ordinary"},
                 "cbr_regnum": 2673, "fiscal_year_end": "12-31"}
    assert set(meta["market_price"]) == set(c["tickers"]) and meta["market_price"]["T"] > 0
    for k in ("date", "facts_date", "valuation_date", "curve_as_of"):
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta[k])
    assert meta["valuation_date"] == meta["date"] >= meta["facts_date"]
    assert (meta["facts_date"], meta["anchor_period"], meta["first_period"], meta["last_period"]) == \
        ("2026-06-30", "2026Q2", "2026Q3", "2036Q4")
    assert book["valuation"]["uncertainty"]["seed"] == int(meta["date"].replace("-", ""))    # зерно — дата книги
    assert "операционная прибыль акционеров" in meta["basis"]


# ------------------------------------------------------------------ решения ведущего числами книги
def test_lead_decisions_1_and_2_are_in_the_book(book):
    """Решения ведущего № 1 и № 2, не изменённые решениями № 4–6, — числами книги (навёрстывание урезанного
    роста — 0 по решению № 5, п. 5: решение № 2 называло 0,25; оси у него нет — решение № 6, п. 5)."""
    assert book["regimes"]["ids"] == ["soft", "norm", "downturn", "crisis"] and book["regimes"]["cor_basis"] == "mgmt"
    assert [book["regimes"][r]["name"] for r in book["regimes"]["ids"]] == \
        ["Мягкая посадка", "Нормализация", "Розничный спад", "Кризис"]
    assert book["joint"]["regime_prob"] == {"soft": 0.15, "norm": 0.40, "downturn": 0.30, "crisis": 0.15}
    for r in ("soft", "norm", "downturn"):
        assert book["joint"]["reg_prob_given_regime"][r] == {"schedule": 0.35, "mid": 0.45, "strict": 0.20}
    assert book["joint"]["reg_prob_given_regime"]["crisis"] == {"schedule": 0.70, "mid": 0.25, "strict": 0.05}
    obs = book["joint"]["regime_update"]["observables"]
    assert obs == {"cor": {"sigma_pp": 0.0085, "rho_q": 0.25}, "nim": {"sigma_pp": 0.0035, "rho_q": 0.3}}
    cor = {r: book["regimes"][r]["cor"] for r in book["regimes"]["ids"]}
    assert [cor[r]["LT"] for r in cor] == [0.048, 0.055, 0.059, 0.061]
    assert [cor["crisis"][f"2027Q{k}"] for k in (1, 2, 3, 4)] == [0.130, 0.105, 0.088, 0.077] and cor["crisis"]["2027"] == 0.100
    assert [cor["downturn"][f"2027Q{k}"] for k in (1, 2, 3, 4)] == [0.062, 0.068, 0.072, 0.074]
    crisis = book["regimes"]["crisis"]
    assert crisis["one_off_loss"] == {"period": "2027Q1", "amount": -40.0}
    assert crisis["loan_growth_override"] == {"2027": 0.03, "2028": 0.06}
    assert crisis["rwa_density_mult"] == {"2026": 1.0, "2027": 0.90, "LT": 1.0, "LT_from": 2030}
    assert (book["credit"]["kappa"], book["credit"]["real_rate_lag_q"]) == (0.10, 2)
    assert book["credit"]["segment_relative"]["enabled"] is False and book["credit"]["fv_loans_factor"] == 0
    assert book["nii"]["transmission"]["weights"] == "anchor"
    drift = book["volumes"]["loan_share_drift"]
    assert [drift[g]["2026"] for g in ("corporate", "mortgage", "retail_other")] == [0.20, 0.03, 0.12]
    assert all(d == {"2026": d["2026"], "2027": d["2026"], "LT": 0.0, "LT_from": 2032} for d in drift.values())
    v = book["volumes"]
    assert (v["guidance_year"], v["share_drift_until"], v["lt_from"], v["link_base"]) == (2025, 2031, 2033, "loans")
    assert v["other_assets_fixed"] == "anchor" and book["capital"]["rwa"]["density"]["other_assets_fixed"] == 0.0
    assert book["capital"]["mgmt_buffer"] == {"n20_0": 0.015, "n1_1": 0.015}
    assert book["capital"]["reg_scenarios"]["ids"] == ["schedule", "mid", "strict"]
    gc = book["capital"]["growth_constraint"]
    assert gc == {"enabled": True, "order": "dividend_first", "min_growth_scale": 0, "lookahead_quarters": 8,
                  "glide_pp_per_quarter": 0.0025, "catch_up_rate": 0.0, "tol": 0.0001}
    assert not any("capital.growth_constraint.catch_up_rate" in a["paths"] for a in book["valuation"]["uncertainty"]["axes"])
    d = book["dividends"]
    assert d["calendar"]["frequency"] == "quarterly"
    assert d["calendar"]["decision_lag_quarters"] == {"1": 2, "2": 2, "3": 1, "4": 2}
    assert (d["calendar"]["reg_deduction_lag_quarters"], d["calendar"]["payment_lag_quarters"], d["calendar"]["checkpoints_ahead"]) == (2, 2, 0)
    assert (d["policy"]["history_test"], d["policy"]["cap"], d["policy"]["base_window_quarters"]) == ("cap", 0.30, 4)
    assert d["policy"]["threshold"] == 0.0 and d["policy"]["steps"] == [] and d["policy"]["deduct_at1_after_tax"] is False
    assert d["excess"] == {"from_profit_year": 2032, "epsilon": 0.5, "ramp_years": 3}
    assert d["crisis"] == {"skip_in_shock_year": True, "catch_up": False}
    val = book["valuation"]
    assert (val["shares_basis"], val["share_count_adj"], val["beta_e"], val["erp"]) == ("issued", 0.0, 1.04, 0.0557)
    assert (val["terminal"]["real_growth"], val["terminal"]["fade"], val["headline"]["print_step"]) == (0.015, 0.5, 5)
    assert val["uncertainty"]["draws"] == 2000
    assert book["equity"]["other_movements"] == {"LT": 0.0}
    assert len(book["nii"]["books"]) == 12 and list(book["nii"]["books"]) == list(BOOKS)


def test_lead_decisions_4_are_in_the_book(book):
    """Решения ведущего № 4 по сводке этапа 1, не изменённые решениями № 6, — числами книги."""
    nii = book["nii"]
    near = book["regimes"]["near_nim_shift"]                                         # п. 1: только ближний путь
    assert near["LT"] == 0.0 and near["LT_from"] == 2030
    axes = {a["paths"][0]: a for a in book["valuation"]["uncertainty"]["axes"]}
    key = nii["nim_lt_target_mgmt"]                                                  # ключ цели — внутри своей оси
    ax = axes["nii.nim_lt_target_mgmt"]
    assert ax["low"] < key < ax["high"]
    t2 = book["capital"]["n20"]["t2"]                                                # п. 3: инструменты растут с RWA
    assert len(t2) > 10 and t2["LT"] > t2["2026Q3"] > t2[book["meta"]["anchor_period"]] == 123.182   # ключ якоря — факт (№ 5, п. 7)
    rwa = book["capital"]["rwa"]                                                     # п. 4
    assert (rwa["density_drift_rate"], rwa["density_drift_until"]) == (0.010, 2027)
    assert (axes["capital.rwa.density_drift_rate"]["low"], axes["capital.rwa.density_drift_rate"]["high"]) == (-0.04, 0.035)
    buf = axes["capital.mgmt_buffer.n20_0"]                                          # п. 5: одна ось на оба норматива
    assert (buf["low"], buf["high"]) == (0.005, 0.025) and buf["paths"] == ["capital.mgmt_buffer.n20_0", "capital.mgmt_buffer.n1_1"]
    assert book["checks"]["bridge_drift_pp"] == {"cor": 0.002, "nim": 0.003}         # п. 6
    assert book["pnl"]["nci_share"] == 0.024                                         # п. 7
    gap = axes["capital.n20.gap_pp"]                                                 # п. 8
    assert (gap["low"], gap["high"]) == (-0.003, 0.003) and book["capital"]["n20"]["gap_pp"] == 0.0
    nc = book["noncore"]["result_real"]                                              # п. 9: ключ 2026 года — явно
    assert nc["2026"] == 10.13 and nc["LT"] == nc["2036"] == 3.78 and book["noncore"]["price_base_year"] == 2026
    assert (axes["valuation.governance.discount"]["low"], axes["valuation.governance.discount"]["high"]) == (0.0, 0.10)   # п. 10
    assert book["joint"]["regime_update"]["observations"] == []                      # п. 12: наблюдения — в базисе движка
    assert 0.0 <= nii["phi_split"] <= nii["sigma0_split"] <= 1.0                     # п. 13: доли заданы правилом (вывод на ядре)
    assert (axes["pnl.nci_share"]["low"], axes["pnl.nci_share"]["high"]) == (0.015, 0.035)   # п. 14
    assert book["capital"]["n20"]["deductions_anchor"] == 197.990                    # п. 15
    ch = book["checks"]                                                              # п. 16
    assert ch["roe_k_spread"]["max_world_gap"] == 0.08 and ch["ni_jump"]["yoy"] == 0.40
    assert ch["m_crisis_vs_cbr"]["cor_shock_year"] == 0.095
    nr = book["valuation"]["next_report"]
    assert nr["cor_values"] == [0.040, 0.045, 0.050, 0.055, 0.060] and nr["nim_values"] == [0.110, 0.113, 0.116, 0.119, 0.122]
    assert -0.02 < near["2026Q4"] < near["2026Q3"] < 0                               # п. 17: путь книги 11,53 и 11,48 % ниже механики
    #   книг; сами ключи выведены на ядре (tests/test_book_core.py сверяет печатаемую маржу, запись вывода — ниже)
    assert book["dividends"]["policy"]["payout"] == {"LT": 0.26}                     # п. 18
    pay = axes["dividends.payout_deviation"]
    assert (pay["low"], pay["high"]) == (-0.05, 0.04)
    assert abs(0.26 + pay["high"] - book["dividends"]["policy"]["cap"]) < 1e-12


def test_lead_decisions_6_are_in_the_book(book):
    """Решения ведущего № 6, не изменённые решениями № 7 и № 8, — числами книги: суждения, заданные правилом от фактов
    (гибкость расходов и услуг), гейты знака и их ключи, подписи, ось-связка гибкости."""
    assert (book["opex"]["volume_link"], book["fees"]["volume_link"], book["volumes"]["link_base"]) == (0.5, 0.6, "loans")
    ch = book["checks"]
    assert ch["stress_sign"] == {"loss_step": 60.0, "tol": 0.5} and ch["volume_sign"]["tol"] == book["valuation"]["headline"]["print_step"] / 10
    assert ch["pb_by_world"] == {w: [0.4, 2.5] for w in book["worlds"]["ids"]}
    axes = {a["paths"][0]: a for a in book["valuation"]["uncertainty"]["axes"]}
    bundle = axes["opex.volume_link"]
    assert bundle["kind"] == "bundle" and bundle["paths"][:2] == list(BUNDLE_LINKS)
    assert [bundle[e][p] for e in ("low", "high") for p in BUNDLE_LINKS] == [0.3, 0.4, 0.7, 0.8]
    satellites = [p for p in bundle["paths"][2:]]
    assert all(p.startswith(("opex.real_growth.", "fees.growth_vs_wages.")) and not p.endswith("LT_from") for p in satellites)
    assert {p.rsplit(".", 1)[1] for p in satellites if p.startswith("opex.")} == set(book["opex"]["real_growth"]) - {"LT_from"}
    assert {p.rsplit(".", 1)[1] for p in satellites if p.startswith("fees.")} == set(book["fees"]["growth_vs_wages"]) - {"LT_from"}
    misc = book["other"]["misc_net_real"]                              # «прочее» несёт стоимость прироста инструментов капитала
    years = [str(y) for y in range(int(book["meta"]["first_period"][:4]), int(book["meta"]["last_period"][:4]) + 1)]
    assert list(misc) == years + ["LT"] and misc["LT"] == misc[years[-1]]
    assert all(misc[a] > misc[b] for a, b in zip(years, years[1:])) and misc[years[0]] < 21.0
    m = axes["other.misc_net_real"]
    assert (m["kind"], m["low"], m["high"], m["unit"]) == ("shift", -13.0, 13.0, "bn")
    fees = book["fees"]["growth_vs_wages"]                             # спред услуг: корень года якоря, далее ноль
    assert fees["2026"] < 0 and all(fees[k] == 0.0 for k in ("2027", "2028", "2029", "2030", "LT")) and fees["LT_from"] == 2031
    labels = book["meta"]["labels"]
    assert (labels["terms"]["cir"], labels["terms"]["roe_lt"]) == ("C/I", "ROE после фазы роста")
    assert labels["terms"]["stake"] == "пакет Яндекса и долг под него"
    assert labels["rule_price"]["unconstrained"] == "Без ограничения роста капиталом"
    assert (labels["basis"]["dividend_issued"], labels["basis"]["dividend_outstanding"]) == ("на все размещённые акции", "на акции в обращении")


def test_lead_decisions_7_are_in_the_book(book):
    """Решения ведущего № 7, не изменённые решениями № 8, — числами книги: уровень, взятый из окна фактов, стоит в
    мире окна (мир-опора κ, цель C/I в ожидании слоя); премия роста средств клиентов — год якоря по факту, далее ноль,
    ось — связкой со сходом к 2032 году; гейты окна и стоимости средств; справочные варианты; строки обратного
    расчёта премии средств и уровня расходов; снятые ключи."""
    ch, nii = book["checks"], book["nii"]
    market = book["joint"]["macro_neutral_world"]
    assert "nim_lt" not in ch
    assert book["credit"]["kappa_reference_world"] == market == "M"
    assert ch["cir_lt"]["scope"] == "market_layer" and "catch_up_price" not in ch and ch["point_path"] is True
    wb = ch["window_backtest"]
    assert wb["from_year"] == 2030 and wb["cor"][0] < 0.0561 < wb["cor"][1] and wb["cir"][0] < ch["cir_lt"]["target"] < wb["cir"][1]
    quarters = json.loads((S.FACTS_DIR / "mgmt_quarterly.json").read_text(encoding="utf-8"))["quarters"]
    window = ("2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2")
    for key in ("cor", "cir"):                                           # коридоры — наименьший и наибольший квартал окна фактов
        vals = [quarters[q][f"{key}_exact"]["v"] for q in window]
        assert wb[key] == pytest.approx([min(vals), max(vals)], abs=6e-6), key
    assert ch["funds_cost_to_key"] == {"max": 0.706, "from_year": 2030}
    funds = book["volumes"]["funds_share_drift"]
    for seg in ("retail", "corporate"):
        assert list(funds[seg]) == [*ANCHOR_YEAR_QUARTERS, *PREMIUM_YEARS, "LT", "LT_from"]
        assert all(funds[seg][y] == 0.0 for y in PREMIUM_YEARS) and (funds[seg]["LT"], funds[seg]["LT_from"]) == (0.0, 2032)
    axes = {a["paths"][0]: a for a in book["valuation"]["uncertainty"]["axes"]}
    prem = axes["volumes.funds_share_drift.retail.2027"]
    paths = [f"volumes.funds_share_drift.{s}.{y}" for s in ("retail", "corporate") for y in PREMIUM_YEARS]
    assert prem["kind"] == "bundle" and prem["paths"] == paths and prem["unit"] == "pp"
    assert all(prem["high"][p] == -prem["low"][p] == PREMIUM_ENDS[p.rsplit(".", 1)[1]] for p in paths)
    assert not any(".2026" in p for p in paths)                              # ключи года якоря — факт, на оси не стоят
    rev = {tuple(a["paths"]): a for a in book["valuation"]["reverse_dcf"]["axes"]}
    assert rev[tuple(paths)]["kind"] == "shift" and rev[tuple(axes["opex.real_growth.2027"]["paths"])]["kind"] == "shift"
    assert rev[("dividends.payout_deviation",)]["search"] == [-0.25, 0.74]
    variants = book["valuation"]["reference_variants"]
    assert [v["id"] for v in variants][:8] == ["fade_symmetric", "kappa_zero", "divisor_earned_grants", "no_instrument_cost",
                                             "catch_up_quarter", "window_level_in_modal_cell", "funds_premium_need", "funds_premium_facts"]
    by_id = {v["id"]: v["overrides"] for v in variants}
    assert by_id["fade_symmetric"] == {"valuation.terminal.fade_mode": "symmetric"} and by_id["kappa_zero"] == {"credit.kappa": 0.0}
    assert by_id["catch_up_quarter"] == {"capital.growth_constraint.catch_up_rate": 0.25}
    assert set(by_id["window_level_in_modal_cell"]) == {"nii.transmission.level_world", "nii.nim_lt_target_mgmt", "nii.sigma0_split",
                                                      "nii.phi_split", "regimes.near_nim_shift", "fees.growth_vs_wages", "opex.real_growth"}
    record = json.loads((S.EVIDENCE / "path" / "out" / "derive_out.json").read_text(encoding="utf-8"))["need"]
    for vid, level in (("funds_premium_need", record["level"]), ("funds_premium_facts", -0.034)):
        assert set(by_id[vid]) == set(paths)
        assert all(by_id[vid][p] == pytest.approx(level * record["shape"][p.rsplit(".", 1)[1]], abs=1e-6) for p in paths), vid
    misc = by_id["no_instrument_cost"]["other.misc_net_real"]
    assert set(misc) == set(book["other"]["misc_net_real"]) and set(misc.values()) == {21.0}
    shares = json.loads((S.FACTS_DIR / "shares.json").read_text(encoding="utf-8"))
    earned = (shares["outstanding_total"]["v"] + 0.5 * shares["motivation_program"]["v"]) / shares["issued_total"]["v"] - 1
    assert by_id["divisor_earned_grants"] == {"valuation.share_count_adj": pytest.approx(earned, abs=6e-6)}


def test_lead_decisions_8_are_in_the_book(book):
    """Решения ведущего № 8 — числами книги: уровень маржи — ключом самого суждения в мире уровня (гейта стационарной
    маржи нет), ось и строка обратного расчёта — о нём же; цель передачи — середина диапазона свидетельств, ось — сам
    диапазон; цена недостающего фондирования — спред ликвидности плюс разность срочных вкладов и ликвидных активов
    окна; отток средств клиентов года якоря — квартальными ключами по факту последнего месячного релиза; строки
    обратного расчёта с уточнением на полной полосе и факты премий; поля окна фактов; справочные варианты; подписи;
    имя мира не совпадает с именем режима."""
    ch, nii = book["checks"], book["nii"]
    market = book["joint"]["macro_neutral_world"]
    assert nii["transmission"]["level_world"] == market == "M" and nii["nim_lt_target_mgmt"] == 0.111 and "nim_stationary" not in ch
    axes = {a["paths"][0]: a for a in book["valuation"]["uncertainty"]["axes"]}
    rev = {tuple(a["paths"]): a for a in book["valuation"]["reverse_dcf"]["axes"]}
    key_axis = axes["nii.nim_lt_target_mgmt"]
    assert (key_axis["kind"], key_axis["low"], key_axis["high"]) == ("value", 0.103, 0.116)
    assert rev[("nii.nim_lt_target_mgmt",)]["range"] == [0.103, 0.116]
    t = axes["nii.transmission.target"]                                     # передача: центр — середина оси свидетельств
    assert (t["kind"], t["low"], t["high"]) == ("value", 0.0, 0.12) and nii["transmission"]["target"] == pytest.approx((t["low"] + t["high"]) / 2)
    assert rev[("nii.transmission.target",)]["range"] == [0.0, 0.12]
    spread = {b: nii["books"][b]["spread"] for b in ("wholesale", "liquidity")}   # цена недостающего фондирования
    assert spread["wholesale"]["LT"] == pytest.approx(spread["liquidity"]["LT"] + TERM_OVER_LIQUID, abs=1e-9)
    assert spread["wholesale"]["2027"] == pytest.approx((spread["wholesale"]["2026"] + spread["wholesale"]["LT"]) / 2, abs=6e-6)
    w = axes["nii.books.wholesale.spread.LT"]
    assert (w["kind"], w["low"], w["high"]) == ("value", -0.015, 0.015) and w["low"] < spread["wholesale"]["LT"] < w["high"]
    # отток года якоря по кварталам: первый прогнозный квартал — остаток последнего месячного релиза к остатку якоря и
    # оставшиеся месяцы квартала темпом сектора; следующий квартал — темпом сектора
    seed = json.loads((S.ROOT / "data" / "indicators" / "seed" / "monthly_release.json").read_text(encoding="utf-8"))["months"]
    funds = book["volumes"]["funds_share_drift"]
    year = int(book["meta"]["first_period"][:4])
    last = max(m for m in seed if m.startswith(str(year)))
    anchor_month, last_month = int(book["meta"]["facts_date"][5:7]), int(last[5:7])
    quarter_end = 3 * int(book["meta"]["first_period"][5])
    assert anchor_month < last_month <= quarter_end
    for seg, node in (("retail", "funds_retail"), ("corporate", "funds_business")):
        growth = {book["worlds_bank"][wd]["funds_growth"][seg][str(year)] for wd in book["worlds"]["ids"]}
        assert len(growth) == 1                                              # рост сектора года якоря один во всех мирах
        r = seed[last]["values"][node]["v"] / seed[f"{year}M{anchor_month:02d}"]["values"][node]["v"]
        want = r ** 4 * (1 + growth.pop()) ** (4 * (quarter_end - last_month) / 12 - 1) - 1
        assert funds[seg][ANCHOR_YEAR_QUARTERS[0]] == pytest.approx(want, abs=1e-6), seg
        assert funds[seg][ANCHOR_YEAR_QUARTERS[1]] == 0.0 and str(year) not in funds[seg]
    assert funds["retail"][ANCHOR_YEAR_QUARTERS[0]] < funds["corporate"][ANCHOR_YEAR_QUARTERS[0]] < 0    # отток — у физлиц
    rd = book["valuation"]["reverse_dcf"]
    assert rd["premium_facts"] == [f"volumes.funds_share_drift.{seg}.{ANCHOR_YEAR_QUARTERS[0]}" for seg in ("retail", "corporate")]
    assert rd["refine_rows"] == ["nii.nim_lt_target_mgmt", "regimes.*.cor.LT"]
    wb = ch["window_backtest"]                                               # поля окна фактов — ряды эмитента и история баланса
    quarters = json.loads((S.FACTS_DIR / "mgmt_quarterly.json").read_text(encoding="utf-8"))["quarters"]
    history = json.loads((S.FACTS_DIR / "balance.json").read_text(encoding="utf-8"))["history"]
    assert tuple(sorted(history)) == WINDOW
    series = {k: [quarters[q][f"{k}_exact"]["v"] for q in WINDOW] for k in ("nim", "cor", "cir")}
    assert wb["nim"] == pytest.approx([min(series["nim"]), max(series["nim"])], abs=6e-6)
    assert wb["means"] == pytest.approx({k: sum(v) / len(v) for k, v in series.items()}, abs=6e-6) and set(wb["means"]) == set(series)
    share = [history[q]["loans"]["v"] / history[q]["iea"]["v"] for q in WINDOW]
    assert wb["loans_share"] == pytest.approx(sum(share) / len(share), abs=6e-5)
    assert wb["nim"][0] < nii["nim_lt_target_mgmt"] < wb["nim"][1] == pytest.approx(key_axis["high"], abs=2e-4)   # верх оси — лучший квартал окна
    variants = {v["id"]: v for v in book["valuation"]["reference_variants"]}
    assert list(variants)[8:] == ["no_near_shift", "near_shift_stays", "transmission_structural", "wholesale_bond_rate"]
    near = book["regimes"]["near_nim_shift"]
    zero, stays = (variants[k]["overrides"]["regimes.near_nim_shift"] for k in ("no_near_shift", "near_shift_stays"))
    assert set(zero) == set(stays) == set(near)                              # все ключи словаря на месте (оси их читают)
    assert all(v == 0.0 for k, v in zero.items() if k != "LT_from") and zero["LT_from"] == stays["LT_from"] == near["LT_from"]
    first = book["meta"]["first_period"]
    assert all(stays[k] == (near[k] if k.startswith(first[:4]) else near[first]) for k in stays if k != "LT_from")
    assert variants["transmission_structural"]["overrides"] == {"nii.transmission.target": t["high"]}
    assert variants["wholesale_bond_rate"]["overrides"] == {"nii.books.wholesale.spread.LT": w["high"]}
    old = variants["window_level_in_modal_cell"]                             # вариант прежней калибровки: его ключ — уровень мира-опоры
    assert old["overrides"]["nii.transmission.level_world"] == nii["transmission"]["reference_world"] and "печатает" in old["note"]
    assert all("note" not in v for k, v in variants.items() if k != "window_level_in_modal_cell")
    labels = book["meta"]["labels"]
    assert labels["dividends"]["pay_event"].startswith("Срок выплаты") and "{value}" in labels["gates"]["nim_anchor"]
    assert labels["nowcast"]["absent"].strip()
    names = [book["worlds"][wd]["name"] for wd in book["worlds"]["ids"]]
    regimes = [book["regimes"][r]["name"] for r in book["regimes"]["ids"]]
    scenarios = [book["capital"]["reg_scenarios"][s]["name"] for s in book["capital"]["reg_scenarios"]["ids"]]
    assert len(set(names + regimes + scenarios)) == len(names + regimes + scenarios)    # одно имя — один мир, режим или сценарий
    assert names == ["Нормализация ставок", "Высокие ставки надолго", "Рыночный как есть"]


def test_frozen_numbers_are_the_record_of_the_derivation(book):
    """Замороженные числа шаблона — запись вывода на ядре (`evidence/path/out/derive_out.json`): доли σ0 и φ, ближний
    сдвиг, траектория инструментов капитала и «прочее» с их стоимостью, спред услуг и корни расходов равны ключам
    записи; концы осей уровня расходов, долей и связки гибкости — её концам; ось уровня маржи — само суждение, и запись
    держит на её концах и на оси передачи стационарную маржу мира уровня; поля окна фактов — запись; запись начата со
    значений `derive_start.json`, сошлась и называет модальную клетку."""
    out = S.EVIDENCE / "path" / "out"
    record = json.loads((out / "derive_out.json").read_text(encoding="utf-8"))
    first = json.loads((out / "derive_start.json").read_text(encoding="utf-8"))
    start, before = first["keys"], first["before"]
    keys = record["keys"]
    assert set(keys) == set(start) == set(before) and record["modal_cell"]["label"] == "H/norm/mid"
    assert record["convergence"]["converged"] and record["convergence"]["rounds"][-1]["max_relative_change"] < record["convergence"]["tol"]
    assert record["frozen_check"]["nim_stationary_ok"] and record["frozen_check"]["cir_lt_ok"]
    assert record["opex"]["scope"] == book["checks"]["cir_lt"]["scope"]
    axes = {a["paths"][0]: a for a in book["valuation"]["uncertainty"]["axes"]}
    ends = record["ends"]
    assert [axes["nii.nim_lt_target_mgmt"][e] for e in ("low", "high")] == [ends["margin_axis"]["low"], ends["margin_axis"]["high"]]
    assert [axes["opex.real_growth.2027"][e] for e in ("low", "high")] == [ends["opex_axis"]["low"], ends["opex_axis"]["high"]]
    assert axes["opex.volume_link"]["paths"] == ends["bundle"]["paths"]
    assert all(axes["opex.volume_link"][e] == ends["bundle"][e] for e in ("low", "high"))
    assert [axes["nii.phi_split"][e] for e in ("low", "high")] == record["splits"]["axis_phi"]
    assert [axes["nii.transmission.target"][e] for e in ("low", "high")] == record["transmission"]["axis"]
    assert all(row["solved"] for row in record["transmission"]["rows"].values()) and record["transmission"]["level_world_fixed"] is True
    assert "nii.nim_lt_target_mgmt" not in keys and record["level"]["key"] == book["nii"]["nim_lt_target_mgmt"]
    assert record["level"]["world"] == book["nii"]["transmission"]["level_world"] == record["frozen_check"]["nim_level_world"]
    assert ends["margin_axis"]["stationary"] == pytest.approx(ends["margin_axis"]["stationary_goal"], abs=1e-9)
    assert book["checks"]["wholesale_share"] == ends["wholesale_share"]["corridor"]
    gate, phi = book["checks"]["funds_cost_to_key"], ends["phi_axis"]      # низ оси доли φ — не дальше порога гейта стоимости средств
    assert phi["low"] == axes["nii.phi_split"]["low"] and phi["funds_cost_to_key_at_low"] <= gate["max"] == phi["gate_max"]
    assert phi["low"] == phi["floor"] or phi["funds_cost_to_key_at_floor"] > gate["max"]
    window, wb = ends["window"], book["checks"]["window_backtest"]
    assert wb["nim"] == [window["nim"]["min"], window["nim"]["max"]] and wb["loans_share"] == window["loans_share"]["window"]
    assert wb["means"] == {k: window[k]["mean"] for k in ("nim", "cor", "cir")}
    assert (wb["cor"], wb["cir"]) == ([window["cor"]["min"], window["cor"]["max"]], [window["cir"]["min"], window["cir"]["max"]])
    for dotted, value in keys.items():
        node = book
        for part in dotted.split("."):
            node = node[part]
        if isinstance(value, dict):             # ключи года — средние кварталов: в шаблоне записаны девятью знаками
            assert set(node) == set(value) and all(node[k] == pytest.approx(value[k], abs=1e-9) for k in value), dotted
        else:
            assert node == value, dotted
    assert keys["capital.n20.t2"] != before["capital.n20.t2"] and keys["regimes.near_nim_shift"] != before["regimes.near_nim_shift"]


def test_numbers_derived_on_the_engine_are_marked_in_the_template(template_text):
    """Числа, зависящие от пути баланса (доли σ0 и φ, ближний сдвиг, спред услуг, корни расходов, «прочее» со
    стоимостью инструментов, инструменты капитала), несут в шаблоне пометку «ВЫВОДИТСЯ НА ЯДРЕ» (до вывода) или
    «ВЫВЕДЕНО НА ЯДРЕ» (после): число без пометки — число, которое при следующей версии книги забудут вывести заново.
    Ключ цели ЧПМ пометки не несёт: у книги с миром уровня он — само суждение."""
    lines = template_text.splitlines()
    key_line = next(i for i, ln in enumerate(lines) if ln.strip().startswith("nim_lt_target_mgmt:"))
    assert "НА ЯДРЕ" not in "\n".join(lines[key_line:key_line + 9])
    for key in DERIVED_ON_ENGINE:
        at = [i for i, ln in enumerate(lines) if ln.strip().startswith(key)]
        assert at, key
        near = "\n".join(lines[at[0]:at[0] + 4])
        assert re.search(r"ВЫВОДИТСЯ НА ЯДРЕ|ВЫВЕДЕНО НА ЯДРЕ", near), key


def test_crisis_keys_lie_in_the_shock_year(book):
    """Год шока = год якоря + `shock_year_offset`; квартальный профиль CoR кризиса, период разового убытка, первый
    год `loan_growth_override` и минимум множителя RWA лежат в году шока (иначе ядро отказывает `BookError`)."""
    crisis = book["regimes"]["crisis"]
    off = crisis["shock_year_offset"]
    assert isinstance(off, int) and not isinstance(off, bool) and off >= 1
    shock = int(book["meta"]["anchor_period"][:4]) + off
    assert crisis["one_off_loss"]["period"][:4] == str(shock)
    quarters = sorted(k for k in crisis["cor"] if "Q" in str(k))
    assert quarters == [f"{shock}Q{k}" for k in (1, 2, 3, 4)]
    assert min(int(y) for y in crisis["loan_growth_override"]) == shock
    mult = crisis["rwa_density_mult"]
    assert mult[str(shock)] == min(v for k, v in mult.items() if k != "LT_from") and mult[str(shock - 1)] == 1.0
    ax = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["paths"][0].startswith("regimes.crisis.rwa_density_mult"))
    assert ax["paths"] == [f"regimes.crisis.rwa_density_mult.{shock}"] and ax["kind"] == "value" and ax["high"] == 1.0
    assert "rwa_density_mult" not in book["regimes"]["norm"]


def test_books_flags_and_spread_floors_are_consistent(book):
    """Двенадцать книг: подпись у каждой; балансирующие книги сдвига σ0 и сжатия φ не несут; у обеих книг средств
    физлиц флаги одинаковы; сжатие и сдвиг несут одни и те же книги; полы спреда и плотности RWA — по шести кредитным
    книгам; доли σ0 и φ лежат внутри своих осей."""
    nii = book["nii"]
    books = nii["books"]
    assert all(isinstance(v["name"], str) and v["name"].strip() for v in books.values())
    assert books["wholesale"]["name"] == "Оптовое фондирование" and not any("fv_share" in v for v in books.values())
    loans = [b for b, v in books.items() if "sector" in v]
    assert loans == list(CREDIT_BOOKS)
    assert [b for b, v in books.items() if v.get("balancing")] == ["securities", "liquidity", "wholesale"]
    assert not any(v["lt_shift"] or v["phi"] for v in books.values() if v.get("balancing"))
    assert books["retail_current"]["lt_shift"] is books["retail_term"]["lt_shift"]
    assert books["retail_current"]["phi"] is books["retail_term"]["phi"]
    assert {b for b, v in books.items() if v["phi"]} == {b for b, v in books.items() if v["lt_shift"]}
    assert books["sme_loans"]["sector"] == "corporate" and books["sme_loans"]["cor_segment"] == "retail"
    for key in ("sigma0_split", "phi_split"):
        ax = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["paths"] == [f"nii.{key}"])
        assert ax["kind"] == "value" and 0.0 <= ax["low"] <= nii[key] <= ax["high"] <= 1.0
    floors = book["checks"]["lt_spread_floor"]
    assert set(floors) == set(loans) and all(isinstance(v, float) and 0.0 <= v < 0.20 for v in floors.values())
    dens = book["capital"]["rwa"]["density"]
    assert set(dens) == set(loans) | {"securities", "liquidity", "other_assets", "other_assets_fixed"}
    assert set(book["meta"]["labels"]["control"]["books"]) == set(loans)


# Единица оси для печати (MODEL §10, PAYLOAD §0.2): код и правило по ПУТЯМ оси, не по словам имени
AXIS_UNITS = {"pct", "pp", "number", "years", "bn"}
YEARS_PATHS = ("oci.fvoci_duration", "oci.fvoci_maturity")
PP_MARKS = ("_pp", "nim_shift", "mgmt_buffer", "spread")
BN_PATHS = ("regimes.crisis.one_off_loss.amount", "capital.n20.t2", "noncore.result_real", "other.misc_net_real")


def test_scalar_axes_carry_the_unit_of_their_paths(book):
    """У каждой скалярной оси — поле `unit` из кодов выпуска; у оси-словаря его нет. Сдвиг доли (вид `shift` на долях,
    пути с `_pp`, сдвиг ЧПМ режима, запас, спред) — `pp`; срок — `years`; суммы в млрд ₽ — `bn` по путям денежных ключей;
    коэффициент больше единицы процентом не печатается."""
    for a in book["valuation"]["uncertainty"]["axes"]:
        if a["kind"] == "dict":
            assert "unit" not in a, a["name"]
            continue
        unit, paths = a.get("unit"), a["paths"]
        assert unit in AXIS_UNITS, (a["name"], unit)
        money = any(p.startswith(BN_PATHS) for p in paths)
        assert (unit == "bn") == money, a["name"]
        if not money and (a["kind"] == "shift" or any(m in p for p in paths for m in PP_MARKS)):
            assert unit == "pp", a["name"]
        assert (unit == "years") == any(p in YEARS_PATHS for p in paths), a["name"]
        if unit in ("pct", "pp"):
            ends = [v for e in ("low", "high") for v in (a[e].values() if a["kind"] == "bundle" else [a[e]])]
            assert max(abs(v) for v in ends) <= 1.0, a["name"]


def test_the_regime_floor_is_a_share_of_the_base_probability(book):
    ru = book["joint"]["regime_update"]
    share, prior = ru["floor_share"], book["joint"]["regime_prob"]
    assert isinstance(share, float) and 0.0 < share < 1.0 and ru["window_obs"] == 4 and ru["max_shift_pp"] == 0.05
    floors = {r: share * p for r, p in prior.items()}
    assert abs(sum(floors.values()) - share) < 1e-12
    assert floors["soft"] == pytest.approx(0.0495) and floors["crisis"] == pytest.approx(0.0495)
    assert all(floors[r] < prior[r] for r in prior)


def off_band_report(book: dict, rows: list, point: float) -> dict:
    """Три условия оси вне полосы (MODEL §10) по строкам цены ошибки суждения: (1) ожидаемая доля размах² / Σ размах²
    меньше 1 %; (2) |сдвиг положения оси| < print_step / 10; (3) |Σ сдвигов по осям вне полосы| ≤ print_step / 10.
    Сдвиг положения — (цена_high + цена_low − 2 × точка) / 6. Возвращает {имя оси или «Σ»: [что нарушено]}."""
    limit = book["valuation"]["headline"]["print_step"] / 10
    by_name = {r["name"]: r for r in rows}
    total = sum(r["swing"] ** 2 for r in rows if r.get("swing") is not None)
    bad, shifts = {}, 0.0
    for a in book["valuation"]["uncertainty"]["off_band_axes"]:
        r = by_name.get(a["name"])
        if r is None:
            bad[a["name"]] = ["нет строки цены ошибки суждения — нужен прогон ядра на этой книге"]
            continue
        shift = (r["price_high"] + r["price_low"] - 2 * point) / 6
        shifts += shift
        why = []
        if not r["swing"] ** 2 / total < 0.01:
            why.append("доля размаха не меньше 1 %")
        if not abs(shift) < limit:
            why.append(f"сдвиг положения {shift:+.2f} ₽")
        if a["kind"] == "dict" or any(p.startswith(NEVER_OFF_BAND) for p in a["paths"]):
            why.append("ось-словарь или односторонняя рисковая ось")
        if why:
            bad[a["name"]] = why
    if abs(shifts) > limit:
        bad["Σ"] = [f"сумма сдвигов положения {shifts:+.2f} ₽ больше {limit} ₽"]
    return bad


def test_off_band_axes_meet_the_three_conditions(book):
    """Ось вне полосы допустима только при трёх условиях MODEL §10 (у книги 1.0 список пуст — все оси в полосе).
    Проверка — по `results.json`; с непустым списком результаты обязаны быть этой книги."""
    off = book["valuation"]["uncertainty"]["off_band_axes"]
    names = {a["name"] for a in book["valuation"]["uncertainty"]["axes"]}
    assert not [a["name"] for a in off if a["name"] in names]
    if not off:
        return
    res = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert res["book_version"] == book["meta"]["version"], "оси вне полосы проверяются по результатам этой книги"
    assert off_band_report(book, res["judgements"], res["headline"]["point"]) == {}


def test_the_off_band_rule_catches_an_asymmetric_and_a_wide_axis(book):
    """Правило на заглушке: узкая симметричная ось проходит; асимметричная, широкая, налоговая и сумма сдвигов — нет."""
    step = book["valuation"]["headline"]["print_step"]
    point = 400.0

    def row(name, lo, hi):
        return {"name": name, "price_low": lo, "price_high": hi, "swing": abs(hi - lo)}

    def variant(axes):
        b = {"valuation": {"headline": {"print_step": step}, "uncertainty": {"off_band_axes": axes}}}
        return off_band_report(b, rows, point)

    rows = [row("главная", 300.0, 520.0), row("узкая", 399.0, 401.0), row("асимметричная", 400.0, 400.0 - step),
            row("широкая", 370.0, 430.0), row("налог", 400.0, 399.5), row("ещё узкая", 399.6, 400.2),
            row("вниз 1", 400.0, 398.2), row("вниз 2", 400.0, 398.4)]
    ax = {n: {"name": n, "kind": "value", "paths": ["x.y"]}
          for n in ("узкая", "асимметричная", "широкая", "ещё узкая", "вниз 1", "вниз 2")}
    ax["налог"] = {"name": "налог", "kind": "shift", "paths": ["tax.statutory"]}
    assert variant([ax["узкая"], ax["ещё узкая"]]) == {}
    assert list(variant([ax["асимметричная"]])) == ["асимметричная", "Σ"]
    assert list(variant([ax["широкая"]])) == ["широкая"]
    assert list(variant([ax["налог"]])) == ["налог"]
    assert list(variant([ax["вниз 1"], ax["вниз 2"]])) == ["Σ"]
    assert "нет строки" in variant([{"name": "новая", "kind": "value", "paths": ["x.y"]}])["новая"][0]


def test_the_near_nim_shift_covers_the_near_path_only(book):
    """Ближний сдвиг ЧПМ (решение ведущего № 4, п. 1): квартальные ключи — от первого прогнозного квартала до конца 2029
    года, ключ года — среднее своих квартальных ключей, с 2030 года — 0; ось скорости схода двигает ключи 2027–2029
    (годовые и квартальные вместе)."""
    near = book["regimes"]["near_nim_shift"]
    first = book["meta"]["first_period"]
    q_keys = sorted(k for k in near if "Q" in k)
    y0 = int(first[:4])
    expected = [f"{y0}Q{k}" for k in range(int(first[5]), 5)] + [f"{y}Q{k}" for y in range(y0 + 1, 2030) for k in (1, 2, 3, 4)]
    assert q_keys == expected
    for y in sorted({k[:4] for k in q_keys}):
        qs = [near[k] for k in q_keys if k.startswith(y)]
        assert near[y] == pytest.approx(sum(qs) / len(qs), abs=1e-9), y
    assert near["LT"] == 0.0 and near["LT_from"] == 2030 and S.year_value({k: v for k, v in near.items() if "Q" not in k}, 2031) == 0.0
    ax = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["paths"][0].startswith("regimes.near_nim_shift"))
    assert ax["kind"] == "shift" and ax["unit"] == "pp"
    assert sorted(p.rsplit(".", 1)[1] for p in ax["paths"]) == sorted(k for k in near if k[:4] in ("2027", "2028", "2029"))
    assert all(book["regimes"][r]["nim_shift"]["2026"] == 0.0 for r in book["regimes"]["ids"])


def test_value_axes_on_year_keys_do_not_meet_quarter_keys(book):
    """Ось `value` на ключе года траектории с квартальными ключами этого года — отказ ядра (MODEL §0.4); ось `shift`
    на таком году обязана двигать ключ года и все его квартальные ключи вместе (иначе ключ года перестаёт быть средним)."""
    unc = book["valuation"]["uncertainty"]
    for a in unc["axes"] + unc["off_band_axes"]:
        for p in a["paths"]:
            head, _, key = p.rpartition(".")
            if not (key.isdigit() and S.has(book, head) and isinstance(S.get(book, head), dict)):
                continue
            quarters = [f"{head}.{k}" for k in S.get(book, head) if str(k).startswith(key + "Q")]
            if a["kind"] == "value":
                assert not quarters, (a["name"], p)
            elif quarters:
                assert set(quarters) <= set(a["paths"]), (a["name"], p)


def test_the_capital_instruments_trajectory_is_quarterly_and_ends_flat(book):
    """Инструменты капитала (решение ведущего № 4, п. 3): траектория в рублях по концам кварталов от первого прогнозного
    квартала до года перед последним; перед ними — ключ квартала якоря, равный факту (решение № 5, п. 7: строка якоря
    воспроизводит норматив); последний год — ключом года, равным LT; путь не убывает; ось — сдвиг всего пути."""
    t2 = book["capital"]["n20"]["t2"]
    first, last = book["meta"]["first_period"], int(book["meta"]["last_period"][:4])
    q_keys = [k for k in t2 if "Q" in k]
    y0 = int(first[:4])
    expected = [book["meta"]["anchor_period"]] + [f"{y0}Q{k}" for k in range(int(first[5]), 5)]         + [f"{y}Q{k}" for y in range(y0 + 1, last) for k in (1, 2, 3, 4)]
    fact = json.loads((S.FACTS_DIR / "capital.json").read_text(encoding="utf-8"))["t2_recognized"]["v"]
    assert t2[book["meta"]["anchor_period"]] == fact
    assert q_keys == expected and t2[str(last)] == t2["LT"] and "LT_from" not in t2
    vals = [t2[k] for k in q_keys] + [t2["LT"]]
    assert all(b >= a for a, b in zip(vals, vals[1:]))
    ax = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["paths"] == ["capital.n20.t2"])
    assert (ax["kind"], ax["low"], ax["high"], ax["unit"]) == ("shift", -37.0, 37.0, "bn")


def test_premiums_are_trajectories_by_sector_and_end_by_the_drift_year(book):
    """Премии роста (MODEL §4.3): у кредитов — ровно три группы сектора, у средств — два сегмента; после
    `share_drift_until` премия равна нулю и при сдвинутой оси: у кредитов ось вида `shift` двигает и LT, у средств
    клиентов ось-связка не трогает ни LT, ни ключ года якоря."""
    v = book["volumes"]
    assert list(v["loan_share_drift"]) == ["corporate", "mortgage", "retail_other"]
    assert list(v["funds_share_drift"]) == ["retail", "corporate"]
    for traj in list(v["loan_share_drift"].values()) + list(v["funds_share_drift"].values()):
        assert traj["LT"] == 0.0 and traj["LT_from"] == v["share_drift_until"] + 1
    assert all(traj["2026"] == traj["2027"] > 0 for traj in v["loan_share_drift"].values())
    axes = {a["paths"][0]: a for a in book["valuation"]["uncertainty"]["axes"]}
    head, keys = "volumes.loan_share_drift", ("corporate", "mortgage", "retail_other")
    ax = axes[f"{head}.{keys[0]}"]
    assert ax["kind"] == "shift" and ax["paths"] == [f"{head}.{k}" for k in keys] and (ax["low"], ax["high"]) == (-0.05, 0.05)
    funds = axes["volumes.funds_share_drift.retail.2027"]
    assert funds["kind"] == "bundle" and all(int(p.rsplit(".", 1)[1]) <= v["share_drift_until"] for p in funds["paths"])
    assert v["guidance_year"] < int(book["meta"]["first_period"][:4])           # механизм гайденса роста выключен
    assert v["guidance_growth"] == {"corporate": 0.0, "retail": 0.0}


def test_misc_quarter_shares_and_the_volume_links(book):
    shares = book["other"]["misc_quarter_shares"]
    assert list(shares) == ["1", "2", "3", "4"] and abs(sum(shares.values()) - 1.0) < 1e-9 and set(shares.values()) == {0.25}
    assert (book["fees"]["volume_link"], book["opex"]["volume_link"], book["other"]["insurance_volume_link"]) == (0.6, 0.5, 0.0)
    assert book["fees"]["growth_override"] == {} and book["other"]["fvtpl_bond_reval"] is False


def test_opex_roots_and_their_axis(book):
    """Корни реального роста расходов: один корень 2027–2030, один 2031–2032, LT с года `volumes.lt_from`; ось полосы
    сдвигает только корень 2027–2030; цель C/I живёт в коридоре гейта долгосрочного C/I."""
    og = book["opex"]["real_growth"]
    assert len({og[str(y)] for y in (2027, 2028, 2029, 2030)}) == 1 and og["2031"] == og["2032"]
    assert og["LT_from"] == book["volumes"]["lt_from"] == book["checks"]["cir_lt"]["from_year"]
    ax = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["paths"][0].startswith("opex.real_growth"))
    assert ax["kind"] == "shift" and ax["paths"] == [f"opex.real_growth.{y}" for y in (2027, 2028, 2029, 2030)]
    assert book["checks"]["cir_lt"] == {"target": 0.47, "tolerance": 0.01, "from_year": 2033, "scope": "market_layer"}


def test_the_labels_are_complete_and_carry_only_known_fields(book):
    """Подписи книги (MODEL §0.6): все группы и ключи договора, непустые строки; поля подстановки — только названные у
    ключа; слова «сквозь цикл» в текстах Т не употребляются; набор строк сводки контрольной модели — ровно пятнадцать."""
    labels = book["meta"]["labels"]
    assert set(labels) == set(LABEL_GROUPS)
    for group, keys in LABEL_GROUPS.items():
        assert set(labels[group]) == keys, group
    assert set(labels["control"]["lines"]) == CONTROL_LINES
    assert set(labels["nowcast"]["targets"]) == {"ni_q", "nim_q", "cor_q"}
    for t in labels["nowcast"]["targets"].values():
        assert set(t) == {"title", "basis", "title_long"} and t["basis"] == "mgmt"
    count = 0
    for path, value in S.leaves(labels):
        if path.endswith(".basis"):
            continue
        count += 1
        assert isinstance(value, str) and value.strip(), path
        fields = {name for _, name, spec, conv in Formatter().parse(value) if name is not None}
        assert fields <= LABEL_FIELDS.get(path, set()), (path, fields)
        assert "сквозь цикл" not in value, path
    assert count >= 44
    assert labels["terms"]["lt_level"] == "после фазы роста" and labels["basis"]["divisor"] == "размещённые акции"
    assert labels["capital"]["n20_short"] == "Н20.0" and labels["capital"]["n11_short"] == "Н20.1"


def test_guidance_items_and_gate_corridors_have_valid_forms(book):
    """Узлы гайденса: без повторов, у узла гейта есть слова; коридоры гейтов — [мин < макс]; новые гейты второй формы."""
    ch = book["checks"]
    items = ch["guidance_items"]
    assert [i["key"] for i in items] == ["op_np_growth", "dps_growth", "roe_target", "nim", "cor_max", "cir"]
    for i in items:
        assert set(i) == {"key", "path", "title", "words", "basis", "gate"} and i["path"] == f"items.{i['key']}" and i["basis"] == "mgmt"
        assert i["title"].strip() and (not i["gate"] or i["words"].strip())
    assert [i["gate"] for i in items] == [True, True, False, True, True, True]
    for key in ("roe_range", "cor_range", "nim_range", "cir_range", "terminal_share", "real_rate", "transmission_pairs", "wholesale_share"):
        lo, hi = ch[key]
        assert lo < hi, key
    assert 0 < ch["growth_cut"]["max_cut_share"] <= 1 and 0 < ch["step_dividend"]["max_lam_drop"] <= 1
    assert ch["manual_overdue_days"] == {"ifrs_fact": 7, "worlds_after_cbr": 21, "dividend_register": 5, "capital_form": 7}
    assert ch["wholesale_share"][0] < 0.135 < ch["wholesale_share"][1]                # якорь внутри коридора
    assert ch["nim_range"][0] <= book["nii"]["nim_lt_target_mgmt"] <= ch["nim_range"][1]
    assert ch["cir_range"][0] < ch["cir_lt"]["target"] < ch["cir_range"][1]
    for k in ("nim_path_joint", "ni_jump"):
        assert isinstance(ch[k]["quarters"], int) and 1 <= ch[k]["quarters"] <= 42
    lo, hi = book["valuation"]["sensitivities"]["rank_window"]
    assert 0.0 < lo < 0.5 < hi < 1.0 and book["valuation"]["sensitivities"]["buffer_pp"] == 0.01


def test_near_spread_keys_follow_the_anchor_rates(book):
    """Ближние ключи спредов (MODEL §4.4): ключ года якоря = ставка якоря − опора мира отсчёта в первом прогнозном
    квартале (у пассивов β × опора); следующий год — середина до калибровки года якоря + 2. Ставки якоря — факты
    `data/facts/nii_books.json`; пока в каталоге фактов нет книг Т, сверку несёт лист `evidence/nii`."""
    facts_path = S.FACTS_DIR / "nii_books.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))["books"] if facts_path.exists() else {}
    if not set(book["nii"]["books"]) <= set(facts):
        pytest.skip("в data/facts ещё нет ставок якоря двенадцати книг Т — сверку несёт лист evidence/nii")
    first = book["meta"]["first_period"]
    y0 = int(first[:4])
    half = f"{y0}H{1 if int(first[5]) <= 2 else 2}"
    ref_world = book["worlds"][book["nii"]["transmission"]["reference_world"]]
    field = {"key": "key_rate"}
    checked = []
    for b, spec in book["nii"]["books"].items():
        sp = spec["spread"]
        if not isinstance(sp, dict) or str(y0) not in sp:
            continue
        ref = ref_world[field.get(spec["ref"], spec["ref"])][half]
        beta = spec["beta"] if spec["side"] == "liability" else 1.0
        s0 = facts[b]["rate_anchor"]["v"] - beta * ref
        assert sp[str(y0)] == pytest.approx(s0, abs=6e-6), b
        mid = (sp[str(y0)] + S.year_value(sp, y0 + 2)) / 2
        assert sp[str(y0 + 1)] == pytest.approx(mid, abs=6e-6), b
        checked.append(b)
    assert set(CREDIT_BOOKS) <= set(checked)
