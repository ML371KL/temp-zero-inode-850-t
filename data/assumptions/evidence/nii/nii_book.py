# -*- coding: utf-8 -*-
"""ЧПД: числа книги против листа калибровки этапа 1 и фактов якоря (MODEL §4.4–§4.5).

Лист калибровки ЧПД этапа 1 (оценки ρ, β и спредов по истории ставок книг, решатель σ0 и φ, пробный путь ЧПМ) считался
на коде и данных книги Сбербанка как носителе и в репозиторий целиком не переносится: его выходы лежат малыми входами
(inputs/stage1/calib/nii/out, sha256 — inputs/SOURCES.json), а этот лист повторяет независимо всё, что выводится из
фактов якоря и записи миров, и сверяет шаблон книги:
  * двенадцать книг шаблона = предложение листа (кроме подписи оптового фондирования, ключа кредитов по справедливой
    стоимости — поправки сводки этапа 1 — и траектории спреда оптового фондирования: её долгосрочный уровень задан
    правилом книги);
  * долгосрочный спред оптового фондирования — цена недостающего фондирования: долгосрочный спред книги ликвидности
    плюс средняя по окну разность ставки срочных вкладов физлиц и доходности ликвидных активов (панель ставок листа
    калибровки, книги `retail_term` и `liquidity`);
  * ближние ключи спредов: "2026" = ставка якоря − опора мира H в первом прогнозном квартале (у пассивов β × опора),
    "2027" — середина между "2026" и значением 2028 года;
  * тождество процентов якоря: проценты 12 книг − взносы в систему страхования вкладов + проценты вне книг = ЧПД квартала;
  * доли якоря (текущие счета, оптовое фондирование, бумаги в ликвидных активах) и ставка взносов;
  * цель передачи — суждение книги (+0,06: середина диапазона свидетельств 0…+0,12 — от «история знака не определяет»
    до структурной оценки баланса якоря); мир уровня — мир слоя «Рыночные ставки как есть»; прочие ключи узла
    передачи — лист;
  * суждение о марже — ключ цели ЧПМ: стационарная маржа мира уровня на составе баланса якоря. Число правила считается
    здесь из входов листа — средняя упр. ЧПМ семи кварталов окна, приведённая к составу баланса якоря (доля кредитов
    в процентных активах по определению эмитента на концах кварталов; наклон — разность доходностей кредитных книг и
    ликвидных активов якоря); рядом — средняя четырёх последних кварталов и её состав;
  * ось уровня маржи и диапазон строки обратного расчёта — само суждение (10,3…11,6 %); запись вывода на ядре держит
    стационарную маржу мира уровня равной ключу, а на оси передачи — неподвижной;
  * поля окна фактов по марже (checks.window_backtest.nim и means.nim) — наименьший, наибольший и средний квартал окна;
  * порог гейта стоимости средств клиентов к ключевой ставке (checks.funds_cost_to_key.max) — наибольший квартал окна
    по панели ставок: проценты трёх книг средств клиентов к их средним остаткам, к средней ключевой ставке квартала;
  * доли σ0 и φ на кредитных книгах — ключи, заданные правилом: равны записи вывода; доля φ — меньшее из доли по
    истории наклонов и предела гейта пола спреда (вниз до 0,01); гейт пола спреда в центре книги проходит; низ оси
    доли φ — не дальше порога гейта стоимости средств клиентов (запись вывода);
  * ближний сдвиг ЧПМ: ключи 2026–2029 выведены на ядре (лист path/derive_on_engine.py), с 2030 года — 0; здесь — форма
    траектории и ось; пробный проход листа калибровки печатается справочно;
  * полы спредов кредитных книг — правило листа: меньшее из стоимости риска продукта и минимума спреда окна, вниз до 0,5 п.п.
Решатель σ0 и φ на книге Т, доли, ближний сдвиг и концы осей на ядре выводит evidence/path/derive_on_engine.py.
Запуск из корня репозитория: python -B data/assumptions/evidence/nii/nii_book.py → out/nii_book_out.json
(код выхода 1 — расхождение с шаблоном книги).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
IN = HERE / "inputs"
OUT = HERE / "out"
sys.path.insert(0, str(HERE.parent))
import evlib  # noqa: E402

NII_ANCHOR_Q = 157.6          # ЧПД 2-го квартала 2026 года, млрд ₽ (МСФО 6М2026, отчёт о прибыли)
DIA_Q = 4.6                   # взносы в систему страхования вкладов за квартал (там же)
LEASE_INTEREST_Q = 1.1        # процентные расходы по аренде — вне книг (там же)
WINDOW = ("2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2")   # окно фактов: семь кварталов после покупки Росбанка
BEFORE_WINDOW = "2024Q3"      # конец квартала перед окном: начало первого квартала окна
NIM_AXIS_STATIONARY = [0.103, 0.116]   # ось суждения о стационарной марже мира уровня (низ — суждение; верх — лучший квартал окна)
TERM_BOOK, LIQUIDITY_BOOK, WHOLESALE_BOOK = "retail_term", "liquidity", "wholesale"   # книги правила цены недостающего фондирования
WHOLESALE_AXIS = [-0.015, 0.015]       # ось долгосрочного спреда оптового фондирования к ключевой: до облигационного уровня
LOAN_BOOKS = ("cards", "cash_loans", "auto", "mortgage", "sme_loans", "corp_loans")
LIQUID_BOOKS = ("securities", "liquidity")
FUNDS_BOOKS = ("retail_current", "retail_term", "corp_funds")     # книги средств клиентов панели ставок
PANEL_BASIS = "IFRS new"      # базис панели ставок: книги по примечаниям отчётности после покупки Росбанка
METRIC_IEA, METRIC_NIM, METRIC_LOANS = "iea_mgmt", "nim_exact", "loans_gross_incl_lease_fvtpl"
TRANSMISSION_AXIS = [0.0, 0.12]     # диапазон свидетельств: ноль (история знака не определяет) … структурная оценка баланса якоря
TRANSMISSION_TARGET = 0.06    # цель передачи — середина диапазона свидетельств (суждение книги)
RECORD = HERE.parent / "path" / "out" / "derive_out.json"       # запись вывода на ядре
REF_FIELD = {"key": "key_avg", "ofz_1y": "ofz_1y", "ofz_3y": "ofz_3y", "ofz_5y": "ofz_5y", "ofz_10y": "ofz_10y"}
RENAMED = {"wholesale": "Оптовое фондирование"}                   # сводка этапа 1, раздел 3, № 10


def quarter_of(day: str) -> str:
    """Дата конца квартала ГГГГ-ММ-ДД → ГГГГQк."""
    return f"{day[:4]}Q{(int(day[5:7]) - 1) // 3 + 1}"


def margin_rule() -> dict:
    """Правило суждения о марже из входов листа: средняя упр. ЧПМ окна, приведённая к составу баланса якоря.
    Состав — доля кредитов в процентных активах по определению эмитента (знаменатель его ЧПМ) на концах кварталов;
    состав квартала — среднее двух концов; наклон — разность доходностей кредитных книг и ликвидных активов якоря."""
    kpi = evlib.read_csv(IN / "stage1/mgmt/mgmt_kpi.csv")
    iea = {r["period"]: float(r["value"]) for r in kpi if r["metric"] == METRIC_IEA}
    nim = {r["period"]: float(r["value"]) / 100 for r in kpi if r["metric"] == METRIC_NIM}
    loans = {quarter_of(r["period"]): float(r["value"]) for r in evlib.read_csv(IN / "stage1/ifrs/ifrs_history.csv")
             if r["metric"] == METRIC_LOANS}
    ends = (BEFORE_WINDOW,) + WINDOW
    share = {q: loans[q] / iea[q] for q in ends}
    by_quarter = {q: (share[ends[i]] + share[q]) / 2 for i, q in enumerate(WINDOW)}
    ab = {r["book"]: r for r in evlib.read_csv(IN / "stage1/ifrs/anchor_books.csv")}

    def yld(books) -> float:
        return (sum(abs(float(ab[b]["interest_2Q2026"])) for b in books) * 365 / 91
                / sum(float(ab[b]["avg_2Q2026"]) for b in books))

    slope = yld(LOAN_BOOKS) - yld(LIQUID_BOOKS)                 # доля маржи на единицу доли кредитов
    mean7 = sum(nim[q] for q in WINDOW) / len(WINDOW)
    comp7 = sum(by_quarter.values()) / len(WINDOW)
    last4 = WINDOW[-4:]
    mean4, comp4 = sum(nim[q] for q in last4) / 4, sum(by_quarter[q] for q in last4) / 4
    anchor = share[WINDOW[-1]]
    return {"window": list(WINDOW), "nim_by_quarter": {q: round(nim[q], 6) for q in WINDOW},
            "window_mean_mgmt": round(mean7, 5), "window_best_quarter": round(max(nim[q] for q in WINDOW), 5),
            "loan_share_ends": {q: round(v, 4) for q, v in share.items()},
            "loan_share_window": round(comp7, 4), "loan_share_anchor": round(anchor, 4),
            "yield_loans_anchor": round(yld(LOAN_BOOKS), 5), "yield_liquid_anchor": round(yld(LIQUID_BOOKS), 5),
            "composition_slope_pp_per_point": round(slope, 4),
            "rule": round(mean7 + slope * (anchor - comp7), 5),
            "last_four": {"mean_mgmt": round(mean4, 5), "loan_share": round(comp4, 4),
                          "at_anchor_composition": round(mean4 + slope * (anchor - comp4), 5)}}


def funds_cost_to_key() -> dict:
    """Стоимость средств клиентов к ключевой ставке по кварталам окна (панель ставок листа калибровки): проценты
    трёх книг средств клиентов к их средним остаткам (ставка книги × средний остаток), к средней ключевой квартала."""
    rows = [r for r in evlib.read_csv(IN / "stage1/calib/nii/out/rates_panel.csv")
            if r["basis"] == PANEL_BASIS and r["series"] in FUNDS_BOOKS and r["quarter"] in WINDOW]
    out = {}
    for q in WINDOW:
        mine = [r for r in rows if r["quarter"] == q]
        assert len(mine) == len(FUNDS_BOOKS), (q, len(mine))
        cost = sum(float(r["rate"]) * float(r["avg_balance"]) for r in mine) / sum(float(r["avg_balance"]) for r in mine)
        out[q] = {"cost": round(cost, 5), "key": float(mine[0]["key"]), "ratio": round(cost / float(mine[0]["key"]), 4)}
    worst = max(out, key=lambda q: out[q]["ratio"])
    return {"by_quarter": out, "max": out[worst]["ratio"], "max_quarter": worst, "min": min(v["ratio"] for v in out.values())}


def wholesale_rule(liquidity_lt: float) -> dict:
    """Долгосрочный спред книги оптового фондирования — цена недостающего фондирования клетки (рыночные займы и вклады
    по рыночной ставке): долгосрочный спред книги ликвидности плюс средняя по кварталам окна разность ставки срочных
    вкладов физлиц и доходности ликвидных активов (панель ставок листа калибровки), до 0,01 п.п."""
    rows = {(r["quarter"], r["series"]): float(r["rate"]) for r in evlib.read_csv(IN / "stage1/calib/nii/out/rates_panel.csv")
            if r["basis"] == PANEL_BASIS and r["series"] in (TERM_BOOK, LIQUIDITY_BOOK) and r["quarter"] in WINDOW}
    gap = {q: rows[(q, TERM_BOOK)] - rows[(q, LIQUIDITY_BOOK)] for q in WINDOW}
    premium = round(sum(gap.values()) / len(gap), 4)
    return {"term_minus_liquid_by_quarter": {q: round(v, 5) for q, v in gap.items()}, "premium": premium,
            "liquidity_lt_spread": liquidity_lt, "rule": round(liquidity_lt + premium, 5)}


def compute() -> dict:
    book = evlib.template()
    nii = book["nii"]
    sheet = yaml.safe_load((IN / "stage1/calib/nii/out/nii_book_proposal.yaml").read_text(encoding="utf-8"))
    cmp = evlib.Compare()
    # --- книги: шаблон = предложение листа
    whs = wholesale_rule(float(nii["books"][LIQUIDITY_BOOK]["spread"]["LT"]))
    for b, spec in sheet["nii"]["books"].items():
        want = {k: v for k, v in spec.items() if k != "fv_share"}
        want["name"] = RENAMED.get(b, want["name"])
        have = dict(nii["books"].get(b) or {})
        if b == WHOLESALE_BOOK:                                  # траектория спреда — правило книги: уровень сверяется ниже
            y_anchor, lt_from = book["meta"]["first_period"][:4], want["spread"]["LT_from"]
            cmp.eq("спред оптового фондирования года якоря — лист", have["spread"][y_anchor], want["spread"][y_anchor], 1e-12)
            cmp.eq("спред оптового фондирования: год выхода на LT — лист", have["spread"]["LT_from"], lt_from)
            cmp.eq("LT-спред оптового фондирования = LT-спред ликвидности + разность срочных вкладов и ликвидных активов окна",
                   have["spread"]["LT"], whs["rule"], 1e-9)
            have.pop("spread"), want.pop("spread")
        cmp.eq(f"nii.books.{b}", have, want)
    w_axis = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["paths"] == [f"nii.books.{WHOLESALE_BOOK}.spread.LT"])
    cmp.eq("ось LT-спреда оптового фондирования", [w_axis["low"], w_axis["high"]], WHOLESALE_AXIS)
    cmp.eq("nii.books: набор", list(nii["books"]), list(sheet["nii"]["books"]))
    cmp.true("у книг Т нет ключа доли кредитов по справедливой стоимости",
             not any("fv_share" in v for v in nii["books"].values()) and book["credit"]["fv_loans_factor"] == 0)
    cmp.eq("nii.transmission.target — суждение книги", nii["transmission"]["target"], TRANSMISSION_TARGET, 1e-12)
    cmp.eq("nii.transmission: прочие ключи — лист", {k: v for k, v in nii["transmission"].items() if k not in ("target", "level_world")},
           {k: v for k, v in evlib.get(sheet, "nii.transmission").items() if k != "target"})
    cmp.eq("цель передачи — середина оси свидетельств", TRANSMISSION_TARGET, sum(TRANSMISSION_AXIS) / 2, 1e-12)
    t_axis = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["paths"] == ["nii.transmission.target"])
    cmp.eq("ось цели передачи", [t_axis["low"], t_axis["high"]], TRANSMISSION_AXIS)
    for path in ("nii.sigma0_from", "nii.retail_current_share",
                 "nii.dia_rate", "checks.lt_spread_floor", "checks.nim_range", "checks.nim_path_joint",
                 "checks.transmission_pairs", "volumes.wholesale_to_funds", "volumes.liquid_min_share",
                 "volumes.securities_share_of_liquid", "volumes.other_assets_to_loans", "volumes.other_liabilities_to_loans",
                 "volumes.guidance_year", "volumes.lt_from"):
        cmp.eq(path, evlib.get(book, path), evlib.get(sheet, path))
    # --- якорь: ставки, остатки, проценты
    ab = {r["book"]: r for r in evlib.read_csv(IN / "stage1/ifrs/anchor_books.csv")}
    num = lambda b, col: float(ab[b][col])
    first = book["meta"]["first_period"]
    ref_world = nii["transmission"]["reference_world"]
    wrow = {(r["world"], r["period"]): r for r in evlib.read_csv(IN / "stage1/worlds/world_paths_quarterly.csv")}
    ref = {k: float(wrow[(ref_world, first)][f]) / 100 for k, f in REF_FIELD.items()}
    y0 = int(first[:4])
    near = {}
    for b, spec in nii["books"].items():
        sp = spec["spread"]
        if not isinstance(sp, dict) or str(y0) not in sp:
            continue
        beta = spec["beta"] if spec["side"] == "liability" else 1.0
        rate = num(b, "rate_2Q2026_act365_pct") / 100
        s0 = rate - beta * ref[spec["ref"]]
        mid = (sp[str(y0)] + evlib.year_value(sp, y0 + 2)) / 2
        near[b] = {"rate_anchor": round(rate, 5), "ref_first_quarter": round(ref[spec["ref"]], 5),
                   "rule": {str(y0): round(s0, 5), str(y0 + 1): round(mid, 5)}}
        cmp.eq(f"nii.books.{b}.spread.{y0} = ставка якоря − опора", sp[str(y0)], s0, 6e-6)
        cmp.eq(f"nii.books.{b}.spread.{y0 + 1} = середина", sp[str(y0 + 1)], mid, 6e-6)
    assets = [b for b, v in nii["books"].items() if v["side"] == "asset"]
    liabs = [b for b, v in nii["books"].items() if v["side"] == "liability"]
    interest_a = sum(num(b, "interest_2Q2026") for b in assets)
    interest_l = -sum(num(b, "interest_2Q2026") for b in liabs)
    other = num("brokerage_receivables", "interest_2Q2026") - LEASE_INTEREST_Q
    nii_id = interest_a - interest_l - DIA_Q + other
    cmp.eq("тождество процентов якоря", round(nii_id, 1), NII_ANCHOR_Q, 0.051)
    for b in nii["books"]:                                     # ставка якоря = проценты × 365/91 / средний остаток
        rate = abs(num(b, "interest_2Q2026")) * 365 / 91 / num(b, "avg_2Q2026")
        cmp.eq(f"ставка якоря {b}", round(rate, 3), round(num(b, "rate_2Q2026_act365_pct") / 100, 3), 2.1e-3)
    bal = {b: num(b, "bal_2026-06-30") for b in nii["books"]}
    funds = bal["retail_current"] + bal["retail_term"] + bal["corp_funds"]
    retail_avg = num("retail_current", "avg_2Q2026") + num("retail_term", "avg_2Q2026")
    key_rows = {r["period"]: r for r in evlib.read_csv(IN / "research/facts/cbr_key_rate_quarterly.csv")}
    anchors = {
        "c_ref": round(bal["retail_current"] / (bal["retail_current"] + bal["retail_term"]), 5),
        "key_ref": round(float(key_rows[book["meta"]["anchor_period"]]["key_avg_pct"]) / 100, 6),
        "wholesale_to_funds": round(bal["wholesale"] / funds, 5),
        "securities_share_of_liquid": round(bal["securities"] / (bal["securities"] + bal["liquidity"]), 5),
        "loans": round(sum(bal[b] for b in assets if not nii["books"][b].get("balancing")), 1),
        "funds": round(funds, 1),
        "dia_rate": round(DIA_Q * 365 / 91 / retail_avg, 5),
        "iea": round(sum(bal[b] for b in assets), 1),
    }
    cmp.eq("nii.dia_rate", nii["dia_rate"], round(anchors["dia_rate"], 4), 1e-9)
    lo, hi = nii["retail_current_share"]["bounds"]
    cmp.true("доля текущих счетов якоря внутри границ книги", lo <= anchors["c_ref"] <= hi)
    # --- суждение о марже — ключ цели ЧПМ: стационарная маржа мира уровня на составе баланса якоря
    tr = json.loads((IN / "stage1/calib/nii/out/transmission_out.json").read_text(encoding="utf-8"))
    rec = json.loads(RECORD.read_text(encoding="utf-8"))
    level_world, key = nii["transmission"]["level_world"], nii["nim_lt_target_mgmt"]
    margin = margin_rule()
    cmp.eq("nii.nim_lt_target_mgmt = средняя окна, приведённая к составу баланса якоря", key, round(margin["rule"], 3), 1e-9)
    cmp.eq("мир уровня = мир слоя «Рыночные ставки как есть»", level_world, book["joint"]["macro_neutral_world"])
    cmp.eq("мир-опора κ = мир уровней окна", book["credit"]["kappa_reference_world"], level_world)
    cmp.true("книга не несёт гейта стационарной маржи: ключ цели — само суждение", "nim_stationary" not in book["checks"])
    cmp.true("запись вывода: стационарная маржа мира уровня равна ключу цели",
             rec["frozen_check"]["nim_level_world"] == level_world and abs(rec["frozen_check"]["nim_stationary"] - key) <= 1e-9)
    axis = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["paths"] == ["nii.nim_lt_target_mgmt"])
    ends = rec["ends"]["margin_axis"]
    cmp.eq("ось уровня маржи — само суждение", [axis["low"], axis["high"]], NIM_AXIS_STATIONARY)
    cmp.true("запись вывода: на концах оси решатель держит стационарную маржу мира уровня",
             [ends["low"], ends["high"]] == NIM_AXIS_STATIONARY and all(abs(a - b) <= 1e-9 for a, b in zip(ends["stationary"], NIM_AXIS_STATIONARY)))
    cmp.eq("верх оси суждения = лучший квартал окна", NIM_AXIS_STATIONARY[1], round(margin["window_best_quarter"], 3), 1e-9)
    cmp.true("запись вывода: на оси передачи мир уровня неподвижен", rec["transmission"]["level_world_fixed"] is True)
    window = book["checks"]["window_backtest"]                   # поля окна фактов по марже — из входов листа
    quarters = list(margin["nim_by_quarter"].values())
    cmp.eq("checks.window_backtest.nim = наименьший и наибольший квартал окна", window["nim"], [round(min(quarters), 5), round(max(quarters), 5)])
    cmp.eq("checks.window_backtest.means.nim = средняя окна", window["means"]["nim"], round(margin["window_mean_mgmt"], 4), 1e-9)
    # --- порог гейта стоимости средств клиентов к ключевой ставке: наибольший квартал окна по панели ставок
    funds = funds_cost_to_key()
    cmp.eq("checks.funds_cost_to_key.max = наибольший квартал окна", book["checks"]["funds_cost_to_key"]["max"], round(funds["max"], 3), 1e-9)
    rev = next(a for a in book["valuation"]["reverse_dcf"]["axes"] if a["paths"] == ["nii.nim_lt_target_mgmt"])
    cmp.eq("строка обратного расчёта ЧПМ: диапазон = ось", rev["range"], [axis["low"], axis["high"]])
    # --- доли σ0 и φ: правило книги на записи вывода
    sp = rec["splits"]
    cmp.eq("nii.sigma0_split = запись вывода", nii["sigma0_split"], sp["sigma0_split"], 1e-12)
    cmp.eq("nii.phi_split = запись вывода", nii["phi_split"], sp["phi_split"], 1e-12)
    floor01 = lambda x: math.floor(x * 100 + 1e-9) / 100  # noqa: E731
    cmp.eq("доля φ = меньшее из доли по истории наклонов и предела гейта пола спреда", nii["phi_split"],
           min(floor01(sp["phi_by_history"]), floor01(sp["phi_limit"])), 1e-9)
    cmp.eq("доля по истории = сжатие истории листа к полному сжатию φ", sp["phi_by_history"],
           round(tr["history_phi_assets"] / sp["phi"], 4), 2e-4)
    for key_, ends_ in (("sigma0_split", sp["axis_sigma0"]), ("phi_split", sp["axis_phi"])):
        ax_ = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["paths"] == [f"nii.{key_}"])
        cmp.eq(f"ось доли nii.{key_} = запись вывода", [ax_["low"], ax_["high"]], ends_)
    cmp.true("гейт пола спреда проходит в центре книги (запись вывода)", sp["floor_headroom"][0] >= -1e-9)
    # --- ближний сдвиг ЧПМ
    path = {r["quarter"]: r for r in evlib.read_csv(IN / "stage1/calib/nii/out/nim_path.csv")}
    shift = book["regimes"]["near_nim_shift"]
    q_keys = sorted(k for k in shift if "Q" in k)
    # ключи кварталов выведены на ядре (модальная клетка с ограничением роста); пробный проход листа — справочно
    cmp.eq("regimes.near_nim_shift: набор квартальных ключей", q_keys, sorted(path)[:len(q_keys)])
    cmp.true("ближний сдвиг года якоря: путь книги ниже механики книг", all(shift[k] < 0 for k in q_keys if k.startswith(book["meta"]["first_period"][:4])))
    for y in sorted({k[:4] for k in q_keys}):
        qs = [shift[k] for k in q_keys if k.startswith(y)]
        cmp.eq(f"regimes.near_nim_shift.{y} = среднее кварталов", shift[y], sum(qs) / len(qs), 1e-9)
    cmp.true("ближний сдвиг: с 2030 года — 0", shift["LT"] == 0.0 and shift["LT_from"] == 2030 and max(q_keys) == "2029Q4")
    ax = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["paths"][0].startswith("regimes.near_nim_shift"))
    cmp.eq("ось скорости схода: ключи 2027–2029", sorted(p.rsplit(".", 1)[1] for p in ax["paths"]),
           sorted(k for k in shift if k[:4] in ("2027", "2028", "2029")))
    first8 = [float(path[k]["nim_mgmt_B"]) for k in sorted(path)[:8]]
    gate = book["checks"]["nim_path_joint"]
    # --- полы спредов: правило листа
    floors = {}
    for b, r in tr["floor_rule"].items():
        rule = max(0.0, math.floor(min(r["cor_mean"], r["spread_lag_min"]) * 200 + 1e-9) / 200)
        floors[b] = {"cor_mean": round(r["cor_mean"], 4), "spread_lag_min": round(r["spread_lag_min"], 4), "rule": rule}
        cmp.eq(f"checks.lt_spread_floor.{b} = правило листа", book["checks"]["lt_spread_floor"][b], rule, 1e-9)
    lt = sp["lt_spread"]
    worst = min((lt[b][w] - book["checks"]["lt_spread_floor"][b], b, w) for b in lt for w in lt[b])
    cmp.true("гейт пола спреда: эффективные спреды записи не ниже полов книги во всех мирах", worst[0] >= -1e-9)
    cmp.eq("nii.sigma0_from = год якоря + 1", nii["sigma0_from"], int(book["meta"]["anchor_period"][:4]) + 1)
    pairs = rec["transmission"]["rows"]["centre"]["pairs"]
    lo, hi = book["checks"]["transmission_pairs"]
    cmp.true("парные передачи центра книги (запись вывода) внутри коридора", all(lo <= v <= hi for v in pairs.values()))
    cmp.eq("ось цели передачи = запись вывода", TRANSMISSION_AXIS, rec["transmission"]["axis"])
    cmp.true("решатель решает цель передачи в центре и на концах оси", all(r["solved"] for r in rec["transmission"]["rows"].values()))
    return {
        "anchor": anchors,
        "nii_identity": {"interest_assets": round(interest_a, 1), "interest_liabilities": round(interest_l, 1), "dia": DIA_Q,
                         "other_interest_net": round(other, 1), "nii": round(nii_id, 1), "nii_fact": NII_ANCHOR_Q},
        "near_spreads": near,
        "nim_target": {"rule": margin, "world": level_world, "key_book": key,
                       "stationary_on_engine": rec["frozen_check"]["nim_stationary"],
                       "stationary_by_world": rec["level"]["stationary_by_world"], "reference_world": rec["level"]["reference_world"],
                       "reference_level_on_engine": rec["level"]["reference_level"], "sigma0_assets": rec["level"]["sigma0"],
                       "axis": [axis["low"], axis["high"]], "reference_level_at_axis_ends": ends["reference_level"],
                       "window_nim": window["nim"], "window_mean_nim": window["means"]["nim"], "derived_on_engine": False},
        "wholesale_spread": {**whs, "book": dict(nii["books"][WHOLESALE_BOOK]["spread"]), "axis": [w_axis["low"], w_axis["high"]]},
        "funds_cost_to_key": {**funds, "book_max": book["checks"]["funds_cost_to_key"]["max"]},
        "transmission": {"target": nii["transmission"]["target"], "axis": [t_axis["low"], t_axis["high"]],
                         "level_world": level_world, "level_world_fixed_on_axis": rec["transmission"]["level_world_fixed"],
                         "phi": sp["phi"], "pairs": pairs, "phi_at_axis_ends": [rec["transmission"]["rows"]["low"]["phi"],
                                                                                 rec["transmission"]["rows"]["high"]["phi"]]},
        "splits": {"sigma0_split": nii["sigma0_split"], "sigma0_limit": sp["sigma0_limit"], "phi_split": nii["phi_split"],
                   "phi_by_history": sp["phi_by_history"], "phi_limit": sp["phi_limit"], "phi_limit_at": sp["phi_limit_at"],
                   "history_compression": round(tr["history_phi_assets"], 4)},
        "transmission_sheet": {"target": tr["center"]["t_real"], "phi": round(tr["center"]["phi"], 4),
                               "sigma0_assets": round(tr["center"]["sigma0"], 5),
                               "pairs": {k: round(v, 4) for k, v in tr["center"]["pairs"].items()},
                               "bridge_used_by_sheet": tr["bridge_nim"]},
        "near_nim_shift": {"trial_pass_first_quarters_mgmt": [round(v, 4) for v in first8], "gate_tolerance": gate["tolerance"],
                           "trial_pass_keys": {k: round(float(path[k]["near_B"]), 5) for k in q_keys},
                           "book_keys": {k: shift[k] for k in q_keys},
                           "shift_removed_at_2030Q1": round(-shift[max(q_keys)], 5), "derived_on_engine": True},
        "lt_spread_floor": floors,
        "floor_headroom_min": {"gap": round(worst[0], 5), "book": worst[1], "world": worst[2]},
        "book_mismatches": cmp.mismatches,
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    res = compute()
    evlib.write_json(OUT / "nii_book_out.json", res)
    print("якорь:", res["anchor"])
    print("тождество процентов:", res["nii_identity"])
    print("цель ЧПМ:", res["nim_target"])
    print("спред оптового фондирования:", res["wholesale_spread"])
    print("стоимость средств клиентов к ключевой:", res["funds_cost_to_key"])
    print("передача и доли:", res["transmission"], res["splits"])
    print("ближний сдвиг:", res["near_nim_shift"])
    print("запас гейта пола спреда:", res["floor_headroom_min"])
    print("расхождения с шаблоном:", res["book_mismatches"] or "нет")
    return 1 if res["book_mismatches"] else 0


if __name__ == "__main__":
    sys.exit(main())
