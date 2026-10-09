# -*- coding: utf-8 -*-
"""Независимая контрольная модель панели — ГОДОВАЯ, с квартальным проходом капитала (docs/MODEL.md §17).

Написана только по тексту docs/MODEL.md, книге (data/assumptions/) и фактам (data/facts/);
каталог ядра не импортируется и не читается (tests/test_control_independence.py). Шаг —
год: неполный год якоря — один период (доля года = оставшиеся кварталы / 4), далее годы до
года last_period, терминал М§7 в годовой форме. Две ветви — по ключам книги: без квартального
календаря дивидендов и без ограничения роста — годовая ветвь образца (решение раз в год); с ними —
годовые строки ОПУ и квартальный проход капитала внутри года (остатки кредитных книг, RWA, нормативы,
требование с глиссадой, решения о дивиденде, доля прироста и навёрстывание — по кварталам). Что
считается иначе, чем в ядре, и почему совпадение ожидается только в допусках — docs/CONTROL-MODEL.md.

Чисел книги и фактов в коде нет: только имена ключей и структурные константы (кварталов в
году, дней в году по act/365, млрд → млн, технические допуски итераций).

Запуск:
    python -B tests/independent_model.py                      сводка на машинной книге и фактах
    python -B tests/independent_model.py --json out.json      то же + полный результат в JSON
    python -B tests/independent_model.py --gates              то же + числа гейтов знака, печатаемая маржа и уровни
                                                              после фазы роста (М§14.2)
    python -B tests/independent_model.py --draft --worlds-lt N=<доля>,H=<доля> [--facts DIR]
        шаблон книги (assumptions_template.yaml) + миры из worlds_source.json и надстройка
        worlds_bank.json (узел LT кривой миров N и H — правило сборки семейства, передаётся явно;
        M — правило рецепта)
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import sys
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BOOK_DIR = ROOT / "data" / "assumptions"
BOOK_YAML = BOOK_DIR / "assumptions.yaml"
DRAFT_YAML = BOOK_DIR / "assumptions.draft.yaml"
TEMPLATE_YAML = BOOK_DIR / "assumptions_template.yaml"
WORLDS_SOURCE = BOOK_DIR / "worlds_source.json"
WORLDS_BANK = BOOK_DIR / "worlds_bank.json"
FACTS_DIR = ROOT / "data" / "facts"

LAYERS = ("analytical", "market_implied", "macro_neutral")
LAYER_OWN, LAYER_MARKET = LAYERS[0], LAYERS[-1]     # слои «свой взгляд» и «рыночные ставки как есть» (М§9)
# Миры из текста методики: реализованная передача — разность M и N (М§4.5); κ-добавка к CoR без ключа
# книги — относительно мира N и только вверх, с ключом credit.kappa_reference_world — относительно
# названного им мира-опоры, с любым знаком (М§4.6).
W_LOW = "N"
W_MKT = "M"
SCOPE_MARKET = "market_layer"       # checks.cir_lt.scope: цель C/I сверяется со слоем «рыночные ставки как есть»
SCOPE_MODAL = "modal_cell"          # явное имя умолчания: модальная клетка, как без ключа scope
FADE_SYMMETRIC = "symmetric"        # valuation.terminal.fade_mode справочного варианта таблиц книги (М§7)
MIX_MODAL, MIX_POINT = "modal", "point"     # смеси узла уровней сверх слоёв: модальная клетка и смесь точки
R_NORM = "norm"             # режим, к которому относится цель A-N2 и кредитная маржа стационара (М§4.5)
R_CRISIS = "crisis"         # режим с годом шока, разовым убытком и отменой выплаты (М§3.2, §5.3)
QY = 4                      # кварталов в году
DAYS_BASE = 365.0           # act/365 (М§0.3)
LOANS_SIDE = "asset"
RETAIL_CURRENT = "retail_current"   # книги ФЛ, доля которых — функция ключевой (М§4.3)
RETAIL_TERM = "retail_term"
CORP_LOANS = "corp_loans"           # таблица состава книг образца (ветвь его фактов, М§17)
SECURITIES = "securities"
LIQUIDITY = "liquidity"
WHOLESALE = "wholesale"
CORP_FUNDS = "corp_funds"
FIT_ITER = 60               # итераций фиксированной точки балансирующих статей, деления отрезка и года
FIT_TOL = 1e-11
PLAN_TOL = 1e-9             # сходимость квартального плана года (доли остатка книги; млрд ₽ дивиденда)
FREQ_QUARTERLY = "quarterly"        # dividends.calendar.frequency (М§5.1)
ORDER_DIV_FIRST = "dividend_first"  # capital.growth_constraint.order (М§4.13)
ORDER_GROWTH_FIRST = "growth_first"
BASIS_ISSUED = "issued"             # valuation.shares_basis (М§8.4)
HIST_EXACT, HIST_CAP, HIST_NONE = "exact", "cap", "none"   # dividends.policy.history_test (М§5.2)
LINK_BASES = ("loans", "funds", "iea")                      # volumes.link_base (М§4.7)
LOAN_SECTORS = ("corporate", "mortgage", "retail_other")    # ключи словаря премии роста кредитов (М§4.3)
FUND_SEGMENTS = ("retail", "corporate")                     # ключи словаря премии средств клиентов


class ControlInputError(ValueError):
    """Книга или факты не дают того, что нужно контрольной модели (громкий отказ)."""


class ControlUnsupported(ValueError):
    """Ветка методики, которую контрольная модель не поддерживает. На настоящей книге — провал теста, не
    пропуск (М§17): отказ остаётся только у модулей, выключенных самой методикой (М§0.6)."""


# ============================================================================ ввод: книга

def _c_read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def c_book_machine(path: Path | None = None) -> dict:
    """Машинная книга data/assumptions/assumptions.yaml (миры и надстройка уже внутри)."""
    p = Path(path) if path else BOOK_YAML
    if not p.exists():
        raise ControlInputError(f"нет машинной книги {p.name}")
    return _c_read_yaml(p)


def c_book_from_draft(draft: Path | None = None, *, worlds_source: Path | None = None,
                    overlay: Path | None = None, curve_lt: dict | None = None) -> dict:
    """Шаблон книги (по умолчанию assumptions_template.yaml, иначе черновик) + блоки worlds.<W> и
    worlds_bank.<W> по таблице М§3.1 — независимая сборка машинной книги.

    Узел LT бескупонной кривой: M — правило рецепта (ОФЗ 10 лет последнего полугодия, до 0,1
    п.п.), N и H — правило сборки семейства (передаётся явно, в коде чисел нет). Строки-метки
    шаблона — комментарии YAML, поэтому шаблон читается как книга без миров.
    """
    src_book = Path(draft) if draft else (TEMPLATE_YAML if TEMPLATE_YAML.exists() else DRAFT_YAML)
    book = _c_read_yaml(src_book)
    src = json.loads(Path(worlds_source or WORLDS_SOURCE).read_text(encoding="utf-8"))
    ovl = json.loads(Path(overlay or WORLDS_BANK).read_text(encoding="utf-8"))
    curve_lt = dict(curve_lt or {})
    fields = {"key_rate": "key_avg", "cpi": "cpi_yoy_avg", "wage_growth": "nominal_wage_yoy",
              "ofz_1y": "ofz_1y", "ofz_3y": "ofz_3y", "ofz_5y": "ofz_5y", "ofz_10y": "ofz_10y",
              "real_key": "real_key_fwd12m"}
    pct = 100.0
    for w in book["worlds"]["ids"]:
        rows = [r for r in src["rows"] if r["world"] == w]
        blk = {"name": w}
        for key, col in fields.items():
            blk[key] = {r["period"]: r[col] / pct for r in rows}
        curve = {str(k): v / pct for k, v in src["fair_zero_curve_today"][w].items()}
        if w not in curve_lt:
            if w != W_MKT:
                raise ControlInputError(f"узел LT кривой мира {w}: передайте --worlds-lt")
            curve_lt[w] = round(rows[-1]["ofz_10y"], 1) / pct
        curve["LT"] = float(curve_lt[w])
        blk["zero_curve"] = curve
        blk["lt_inflation"] = src["lt_inflation"][w] / pct
        book["worlds"][w] = blk
    book["worlds_bank"] = {w: ovl["worlds"][w] for w in book["worlds"]["ids"]}
    return book


def c_bget(book: dict, dotted: str):
    """Значение книги по точечному пути; нет ключа — громкий отказ."""
    cur = book
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, dict) and part.isdigit() and int(part) in cur:
            cur = cur[int(part)]
        else:
            raise ControlInputError(f"в книге нет ключа {dotted}")
    return cur


def c_bnum(book: dict, dotted: str) -> float:
    v = c_bget(book, dotted)
    if v is None or isinstance(v, (dict, list, str, bool)):
        raise ControlInputError(f"ключ книги {dotted} — не число: {v!r}")
    return float(v)


def c_bopt(book: dict, dotted: str, default=None):
    """Необязательный (поведенческий) ключ книги: нет ключа или null — умолчание (М§0.6: «ключа нет»)."""
    cur = book
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return default if cur is None else cur


def c_is_quarterly(book: dict) -> bool:
    """Квартальный календарь дивидендов (М§5.7); без ключа frequency — годовой режим образца."""
    return c_bopt(book, "dividends.calendar.frequency") == FREQ_QUARTERLY


def c_growth_rule(book: dict):
    """Параметры ограничения роста капиталом (М§4.13) или None: объекта нет либо enabled: false."""
    gc = c_bopt(book, "capital.growth_constraint")
    if not isinstance(gc, dict) or not gc.get("enabled"):
        return None
    for key in ("order", "min_growth_scale", "lookahead_quarters", "glide_pp_per_quarter", "catch_up_rate", "tol"):
        if gc.get(key) is None:
            raise ControlInputError(f"capital.growth_constraint.{key}: нет поля при enabled: true (М§4.13)")
    if gc["order"] not in (ORDER_DIV_FIRST, ORDER_GROWTH_FIRST):
        raise ControlInputError("capital.growth_constraint.order — не dividend_first и не growth_first")
    lam_min, cu = float(gc["min_growth_scale"]), float(gc["catch_up_rate"])
    if not (0.0 <= lam_min <= 1.0 and 0.0 <= cu <= 1.0 and float(gc["glide_pp_per_quarter"]) >= 0.0
            and float(gc["tol"]) > 0.0 and int(gc["lookahead_quarters"]) >= 0):
        raise ControlInputError("capital.growth_constraint: поле вне границ (М§4.13)")
    if not c_is_quarterly(book):
        raise ControlInputError("ограничение роста требует квартального календаря дивидендов (М§4.13)")
    if int(c_bnum(book, "volumes.guidance_year")) >= c_per_parse(c_bget(book, "meta.first_period"))[0]:
        raise ControlInputError("ограничение роста при годе гайденса внутри сетки (М§4.3)")
    return {"order": gc["order"], "lam_min": lam_min, "ahead": int(gc["lookahead_quarters"]),
            "glide": float(gc["glide_pp_per_quarter"]), "catch_up": cu, "tol": float(gc["tol"])}


# ============================================================================ ввод: факты

def c_facts_bundle(root: Path | None = None) -> dict:
    """Все data/facts/*.json как словари {имя файла: содержимое}."""
    d = Path(root) if root else FACTS_DIR
    files = sorted(d.glob("*.json")) if d.exists() else []
    if not files:
        raise ControlInputError(f"нет фактов в {d}")
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in files}


def _c_dig(tree, dotted: str):
    cur = tree
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise ControlInputError(f"нет узла {dotted}")
    return cur


def c_fval(facts: dict, file: str, dotted: str, *, null_ok: bool = False):
    """Значение узла факта {v, src|calc}; null — отказ (null ≠ 0), если не разрешено явно."""
    if file not in facts:
        raise ControlInputError(f"нет файла фактов {file}.json")
    node = _c_dig(facts[file], dotted)
    val = node.get("v") if isinstance(node, dict) and "v" in node else node
    if val is None:
        if null_ok:
            return None
        raise ControlInputError(f"null в узле {file}:{dotted}")
    return val


def c_fnum(facts: dict, file: str, dotted: str) -> float:
    return float(c_fval(facts, file, dotted))


def _c_quarter_rows(pnl: dict) -> dict[str, dict]:
    """Кварталы pnl_quarterly.json в виде {период: {строка: узел}} (допускаются формы
    «словарь периодов» и «список записей с полем period»)."""
    for key in ("quarters", "periods", "rows", "data"):
        if key in pnl:
            body = pnl[key]
            break
    else:
        body = {k: v for k, v in pnl.items() if isinstance(k, str) and "Q" in k and k[:4].isdigit()}
    if isinstance(body, list):
        return {str(r["period"]): r for r in body}
    return {str(k): v for k, v in body.items()}


def _c_nodeval(node):
    if isinstance(node, dict):
        return node.get("v")
    return node


# ============================================================================ время

def c_per_parse(p: str) -> tuple[int, int]:
    """«2026Q3» → (2026, 3)."""
    y, q = str(p).upper().split("Q")
    return int(y), int(q)


def c_q_first_day(y: int, q: int) -> dt.date:
    return dt.date(y, 3 * (q - 1) + 1, 1)


def c_q_last_day(y: int, q: int) -> dt.date:
    ny, nq = (y + 1, 1) if q == QY else (y, q + 1)
    return c_q_first_day(ny, nq) - dt.timedelta(days=1)


def c_q_len(y: int, q: int) -> int:
    return (c_q_last_day(y, q) - c_q_first_day(y, q)).days + 1


def _c_as_date(x) -> dt.date:
    if isinstance(x, dt.date):
        return x
    return dt.date.fromisoformat(str(x))


def c_annual_periods(book: dict) -> list[dict]:
    """Периоды годовой модели: остаток года якоря (если он есть) и полные годы до last_period."""
    y0, qa = c_per_parse(c_bget(book, "meta.anchor_period"))
    yl, ql = c_per_parse(c_bget(book, "meta.last_period"))
    if ql != QY:
        raise ControlUnsupported("last_period должен кончать год (терминал — с года после него)")
    fy, fq = c_per_parse(c_bget(book, "meta.first_period"))
    nxt = (y0 + 1, 1) if qa == QY else (y0, qa + 1)
    if (fy, fq) != nxt:
        raise ControlInputError("first_period — не квартал после якоря")
    out = []
    if qa < QY:
        out.append({"year": y0, "quarters": tuple(range(qa + 1, QY + 1)), "stub": True})
    for y in range(y0 + 1, yl + 1):
        out.append({"year": y, "quarters": tuple(range(1, QY + 1)), "stub": False})
    for p in out:
        y = p["year"]
        p["n"] = len(p["quarters"])
        p["days"] = sum(c_q_len(y, q) for q in p["quarters"])
        p["start"] = c_q_first_day(y, p["quarters"][0])
        p["end"] = c_q_last_day(y, p["quarters"][-1])
        p["label"] = str(y)
    return out


# ============================================================================ траектории (М§0.4)

def _c_time_keys(traj: dict) -> dict[str, tuple[int, int, int]]:
    """Ключи времени траектории → (год, первый квартал, последний квартал)."""
    out = {}
    for k in traj:
        s = str(k)
        if s in ("LT", "LT_from"):
            continue
        if len(s) == 4 and s.isdigit():
            out[s] = (int(s), 1, QY)
        elif "Q" in s:
            y, q = c_per_parse(s)
            out[s] = (y, q, q)
        elif "H" in s:
            y, h = s.split("H")
            out[s] = (int(y), 2 * int(h) - 1, 2 * int(h))
        else:
            raise ControlInputError(f"ключ траектории не разбирается: {s}")
    return out


def c_traj_at(traj, y: int, q: int) -> float:
    """Значение траектории книги в квартале (y, q) по правилу М§0.4."""
    if traj is None:
        raise ControlInputError("null в траектории")
    if isinstance(traj, (int, float)) and not isinstance(traj, bool):
        return float(traj)
    if not isinstance(traj, dict):
        raise ControlInputError(f"траектория не словарь: {traj!r}")
    t = {str(k): v for k, v in traj.items()}
    for key in (f"{y}Q{q}", f"{y}H{1 if q <= 2 else 2}", str(y)):
        if key in t:
            return float(t[key])
    tk = _c_time_keys(t)
    years = sorted(v[0] for k, v in tk.items() if len(k) == 4)
    lt = t.get("LT")
    if not tk:
        if lt is None:
            raise ControlInputError("траектория без ключей времени и без LT")
        return float(lt)
    if years and years[0] < y < years[-1]:
        lo = max(v for v in years if v < y)
        hi = min(v for v in years if v > y)
        a, b = float(t[str(lo)]), float(t[str(hi)])
        return a + (b - a) * (y - lo) / (hi - lo)
    order = sorted(tk.items(), key=lambda kv: (kv[1][0], kv[1][1]))
    first_key, (fy, fq, _) = order[0]
    if (y, q) < (fy, fq):
        return float(t[first_key])                               # правило 6
    if years and y > years[-1]:
        last = float(t[str(years[-1])])
        if lt is None:
            return last
        lt_from = t.get("LT_from")
        if lt_from is None or y >= int(lt_from):
            return float(lt)
        span = int(lt_from) - years[-1]
        return last + (float(lt) - last) * (y - years[-1]) / span
    # после последнего ключа полугодия/квартала (миры) — последнее значение
    last_key = order[-1][0]
    if lt is not None and not years:
        return float(lt)
    return float(t[last_key])


def c_traj_mean(traj, y: int, quarters) -> float:
    """Среднее траектории по кварталам периода (год или остаток года якоря)."""
    return sum(c_traj_at(traj, y, q) for q in quarters) / len(quarters)


def c_spread_at(ctx: dict, b: str, y: int, q: int) -> float:
    """Спред книги в квартале: s_b(q) = путь + σ_b × [lt_shift] × [Y(q) ≥ nii.sigma0_from] (М§4.4),
    σ_b = +σ0_A у активов и −σ0_L у пассивов (М§4.5).

    Сдвиг прибавляется к значению пути во всех кварталах с года sigma0_from, а не к ключу LT:
    ближний участок (до sigma0_from) держит калибровку к ставкам якоря."""
    sp = ctx["B"]["nii"]["books"][b]
    s = c_traj_at(sp["spread"], y, q)
    if sp.get("lt_shift") and y >= ctx["sigma0_from"]:
        s += ctx["tr"]["sigma0"] if sp["side"] == LOANS_SIDE else -ctx["tr"]["sigma0_liab"]
    return s


# ============================================================================ кривая и дисконт (М§0.5)

def _c_curve_nodes(curve: dict) -> tuple[list[tuple[float, float]], float]:
    nodes = sorted((float(k), float(v)) for k, v in curve.items() if str(k) != "LT")
    return nodes, float(curve["LT"])


def c_zero_at(curve: dict, t: float) -> float:
    """Бескупонная ставка мира на срок t (годовое начисление)."""
    nodes, lt = _c_curve_nodes(curve)
    if t <= nodes[0][0]:
        return nodes[0][1]
    for (t1, z1), (t2, z2) in zip(nodes, nodes[1:]):
        if t <= t2:
            return z1 + (z2 - z1) * (t - t1) / (t2 - t1)
    tn, zn = nodes[-1]
    return ((1.0 + zn) ** tn * (1.0 + lt) ** (t - tn)) ** (1.0 / t) - 1.0


def c_df_world(curve: dict, add: float, t: float) -> float:
    """DF_W(t) = (1 + z(t) + β_E·ERP)^(−t)."""
    if t == 0.0:
        return 1.0
    return (1.0 + c_zero_at(curve, t) + add) ** (-t)


class CDisc:
    """Дисконт от даты оценки с перекатом по форвардам: DF_v(τ) = DF(Δ + τ) / DF(Δ)."""

    def __init__(self, curve: dict, add: float, shift: float):
        self.curve, self.add, self.shift = curve, add, shift
        self.base = c_df_world(curve, add, shift)

    def __call__(self, tau: float) -> float:
        return c_df_world(self.curve, self.add, self.shift + tau) / self.base


# ============================================================================ якорь из фактов

def _c_sum_nodes(facts: dict, file: str, base: str, parts: list[str], notes: list) -> float:
    """Сумма узлов; null-узел — «отдельно не раскрыт, входит в соседний» (записывается в notes)."""
    total = 0.0
    for part in parts:
        v = c_fval(facts, file, f"{base}.{part}", null_ok=True)
        if v is None:
            notes.append(f"{file}:{base}.{part} = null (не раскрыто отдельно) — не суммируется")
            continue
        total += float(v)
    return total


def _c_book_rate(facts: dict, b: str) -> float:
    nb = facts.get("nii_books")
    if nb is None:
        raise ControlInputError("нет файла фактов nii_books.json")
    for root in (nb.get("books", {}), nb):
        if isinstance(root, dict) and b in root:
            return float(c_fval({"x": root}, "x", f"{b}.rate_anchor"))
    raise ControlInputError(f"нет ставки якоря книги {b} (nii_books.json)")


def _c_nb_node(facts: dict, name: str) -> float:
    nb = facts["nii_books"]
    for root in (nb, nb.get("anchor", {}), nb.get("totals", {})):
        if isinstance(root, dict) and name in root:
            return float(c_fval({"x": root}, "x", name))
    raise ControlInputError(f"нет узла nii_books.{name}")


PNL_LINES = ("nii", "fees_net", "llp_debt_fa", "insurance_net", "noncore_net", "opex", "pbt",
             "tax", "ni", "ni_shareholders", "misc_net")


def c_anchor_state(book: dict, facts: dict) -> dict:
    """Стартовое состояние якоря (М§4.1, прил. B) в единицах модели, с источником — фактами."""
    notes: list[str] = []
    bal = "balance"

    def c_lg(k):
        return c_fnum(facts, bal, f"loans_ac_gross.{k}")

    books = c_bget(book, "nii.books")
    for role in (SECURITIES, LIQUIDITY, WHOLESALE, RETAIL_CURRENT, RETAIL_TERM):
        if role not in books:
            raise ControlInputError(f"в nii.books нет книги роли {role} (М§4.1)")
    direct = isinstance(facts.get(bal, {}).get("books"), dict)
    if direct:
        # остатки якоря — прямыми узлами balance.books.<b> при любом составе книг (М§4.1 п. 2)
        E0 = {b: c_fnum(facts, bal, f"books.{b}") for b in books}
        fv_loans = None
        if any("fv_share" in sp for sp in books.values()):
            raise ControlInputError("fv_share у книги с остатками прямыми узлами: формулы вывода нет (М§4.1 п. 6)")
    else:
        # таблица состава книг образца — ветвь для его фактов (М§17)
        fv_loans = c_fnum(facts, bal, "loans_fvtpl")
        E0 = {
            CORP_LOANS: c_lg("commercial") + c_lg("project") + fv_loans,
            "mortgage": c_lg("mortgage_market"),
            "mortgage_sub": c_lg("mortgage_subsidized"),
            "retail_loans": c_lg("consumer") + c_lg("cards") + c_lg("auto"),
            SECURITIES: _c_sum_nodes(facts, bal, "securities",
                                   ["fvoci_debt", "fvoci_repo", "ac", "ac_repo", "fvtpl_bonds"], notes),
            LIQUIDITY: _c_sum_nodes(facts, bal, "liquidity",
                                  ["cash", "cbr", "due_from_banks", "reverse_repo"], notes),
            RETAIL_CURRENT: c_fnum(facts, bal, "funds.retail_current"),
            RETAIL_TERM: c_fnum(facts, bal, "funds.retail_term"),
            CORP_FUNDS: c_fnum(facts, bal, "funds.corp_current") + c_fnum(facts, bal, "funds.corp_term"),
            WHOLESALE: _c_sum_nodes(facts, bal, "wholesale",
                                  ["banks", "issued_debt", "subordinated", "repo_cbr"], notes),
        }
        for b in books:
            if b not in E0:
                raise ControlInputError(f"книга {b}: нет узла balance.books.{b}, а таблица состава книг "
                                        f"образца её не знает (М§4.1 п. 2, прил. B)")
    A = {"E0": E0, "notes": notes, "fv_loans": fv_loans, "direct_books": direct}
    A["rate0"] = {b: _c_book_rate(facts, b) for b in books}
    A["AL"] = abs(c_fnum(facts, bal, "allowance_ac"))
    A["OA"] = c_fnum(facts, bal, "other_assets")
    A["OL"] = c_fnum(facts, bal, "other_liabilities")
    A["DP"] = c_fnum(facts, bal, "dividends_payable")
    A["DP_year"] = _c_nodeval(facts[bal].get("dividends_payable_year"))          # признак годового режима (М§5.4)
    A["DP_declared"] = [{"period": str(_c_nodeval(it["period"])), "amount": float(_c_nodeval(it["amount"]))}
                        for it in (facts[bal].get("dividends_payable_declared") or [])]
    oaf = facts[bal].get("other_assets_fixed")
    A["OA_fixed_fact"] = None if oaf is None else _c_nodeval(oaf)
    A["history"] = {str(per): {k: _c_nodeval(v) for k, v in rec.items()}
                    for per, rec in (facts[bal].get("history") or {}).items() if isinstance(rec, dict)}
    A["BV"] = c_fnum(facts, bal, "equity.bv_common")
    A["AT1"] = c_fnum(facts, bal, "equity.at1")
    A["NCI"] = c_fnum(facts, bal, "equity.nci")
    A["prev_corp"] = c_fnum(facts, bal, "prev_year_end.loans_corporate")
    A["prev_retail"] = c_fnum(facts, bal, "prev_year_end.loans_retail")
    A["fvoci_debt"] = (c_fnum(facts, bal, "securities.fvoci_debt")
                       + (c_fval(facts, bal, "securities.fvoci_repo", null_ok=True) or 0.0))
    A["fvtpl_bonds"] = c_fval(facts, bal, "securities.fvtpl_bonds", null_ok=True)
    # доля текущих счетов якоря: узел факта, а при null — из остатков книг средств физлиц (прил. B)
    share0 = _c_nb_opt(facts, "current_share_anchor")
    A["current_share"] = (float(share0) if share0 is not None
                          else E0[RETAIL_CURRENT] / (E0[RETAIL_CURRENT] + E0[RETAIL_TERM]))
    A["key_ref"] = _c_nb_node(facts, "key_avg_anchor_q")
    cap = "capital"
    A["cpn_annual"] = c_fnum(facts, cap, "at1.coupon_annual")
    A["cpn_quarter"] = int(c_fnum(facts, cap, "at1.coupon_quarter"))
    A["R0"] = c_fnum(facts, cap, "fvoci_reserve")
    A["curve0"] = {str(k): c_fnum(facts, cap, f"ofz_curve_anchor.{k}")
                   for k in _c_dig(facts[cap], "ofz_curve_anchor") if str(k)[:1].isdigit()}
    A["n20_fact"] = c_fnum(facts, cap, "n20_0.value")
    A["n11_fact"] = c_fnum(facts, cap, "n1_1_bank.value")
    A["rwa_basel"] = c_fnum(facts, cap, "basel.rwa")
    A["group_cet1"] = _c_nodeval(facts[cap].get("basel", {}).get("cet1"))
    A["base_capital"] = _c_nodeval(facts[cap].get("bank_base_capital"))
    sh = "shares"
    A["N_iss"] = c_fnum(facts, sh, "issued_total")
    A["N_out"] = c_fnum(facts, sh, "outstanding_total")
    A["N_div"] = c_divisor(book, facts, A["N_iss"], A["N_out"])
    A["bridge"] = {x: (str(c_fval(facts, "bridge_mgmt_ifrs", f"{x}.method")),
                       float(c_fval(facts, "bridge_mgmt_ifrs", f"{x}.value"))) for x in ("cor", "nim")}
    if isinstance(facts.get("bridge_mgmt_ifrs", {}).get("cir"), dict):
        # мост C/I нужен только уровням после фазы роста (ключи checks.window_backtest и checks.cir_lt)
        A["bridge"]["cir"] = (str(c_fval(facts, "bridge_mgmt_ifrs", "cir.method")),
                              float(c_fval(facts, "bridge_mgmt_ifrs", "cir.value")))
    rows = _c_quarter_rows(facts["pnl_quarterly"])
    A["pnl"] = {per: {line: _c_nodeval(rec[line]) for line in PNL_LINES if line in rec}
                for per, rec in rows.items()}
    dv = facts.get("dividends", {})
    A["div_history"] = dv.get("history", [])
    A["register"] = dv.get("register_seed", [])
    A["div_years"] = dv.get("years") or {}
    A["facts_date"] = _c_as_date(c_bget(book, "meta.facts_date"))
    A["anchor"] = c_per_parse(c_bget(book, "meta.anchor_period"))
    return A


def c_divisor(book: dict, facts: dict, n_iss: float, n_out: float) -> float:
    """Делитель «на акцию» N_div (М§8.4): база — акции в обращении (без ключа) или размещённые за вычетом
    экономически собственных; множитель (1 + share_count_adj) — только при ключе."""
    basis = c_bopt(book, "valuation.shares_basis")
    n_div = n_out
    if basis == BASIS_ISSUED:
        if len(c_bget(book, "meta.company.tickers")) != 1:
            raise ControlInputError("valuation.shares_basis: issued при двух и более тикерах (М§8.4)")
        node = facts.get("shares", {}).get("economic_treasury")
        n_div = n_iss - float(_c_nodeval(node) or 0.0)
    elif basis not in (None, "outstanding"):
        raise ControlInputError(f"valuation.shares_basis: {basis!r}")
    adj = c_bopt(book, "valuation.share_count_adj")
    if adj is not None:
        if not -0.5 < float(adj) < 0.5:
            raise ControlInputError("valuation.share_count_adj вне (−0,5; 0,5) (М§8.4)")
        n_div = n_div * (1.0 + float(adj))
    if n_div <= 0.0:
        raise ControlInputError("делитель N_div не положителен (М§8.4)")
    return n_div


def _c_nb_opt(facts: dict, name: str):
    """Узел nii_books.<name>, допускающий null (None — «считается из книг», прил. B)."""
    nb = facts.get("nii_books") or {}
    for root in (nb, nb.get("anchor", {}), nb.get("totals", {})):
        if isinstance(root, dict) and name in root:
            return _c_nodeval(root[name])
    return None


def c_fv_books(books: dict) -> list[str]:
    """Кредитные книги с долей кредитов по справедливой стоимости (ключ fv_share, М§4.6)."""
    return [b for b, sp in books.items() if sp.get("sector") and "fv_share" in sp]


def c_client_funds(books: dict) -> list[str]:
    """Небалансирующие пассивы, кроме пары средств физлиц, — средства клиентов-бизнеса (М§4.1 п. 1)."""
    return [b for b, sp in books.items()
            if sp["side"] != LOANS_SIDE and b not in (RETAIL_CURRENT, RETAIL_TERM, WHOLESALE)]


def c_unaudited_anchor(book: dict, A: dict):
    """E_0 — неаудированная прибыль на якоре по календарю аудитов (М§4.11); None — нет фактов кварталов."""
    cut = [int(c) for c in c_bget(book, "capital.n11.audit_cutoffs")]
    total = 0.0
    for yq in _c_unaudited_quarters(cut, *A["anchor"]):
        rec = A["pnl"].get(f"{yq[0]}Q{yq[1]}")
        if rec is None or rec.get("ni_shareholders") is None:
            return None
        total += float(rec["ni_shareholders"])
    return total


def c_resolve_anchor_keys(book: dict, A: dict) -> tuple[dict, dict]:
    """Книга с числами вместо "anchor" (формулы — прил. A М) и таблица выведенных значений."""
    B = copy.deepcopy(book)
    E0 = A["E0"]
    books = B["nii"]["books"]
    loans = [b for b, spec in books.items() if spec.get("sector")]
    sum_loans = sum(E0[b] for b in loans)
    loans_ac = sum_loans - A["fv_loans"] if A["fv_loans"] is not None else sum_loans
    biz = c_client_funds(books)
    if biz == [CORP_FUNDS]:
        funds = E0[RETAIL_CURRENT] + E0[RETAIL_TERM] + E0[CORP_FUNDS]
    else:
        funds = E0[RETAIL_CURRENT] + E0[RETAIL_TERM] + sum(E0[b] for b in biz)
    la = E0[SECURITIES] + E0[LIQUIDITY]
    # постоянные прочие активы (М§4.3): число книги или узел фактов; без ключа — 0, и формула образца
    oaf_key = c_bopt(B, "volumes.other_assets_fixed")
    if oaf_key == "anchor":
        if A["OA_fixed_fact"] is None:
            raise ControlInputError("volumes.other_assets_fixed: anchor без узла balance.other_assets_fixed")
        oaf = float(A["OA_fixed_fact"])
    else:
        oaf = float(oaf_key or 0.0)
    if oaf < 0.0 or oaf > A["OA"]:
        raise ControlInputError("постоянные прочие активы вне [0; прочие активы якоря] (М§4.3)")
    A["OA_fixed"] = oaf
    formulas = {
        "credit.allowance_ratio": A["AL"] / loans_ac,
        "nii.retail_current_share.c_ref": A["current_share"],
        "nii.retail_current_share.key_ref": A["key_ref"],
        "volumes.wholesale_to_funds": E0[WHOLESALE] / funds,
        "volumes.securities_share_of_liquid": E0[SECURITIES] / la,
        "volumes.other_assets_fixed": oaf,
        "volumes.other_assets_to_loans": (A["OA"] - oaf) / sum_loans if oaf else A["OA"] / sum_loans,
        "volumes.other_liabilities_to_loans": A["OL"] / sum_loans,
        "oci.fvoci_share": A["fvoci_debt"] / E0[SECURITIES],
        "oci.fvtpl_bond_share": (A["fvtpl_bonds"] or 0.0) / E0[SECURITIES],
    }
    for b in c_fv_books(books):
        if A["fv_loans"] is not None:
            formulas[f"nii.books.{b}.fv_share"] = A["fv_loans"] / E0[b]
    # вычеты капитала якоря словом anchor (М§4.11, прил. A): Ded20_0 = BV − капитал группы без
    # регуляторных инструментов; Ded11_0 = BVreg − max(E_0, 0) − базовый капитал группы
    if c_bget(B, "capital.n20.deductions_anchor") == "anchor":
        if A["group_cet1"] is None:
            raise ControlInputError("capital.n20.deductions_anchor: anchor без узла capital.basel.cet1")
        formulas["capital.n20.deductions_anchor"] = A["BV"] - float(A["group_cet1"])
    if c_bget(B, "capital.n11.deductions_anchor") == "anchor":
        e0 = c_unaudited_anchor(B, A)
        if A["base_capital"] is None or e0 is None:
            raise ControlInputError("capital.n11.deductions_anchor: anchor без базового капитала группы "
                                    "или прибыли неаудированного периода якоря")
        bvreg0 = A["BV"] + c_dpreg_anchor(B, A) - (1.0 - c_bnum(B, "capital.n20.fvoci_recognition")) * A["R0"]
        formulas["capital.n11.deductions_anchor"] = bvreg0 - max(e0, 0.0) - float(A["base_capital"])
    derived = {}

    def c_walk(node, prefix):
        if isinstance(node, dict):
            for k, v in node.items():
                path = f"{prefix}.{k}" if prefix else str(k)
                if v == "anchor":
                    if path == "nii.transmission.weights":
                        continue                                # веса — структура якоря (М§4.5)
                    if path.startswith("meta.labels."):
                        continue                                # подпись, не ключ вывода
                    if path not in formulas:
                        raise ControlInputError(f"anchor-ключ без формулы: {path}")
                    node[k] = formulas[path]
                    derived[path] = formulas[path]
                else:
                    c_walk(v, path)

    c_walk(B, "")
    return B, derived


# ============================================================================ мост упр. ↔ движок (М§4.6)

def c_to_engine(A: dict, x: str, v: float) -> float:
    method, b = A["bridge"][x]
    if method == "additive":
        return v + b
    if method == "ratio":
        return v * b
    raise ControlInputError(f"метод моста {method}")


def c_to_mgmt(A: dict, x: str, v: float) -> float:
    if x not in A["bridge"]:
        raise ControlInputError(f"в фактах нет моста упр. ↔ движок для {x} (М§4.6)")
    method, b = A["bridge"][x]
    return v - b if method == "additive" else v / b


# ============================================================================ миры

def c_world_quarter(book: dict, w: str, field: str, y: int, q: int) -> float:
    return c_traj_at(c_bget(book, f"worlds.{w}.{field}"), y, q)


def c_ref_field(ref: str) -> str:
    return "key_rate" if ref == "key" else ref


def c_kappa_world(book: dict):
    """Мир-опора κ (ключ книги credit.kappa_reference_world): мир, в котором стоят уровни CoR режимов. Нет
    ключа — None: добавка образца, относительно мира N и только вверх."""
    ref = c_bopt(book, "credit.kappa_reference_world")
    if ref is not None and ref not in c_bget(book, "worlds.ids"):
        raise ControlInputError(f"credit.kappa_reference_world: {ref!r} — не мир из worlds.ids (М§4.6)")
    return ref


def c_kappa_spread(book: dict, w: str, y: int, q: int) -> float:
    """Разность реальных ставок квартала (y, q), на которую умножается κ в мире w (М§4.6). С миром-опорой —
    rr_w − rr_опоры с любым знаком: в мире-опоре ноль, в мире с меньшей реальной ставкой добавка
    отрицательна. Без ключа — max(0, rr_w − rr_N)."""
    rr = c_world_quarter(book, w, "real_key", y, q)
    ref = c_kappa_world(book)
    if ref is None:
        return max(0.0, rr - c_world_quarter(book, W_LOW, "real_key", y, q))
    return rr - c_world_quarter(book, ref, "real_key", y, q)


def c_g_terminal(book: dict, w: str) -> float:
    """g_T мира до защиты k_T − 0,0001 (М§7)."""
    return ((1.0 + c_bnum(book, f"worlds.{w}.lt_inflation"))
            * (1.0 + c_bnum(book, "valuation.terminal.real_growth")) - 1.0)


def c_overlay_growth(book: dict, w: str, group: str, name: str, y: int) -> float:
    """Рост надстройки миров года y; после последнего года — линейный сход к g_T к lt_from (М§4.3)."""
    table = {int(k): float(v) for k, v in c_bget(book, f"worlds_bank.{w}.{group}.{name}").items()}
    if y in table:
        return table[y]
    first, last = min(table), max(table)
    if y < first:
        return table[first]
    gt = c_g_terminal(book, w)
    lt_from = int(c_bnum(book, "volumes.lt_from"))
    if y >= lt_from:
        return gt
    return table[last] + (gt - table[last]) * (y - last) / (lt_from - last)


# ============================================================================ передача ставки (М§4.5)

def c_transmission_ctl(book: dict, A: dict) -> dict:
    """σ0_A, σ0_L, φ, φ_A, φ_L, target_eng, T_real, T(W), пары, эффективные LT-спреды кредитных книг и
    кредитная маржа миров — замкнутое решение по стационарному ЧПМ (М§4.5). Сдвиг Δ0 делит
    nii.sigma0_split, сжатие φ — nii.phi_split: объём сжатия мира φ × C_W один при любой доле, доля p
    снимается со спредов кредитных книг Φ_A, остаток — добавка к стоимости пассивов Φ_L. Ключ цели
    (target_eng) — стационарный ЧПМ мира nii.transmission.level_world (nss_level); без ключа — мира-опоры."""
    books = c_bget(book, "nii.books")
    E0 = A["E0"]
    iea = sum(E0[b] for b, s in books.items() if s["side"] == LOANS_SIDE)
    yl, ql = c_per_parse(c_bget(book, "meta.last_period"))
    ref_w = c_bget(book, "nii.transmission.reference_world")

    def c_ref_lt(w, ref):
        return c_world_quarter(book, w, c_ref_field(ref), yl, ql)

    def c_s_lt(b):
        return c_traj_at(books[b]["spread"], yl, ql)

    c_ref = c_bnum(book, "nii.retail_current_share.c_ref")
    k_ref = c_bnum(book, "nii.retail_current_share.key_ref")
    psi = c_bnum(book, "nii.retail_current_share.psi")
    lo, hi = (float(x) for x in c_bget(book, "nii.retail_current_share.bounds"))
    dia = c_bnum(book, "nii.dia_rate")
    l_r = (E0[RETAIL_CURRENT] + E0[RETAIL_TERM]) / iea

    def c_cstar(key):
        return min(hi, max(lo, c_ref - psi * (key - k_ref)))

    def c_cost_lt(b, base, sl):
        # стоимость пассива в стационаре: β × опора + s^LT − σ0_L × [lt_shift]
        sp = books[b]
        return float(sp["beta"]) * base + c_s_lt(b) - (sl if sp.get("lt_shift") else 0.0)

    def c_nss(w, d, sa, sl, ph):
        key = c_ref_lt(w, "key") + d
        tot = 0.0
        for b, sp in books.items():
            wgt = E0[b] / iea
            r_w = c_ref_lt(w, sp["ref"]) + d
            if sp["side"] == LOANS_SIDE:
                val = r_w + c_s_lt(b) + (sa if sp.get("lt_shift") else 0.0)
                if sp.get("phi"):
                    val -= ph * (r_w - c_ref_lt(ref_w, sp["ref"]))
                tot += wgt * val
            elif b not in (RETAIL_CURRENT, RETAIL_TERM):
                tot -= wgt * c_cost_lt(b, r_w, sl)
        c = c_cstar(key)
        tot -= l_r * (c * c_cost_lt(RETAIL_CURRENT, key, sl) + (1.0 - c) * c_cost_lt(RETAIL_TERM, key, sl))
        tot -= dia * l_r
        return tot

    target = c_to_engine(A, "nim", c_bnum(book, "nii.nim_lt_target_mgmt"))
    split = c_bnum(book, "nii.sigma0_split")
    if not 0.0 <= split <= 1.0:
        raise ControlInputError("nii.sigma0_split вне [0; 1] (М прил. A)")
    # Δ0 — нужный сдвиг стационарного ЧПМ мира H (там сжатие φ равно нулю); долю split несут активы с
    # lt_shift, остаток — пассивы с lt_shift. Вес пассива в стационаре мира H: у средств ФЛ —
    # l_R × c*(key_H^LT) (текущие) и l_R × (1 − c*(key_H^LT)) (срочные), у прочих — l_b.
    base_ref = c_nss(ref_w, 0.0, 0.0, 0.0, 0.0)
    w_assets = sum(E0[b] / iea for b, s in books.items() if s["side"] == LOANS_SIDE and s.get("lt_shift"))
    c_h = c_cstar(c_ref_lt(ref_w, "key"))
    w_liab = 0.0
    for b, s in books.items():
        if s["side"] == LOANS_SIDE or not s.get("lt_shift"):
            continue
        w_liab += l_r * c_h if b == RETAIL_CURRENT else l_r * (1.0 - c_h) if b == RETAIL_TERM else E0[b] / iea
    if split > 0.0 and w_assets == 0.0:
        raise ControlInputError("nii.sigma0_split > 0 без актива с lt_shift (М§4.5)")
    if split < 1.0 and w_liab == 0.0:
        raise ControlInputError("nii.sigma0_split < 1 без пассива с lt_shift (М§4.5)")
    dk = c_ref_lt(W_MKT, "key") - c_ref_lt(W_LOW, "key")
    if dk == 0.0:
        raise ControlInputError("передача не определена: key_M^LT = key_N^LT")
    dphi = sum(E0[b] / iea * (c_ref_lt(W_MKT, s["ref"]) - c_ref_lt(W_LOW, s["ref"]))
               for b, s in books.items() if s["side"] == LOANS_SIDE and s.get("phi")) / dk
    if dphi == 0.0:
        raise ControlInputError("передача не определена: D = 0")
    t_star = c_bnum(book, "nii.transmission.target")

    def c_shifts(d0):
        # сдвиги спредов и сжатие при сдвиге Δ0 стационарного ЧПМ мира-опоры: (σ0_A, σ0_L, T при φ = 0, φ)
        sa = split * d0 / w_assets if split > 0.0 else 0.0
        sl = (1.0 - split) * d0 / w_liab if split < 1.0 else 0.0
        flat = (c_nss(W_MKT, 0.0, sa, sl, 0.0) - c_nss(W_LOW, 0.0, sa, sl, 0.0)) / dk
        return sa, sl, flat, (flat - t_star) / dphi

    # Чей уровень задаёт ключ цели (nii.transmission.level_world): без ключа — мира-опоры, и Δ0 — прямая
    # разность. С ключом ключ цели — стационарный ЧПМ названного мира на составе якоря: он линеен по Δ0
    # (σ0 и φ линейны по Δ0 и входят слагаемыми), поэтому Δ0 — из значения при Δ0 = 0 и отклика на единицу.
    level_w = c_bopt(book, "nii.transmission.level_world")
    if level_w is not None and level_w not in c_bget(book, "worlds.ids"):
        raise ControlInputError(f"nii.transmission.level_world: {level_w!r} — не мир из worlds.ids (М§4.5)")
    if level_w is None or level_w == ref_w:
        delta0 = target - base_ref
    else:
        def c_level(d0):
            sa, sl, _, ph = c_shifts(d0)
            return c_nss(level_w, 0.0, sa, sl, ph)

        at_zero = c_level(0.0)
        unit = c_level(1.0) - at_zero
        if unit == 0.0:
            raise ControlInputError(f"стационарный ЧПМ мира {level_w} не зависит от сдвига спредов (М§4.5)")
        delta0 = (target - at_zero) / unit
    sigma0, sigma0_l, t0, phi = c_shifts(delta0)
    t_real = (c_nss(W_MKT, 0.0, sigma0, sigma0_l, phi) - c_nss(W_LOW, 0.0, sigma0, sigma0_l, phi)) / dk
    h = c_bnum(book, "nii.transmission.fd_step")
    ids = list(c_bget(book, "worlds.ids"))
    t_loc = {w: (c_nss(w, h, sigma0, sigma0_l, phi) - c_nss(w, -h, sigma0, sigma0_l, phi)) / (2.0 * h)
             for w in ids}
    # Парные передачи соседних по key^LT миров (М§4.5): равные key^LT — пара не определена (None).
    key_lt = {w: c_ref_lt(w, "key") for w in ids}
    nss0 = {w: c_nss(w, 0.0, sigma0, sigma0_l, phi) for w in ids}
    # Раскладка сжатия (М§4.5): φ_A = p × φ — спреды кредитных книг Φ_A; φ_L = (1 − p) × φ × A / L —
    # добавка к стоимости пассивов Φ_L на единицу X_W = Σ ω_b × (ref_b,W − ref_b,H), ω_b = a_b / A.
    # Флаг phi у обеих книг средств ФЛ обязан совпадать: их веса в стационаре зависят от мира.
    p_split = c_bnum(book, "nii.phi_split")
    if not 0.0 <= p_split <= 1.0:
        raise ControlInputError("nii.phi_split вне [0; 1] (М прил. A)")
    if bool(books[RETAIL_CURRENT].get("phi")) != bool(books[RETAIL_TERM].get("phi")):
        raise ControlInputError("флаг phi у книг средств ФЛ разный (М§4.5)")
    phi_a_w = {b: E0[b] / iea for b, s in books.items() if s["side"] == LOANS_SIDE and s.get("phi")}
    a_sum = sum(phi_a_w.values())
    l_sum = sum(E0[b] / iea for b, s in books.items() if s["side"] != LOANS_SIDE and s.get("phi"))
    if p_split > 0.0 and a_sum == 0.0:
        raise ControlInputError("nii.phi_split > 0 без актива с phi (М§4.5)")
    if p_split < 1.0 and l_sum == 0.0:
        raise ControlInputError("nii.phi_split < 1 без пассива с phi (М§4.5)")
    phi_a = p_split * phi
    phi_l = (1.0 - p_split) * phi * a_sum / l_sum if p_split < 1.0 else 0.0
    omega = {b: v / a_sum for b, v in phi_a_w.items()}
    x_lt = {w: sum(omega[b] * (c_ref_lt(w, books[b]["ref"]) - c_ref_lt(ref_w, books[b]["ref"])) for b in omega)
            for w in ids}
    # Эффективный LT-спред кредитной книги к её опоре в стационаре мира (М§4.5, гейт lt_spread_floor):
    # s_eff = s^LT + σ0_A × [lt_shift] − φ_A × [b ∈ Φ_A] × (ref_W^LT − ref_H^LT)
    lt_spread = {}
    for b, s in books.items():
        if not s.get("sector"):
            continue
        lt_spread[b] = {w: (c_s_lt(b) + (sigma0 if s.get("lt_shift") else 0.0)
                            - (phi_a * (c_ref_lt(w, s["ref"]) - c_ref_lt(ref_w, s["ref"])) if s.get("phi") else 0.0))
                        for w in ids}

    def c_nss_books(w):
        # стационарный ЧПМ «по книгам»: сжатие — долями φ_A (спреды Φ_A) и φ_L × X_W (стоимость Φ_L);
        # обязан совпасть с Nss(W, 0), где сжатие — одним слагаемым φ × C_W
        key = c_ref_lt(w, "key")
        c = c_cstar(key)
        tot = 0.0
        for b, sp in books.items():
            r_w = c_ref_lt(w, sp["ref"])
            if sp["side"] == LOANS_SIDE:
                val = r_w + c_s_lt(b) + (sigma0 if sp.get("lt_shift") else 0.0)
                if sp.get("phi"):
                    val -= phi_a * (r_w - c_ref_lt(ref_w, sp["ref"]))
                tot += E0[b] / iea * val
                continue
            wgt = l_r * c if b == RETAIL_CURRENT else l_r * (1.0 - c) if b == RETAIL_TERM else E0[b] / iea
            tot -= wgt * (c_cost_lt(b, r_w, sigma0_l) + (phi_l * x_lt[w] if sp.get("phi") else 0.0))
        return tot - dia * l_r

    # Кредитная маржа стационара мира (М§4.5): доходность кредитного портфеля − CoR режима norm с
    # κ-добавкой мира − смесь балансирующих активов (бумаги и ликвидность в долях LA)
    credit = [b for b, s in books.items() if s.get("sector")]
    cor_norm = c_traj_at(c_bget(book, f"regimes.{R_NORM}.cor"), yl, ql)
    if c_bget(book, "regimes.cor_basis") == "mgmt":
        cor_norm = c_to_engine(A, "cor", cor_norm)
    kap = c_bnum(book, "credit.kappa")
    sec = c_bnum(book, "volumes.securities_share_of_liquid")
    margin = {}
    for w in ids:
        yld = (sum(E0[b] * (c_ref_lt(w, books[b]["ref"]) + lt_spread[b][w]) for b in credit)
               / sum(E0[b] for b in credit))
        risk = cor_norm + kap * c_kappa_spread(book, w, yl, ql)
        bal = (sec * (c_ref_lt(w, books[SECURITIES]["ref"]) + c_s_lt(SECURITIES))
               + (1.0 - sec) * (c_ref_lt(w, books[LIQUIDITY]["ref"]) + c_s_lt(LIQUIDITY)))
        margin[w] = yld - risk - bal
    order = sorted(ids, key=lambda w: key_lt[w])
    pairs = {}
    for w1, w2 in zip(order, order[1:]):
        dkk = key_lt[w2] - key_lt[w1]
        pairs[f"{w1}_{w2}"] = None if dkk == 0.0 else (nss0[w2] - nss0[w1]) / dkk
    # ROE-эквивалент: T × IEA_0/BV_0 × (1 − τ_eff года last_period) — п.п. ROE на 1 п.п. ключевой
    tau_l = c_traj_at(c_bget(book, "tax.statutory"), yl, ql) + c_bnum(book, "tax.effective_gap")
    scale = iea / A["BV"] * (1.0 - tau_l)
    return {"sigma0": sigma0, "sigma0_liab": sigma0_l, "split": split, "delta0": delta0,
            "w_assets": w_assets, "w_liab": w_liab, "lt_spread": lt_spread,
            "phi": phi, "phi_split": p_split, "phi_assets": phi_a, "phi_liab": phi_l, "phi_weights": omega,
            "phi_a_sum": a_sum, "phi_l_sum": l_sum, "x_lt": x_lt, "loan_margin": margin,
            "nss_books": {w: c_nss_books(w) for w in ids},
            "target_eng": target, "t_real": t_real, "t_local": t_loc,
            "level_world": level_w or ref_w, "nss_level": nss0[level_w or ref_w],
            "nss_ref": nss0[ref_w], "nss": nss0, "key_lt": key_lt, "iea0": iea,
            "d_phi": dphi, "t_real_phi0": t0, "pairs": pairs, "roe_equiv": t_star * scale,
            "roe_equiv_pairs": {k: None if v is None else v * scale for k, v in pairs.items()}}


# ============================================================================ контекст прогона

def _c_pos(x: dt.date, anchor: tuple[int, int]) -> float:
    """Положение даты на линейке кварталов сетки (М§0.2) — одна функция для даты оценки и даты
    кривой, по конвенции «конец дня»: внутри квартала q — (q − 1) + (x − S_q)/d_q, на конце
    квартала pos(E_q) = q (квартал закрыт, как у S_(q+1)). q — номер квартала сетки: первый
    прогнозный — 1, раньше сетки — q ≤ 0."""
    y0, qa = anchor
    y, q = x.year, (x.month - 1) // 3 + 1
    qi = (y - y0) * QY + (q - qa)
    if x == c_q_last_day(y, q):
        return float(qi)
    return (qi - 1) + (x - c_q_first_day(y, q)).days / c_q_len(y, q)


def _c_clock(B: dict, periods: list[dict], v: dt.date) -> dict:
    """Дата оценки на годовой линейке (М§0.2): период p0 с v и число прошедших в нём кварталов
    pos (целые — закрытые, дробь — доля дней квартала q0); e = pos/n; начала периодов в годах от v
    по линейке 0,25 года на квартал."""
    facts_date = _c_as_date(c_bget(B, "meta.facts_date"))
    if v < facts_date:
        raise ControlInputError("дата оценки раньше даты фактов")
    anchor = c_per_parse(c_bget(B, "meta.anchor_period"))
    pos_abs = 0.0 if v == facts_date else _c_pos(v, anchor)
    first, p0 = 0.0, None
    for i, p in enumerate(periods):
        if first <= pos_abs < first + p["n"]:
            p0, pos = i, pos_abs - first
            break
        first += p["n"]
    if p0 is None:
        raise ControlInputError("дата оценки вне сетки (v ≥ E_Q)")
    t_start, t = {}, -pos / QY
    for i in range(p0, len(periods)):
        t_start[i] = t
        t += periods[i]["n"] / QY
    return {"v": v, "p0": p0, "pos": pos, "e": pos / periods[p0]["n"], "pos_abs": pos_abs,
            "t_start": t_start, "tau_end": {i: t_start[i] + periods[i]["n"] / QY for i in t_start}}


def _c_kappa_gap(B: dict, w: str, y: int, q: int, lag: int) -> float:
    """Разность реальных ставок κ-добавки квартала q − L (М§4.6): относительно мира-опоры книги с любым
    знаком, без ключа опоры — max(0, rr_W − rr_N); история до сетки — ноль (она у миров общая)."""
    y0, qa = c_per_parse(c_bget(B, "meta.anchor_period"))
    idx = (y - y0) * QY + (q - qa) - lag                # номер квартала сетки q − L
    if idx < 1:
        return 0.0                                      # история до сетки: rr одинакова во всех мирах
    yy, qq = y0 + (qa + idx - 1) // QY, (qa + idx - 1) % QY + 1
    return c_kappa_spread(B, w, yy, qq)


def _c_world_period(B: dict, w: str, p: dict, lag: int) -> dict:
    """Ряды мира за период по кварталам и κ-разрыв с лагом."""
    y, qs = p["year"], p["quarters"]
    out = {}
    for f in ("key_rate", "ofz_1y", "ofz_3y", "ofz_5y", "ofz_10y", "cpi", "wage_growth", "real_key"):
        out[f] = [c_world_quarter(B, w, f, y, q) for q in qs]
    out["kappa_gaps"] = [_c_kappa_gap(B, w, y, q, lag) for q in qs]
    return out


def c_control_context(book: dict, facts: dict, *, valuation_date=None, base_book: dict | None = None) -> dict:
    """Всё общее для 36 клеток: якорь, выведенные ключи, передача, миры, дисконт, A-P2u.

    base_book — книга до подмен (М§4.6): по ней берётся путь режима-опоры FVC, который не сдвигается
    вместе с осями и чувствительностями; без неё книга — сама себе база."""
    A = c_anchor_state(book, facts)
    B, derived = c_resolve_anchor_keys(book, A)
    B0 = B if base_book is None else c_resolve_anchor_keys(base_book, A)[0]
    for sw, what in (("capital.recapitalization.enabled", "докапитализация"),
                     ("dividends.buyback.enabled", "байбэк")):
        if c_bget(B, sw):
            raise ControlUnsupported(f"{what} включён — модуль не реализован (М§0.6)")
    if c_bopt(B, "valuation.terminal.fade_mode") == FADE_SYMMETRIC:
        # симметричное угасание — правило справочного варианта таблиц книги, а не точки книги (М§7, §17)
        raise ControlUnsupported("симметричное угасание (valuation.terminal.fade_mode) — справочный вариант: "
                                 "контрольная модель считает точку книги с односторонним угасанием")
    periods = c_annual_periods(B)
    y0, qa = c_per_parse(c_bget(B, "meta.anchor_period"))
    quarterly = c_is_quarterly(B)
    growth = c_growth_rule(B)
    tr = c_transmission_ctl(B, A)
    books = B["nii"]["books"]
    s0_from = int(c_bnum(B, "nii.sigma0_from"))
    if not periods[0]["year"] <= s0_from <= periods[-1]["year"]:
        raise ControlInputError("nii.sigma0_from вне годов first_period…last_period (М прил. A)")
    shares = {int(h): float(v) for h, v in c_bget(B, "other.misc_quarter_shares").items()}
    if sorted(shares) != list(range(1, QY + 1)) or abs(sum(shares.values()) - 1.0) > 1e-9:
        raise ControlInputError("other.misc_quarter_shares: нужны доли кварталов 1…4 с суммой 1 (М§4.7)")
    v = _c_as_date(valuation_date or c_bget(B, "meta.valuation_date"))
    clock = _c_clock(B, periods, v)
    lag = int(c_bnum(B, "credit.real_rate_lag_q"))
    worlds = list(c_bget(B, "worlds.ids"))
    wv = {w: [_c_world_period(B, w, p, lag) for p in periods] for w in worlds}
    add = c_bnum(B, "valuation.beta_e") * c_bnum(B, "valuation.erp")
    ca = _c_as_date(c_bget(B, "meta.curve_as_of"))
    # перекат (М§0.2): Δ = 0,25 × (pos(v) − pos(curve_as_of)) по линейке кварталов
    shift = (0.25 * (clock["pos_abs"] - _c_pos(ca, (y0, qa)))
             if (c_bget(B, "valuation.roll_along_forwards") and ca < v) else 0.0)
    disc = {w: CDisc(c_bget(B, f"worlds.{w}.zero_curve"), add, shift) for w in worlds}
    dens = c_bget(B, "capital.rwa.density")
    oaf = A["OA_fixed"]
    dens_oaf = 0.0
    if oaf:
        if dens.get("other_assets_fixed") is None:
            raise ControlInputError("постоянные прочие активы без плотности capital.rwa.density.other_assets_fixed")
        dens_oaf = float(dens["other_assets_fixed"])
        if dens_oaf < 0.0:
            raise ControlInputError("capital.rwa.density.other_assets_fixed отрицательна (М§4.11)")
    mults = {}
    for rid in c_bget(B, "regimes.ids"):
        mult = c_bopt(B, f"regimes.{rid}.rwa_density_mult")
        if mult is not None:
            vals = [mult] if not isinstance(mult, dict) else [v for k, v in mult.items() if str(k) != "LT_from"]
            if any(float(v) <= 0.0 for v in vals):
                raise ControlInputError(f"regimes.{rid}.rwa_density_mult: значение ≤ 0 (М§4.11)")
            mults[rid] = mult
    links = tuple(float(c_bopt(B, key, 0.0)) for key in ("fees.volume_link", "other.insurance_volume_link",
                                                        "opex.volume_link"))
    if any(not 0.0 <= x <= 1.0 for x in links):
        raise ControlInputError("связь с объёмом вне [0; 1] (М§4.7)")
    link_base = c_bopt(B, "volumes.link_base", LINK_BASES[0])
    if any(links) and link_base not in LINK_BASES:
        raise ControlInputError(f"volumes.link_base: {link_base!r} (М§4.7)")
    loans_ids = [b for b, sp in books.items() if sp.get("sector")]
    geo = {"books": books, "dens": dens, "oaf": oaf, "dens_oaf": dens_oaf, "rwa_mult": mults}
    rwa0 = _c_rwa_of(geo, None, y0, qa, A["E0"], A["OA"], 1.0, 1.0)
    gov = sum(float(c["sign"]) * float(c["value"]) for c in c_bget(B, "valuation.governance.components"))
    fv_ref = c_bget(B, "credit.fv_loans_ref")
    if fv_ref not in c_bget(B, "regimes.ids"):
        raise ControlInputError("credit.fv_loans_ref — не режим из regimes.ids (М§4.6)")
    ctx = {"A": A, "B": B, "derived": derived, "periods": periods, "tr": tr, "sigma0_from": s0_from,
           "misc_shares": shares, "clock": clock, "wv": wv, "disc": disc, "rwa0": rwa0, "worlds": worlds,
           "gov": c_bnum(B, "valuation.governance.discount"), "gov_sum": gov, "fv_ref": fv_ref, "B0": B0,
           "shock_year": c_shock_year(B),
           "posterior": dict(c_bget(B, "joint.regime_prob")), "dev": {}, "mu": {}, "anchor": (y0, qa),
           "quarterly": quarterly, "growth": growth, "links": links, "link_base": link_base,
           "loans": loans_ids, "biz": c_client_funds(books), "glide_memo": {},
           "fv": {b: c_bnum(B, f"nii.books.{b}.fv_share") for b in c_fv_books(books)},
           "Q": c_qidx((y0, qa), *c_per_parse(c_bget(B, "meta.last_period"))), **geo}
    if quarterly:
        if c_bopt(B, "dividends.policy.steps"):
            raise ControlInputError("непустой dividends.policy.steps в квартальном режиме (М§5.7.1)")
        ctx["divcal"] = c_div_calendar(B, A)
    ctx["bridge_amount"] = c_bridge_register(ctx)
    ctx["pending_amount"] = c_pending_register(ctx)
    c_regime_update_ctl(ctx)
    return ctx


def c_shock_year(B: dict) -> int:
    """Год шока кризиса = год якоря + regimes.crisis.shock_year_offset (М§3.2). Кризисные ключи
    привязаны к нему: квартальный профиль CoR, период разового убытка и первый год
    loan_growth_override обязаны лежать в году шока — иначе громкий отказ."""
    off = c_bget(B, "regimes.crisis.shock_year_offset")
    if isinstance(off, bool) or not isinstance(off, int) or off < 1:
        raise ControlInputError("regimes.crisis.shock_year_offset — целое ≥ 1 (М прил. A)")
    shock = c_per_parse(c_bget(B, "meta.anchor_period"))[0] + off
    cor = c_bget(B, "regimes.crisis.cor")
    if isinstance(cor, dict):
        for k, (ky, q1, q2) in _c_time_keys({str(k): v for k, v in cor.items()}).items():
            if q1 == q2 and ky != shock:
                raise ControlInputError(f"regimes.crisis.cor: квартальный ключ {k} вне года шока {shock}")
    if c_per_parse(c_bget(B, "regimes.crisis.one_off_loss.period"))[0] != shock:
        raise ControlInputError(f"regimes.crisis.one_off_loss.period вне года шока {shock}")
    over = c_bget(B, "regimes.crisis.loan_growth_override") or {}
    if over and min(int(k) for k in over) != shock:
        raise ControlInputError(f"regimes.crisis.loan_growth_override: первый год — не год шока {shock}")
    return shock


# ============================================================================ помощники клетки

def _c_fact_q(A: dict, line: str, y: int, q: int):
    rec = A["pnl"].get(f"{y}Q{q}")
    return None if rec is None else rec.get(line)


def _c_need_fact_q(A: dict, line: str, y: int, q: int) -> float:
    v = _c_fact_q(A, line, y, q)
    if v is None:
        raise ControlInputError(f"нет факта pnl_quarterly {y}Q{q}.{line}")
    return float(v)


def _c_fact_line(A: dict, line: str, y: int, q: int) -> float:
    """Факт строки в знаке движка: расходы — положительным числом (в отчётности — со знаком минус)."""
    v = _c_need_fact_q(A, line, y, q)
    return abs(v) if line == "opex" else v


def _c_floor(B: dict, s: str, which: str, y: int, q: int) -> float:
    base = c_bnum(B, f"capital.minimum.{which}")
    return base + sum(c_traj_at(c_bget(B, f"capital.reg_scenarios.{s}.{k}"), y, q)
                      for k in ("conservation", "sifi", "ccyb"))


def _c_partial(rho: float, n: int) -> tuple[float, float]:
    """Годовая агрегация подстройки ρ за n кварталов: (доля к цели на конец, средняя доля)."""
    lag = 1.0 - rho
    return 1.0 - lag ** n, 1.0 - sum(lag ** j for j in range(1, n + 1)) / n


def _c_path_mean(points: list[float]) -> float:
    """Средний остаток периода по остаткам на концах кварталов: среднее квартальных трапеций."""
    return sum((a + b) / 2.0 for a, b in zip(points, points[1:])) / (len(points) - 1)


def _c_geo_path(start: float, end: float, n: int) -> list[float]:
    """Остатки на концах кварталов периода при одном квартальном множителе (М§4.3): статья растёт от
    начала к концу периода геометрически — замкнутая форма, без прохода по кварталам клетки."""
    if start <= 0.0 or end <= 0.0:
        return [start + (end - start) * j / n for j in range(n + 1)]
    g = (end / start) ** (1.0 / n)
    return [start * g ** j for j in range(n + 1)]


def _c_unaudited_quarters(cutoffs: list[int], y: int, h: int) -> list[tuple[int, int]]:
    """Кварталы неаудированной прибыли на конец квартала (y, h) (М§4.11)."""
    yy, hh = y, h
    out = []
    while True:
        out.append((yy, hh))
        yy, hh = (yy - 1, QY) if hh == 1 else (yy, hh - 1)
        if hh in cutoffs:
            return out
        if len(out) > QY * 2:
            return out


# ============================================================================ клетка: один период

def _c_period(ctx: dict, cell: dict, st: dict, i: int, div: float, plan: dict | None = None) -> tuple[dict, dict]:
    """Годовой шаг клетки (порядок М§4.2 в годовом приближении). Возвращает (состояние, строка).

    plan — квартальный план года ветви с квартальным проходом капитала (М§17): пути кредитных книг по
    концам кварталов (loans; None — потенциальный прирост целиком) и решения о дивиденде года с кварталами
    решения, вычета и выплаты (divs). Без плана — годовая ветвь образца: одно решение div в квартал собрания."""
    B, A, p = ctx["B"], ctx["A"], ctx["periods"][i]
    w, r, s = cell["world"], cell["regime"], cell["scenario"]
    y, qs, n = p["year"], p["quarters"], p["n"]
    frac, dfac = n / QY, p["days"] / DAYS_BASE
    wd = ctx["wv"][w][i]
    ref_w = c_bget(B, "nii.transmission.reference_world")
    wh = ctx["wv"][ref_w][i]
    books = B["nii"]["books"]
    y0, qa = ctx["anchor"]
    loans = [b for b, sp in books.items() if sp.get("sector")]
    biz, fv, oaf = ctx["biz"], ctx["fv"], ctx["oaf"]
    E, Ynew, row = dict(st["E"]), dict(st["y"]), {}

    def c_fv_part(vals):
        return sum(fv[b] * vals[b] for b in fv)

    # --- объёмы (М§4.3)
    gy = int(c_bnum(B, "volumes.guidance_year"))
    over = c_bget(B, "regimes.crisis.loan_growth_override") if r == R_CRISIS else {}
    over = {int(k): float(v) for k, v in (over or {}).items()}
    drift_until = int(c_bnum(B, "volumes.share_drift_until"))
    m_q = {}                                            # потенциальный прирост книги за квартал (М§4.13.1)
    for b in loans:
        sp = books[b]
        if y == gy:
            seg = sp["cor_segment"]
            if p["stub"]:
                start_seg = sum(st["E"][x] for x in loans if books[x]["cor_segment"] == seg)
                prev = A["prev_corp"] if seg == "corporate" else A["prev_retail"]
                mult = prev * (1.0 + c_bnum(B, f"volumes.guidance_growth.{seg}")) / start_seg
            else:
                mult = 1.0 + c_bnum(B, f"volumes.guidance_growth.{seg}")
            E[b] = st["E"][b] * mult
            m_q[b] = mult ** (1.0 / n) - 1.0
            continue
        if y in over:
            g = over[y]
        else:
            G = c_overlay_growth(B, w, "credit_growth", sp["sector"], y)
            d = c_premium(B, "volumes.loan_share_drift", LOAN_SECTORS, sp["sector"], y) if y <= drift_until else 0.0
            g = (1.0 + G) * (1.0 + d) - 1.0 + c_traj_mean(c_bget(B, f"regimes.{r}.loan_growth_adj"), y, qs)
        E[b] = st["E"][b] * (1.0 + g) ** frac
        m_q[b] = (1.0 + g) ** (1.0 / QY) - 1.0
    paths = plan.get("loans") if plan is not None else None
    if paths is not None:
        for b in loans:
            E[b] = paths[b][-1]
    fd = c_premium(B, "volumes.funds_share_drift", FUND_SEGMENTS, "retail", y, qs) if y <= drift_until else 0.0
    fd_c = c_premium(B, "volumes.funds_share_drift", FUND_SEGMENTS, "corporate", y, qs) if y <= drift_until else 0.0
    fr0 = st["E"][RETAIL_CURRENT] + st["E"][RETAIL_TERM]
    g_r = (1.0 + c_overlay_growth(B, w, "funds_growth", "retail", y)) * (1.0 + fd) - 1.0
    g_c = (1.0 + c_overlay_growth(B, w, "funds_growth", "corporate", y)) * (1.0 + fd_c) - 1.0
    fr1 = fr0 * (1.0 + g_r) ** frac
    for b in biz:
        E[b] = st["E"][b] * (1.0 + g_c) ** frac
    cf0, cf1 = sum(st["E"][b] for b in biz), sum(E[b] for b in biz)
    rcs = "nii.retail_current_share"
    lo, hi = (float(x) for x in c_bget(B, f"{rcs}.bounds"))
    share_target = sum(min(hi, max(lo, c_bnum(B, f"{rcs}.c_ref") - c_bnum(B, f"{rcs}.psi")
                                 * (k - c_bnum(B, f"{rcs}.key_ref")))) for k in wd["key_rate"]) / n
    rho_c = c_bnum(B, f"{rcs}.rho")
    c1 = st["c"] + _c_partial(rho_c, n)[0] * (share_target - st["c"])
    E[RETAIL_CURRENT], E[RETAIL_TERM] = c1 * fr1, (1.0 - c1) * fr1
    sum_loans = sum(E[b] for b in loans)
    loans_ac = sum_loans - c_fv_part(E) if fv else sum_loans
    wtf = c_bnum(B, "volumes.wholesale_to_funds")
    r_oa, r_ol = c_bnum(B, "volumes.other_assets_to_loans"), c_bnum(B, "volumes.other_liabilities_to_loans")
    r_al = c_bnum(B, "credit.allowance_ratio")
    wh_base = wtf * (fr1 + cf1)
    OA = r_oa * sum_loans
    if oaf:
        OA = OA + oaf                                   # постоянные прочие активы не растут (М§4.3)
    OL = r_ol * sum_loans
    AL = r_al * loans_ac
    # Средние остатки периода (М§0.3): небалансирующие статьи растут внутри периода одним квартальным
    # множителем, поэтому средний остаток — замкнутая сумма квартальных трапеций геометрического пути
    # (не полусумма начала и конца: та завышает средний остаток растущей статьи). Доля текущих счетов —
    # замкнутая подстройка к средней цели периода.
    fr_path = _c_geo_path(fr0, fr1, n)
    c_path = [st["c"] + (1.0 - (1.0 - rho_c) ** j) * (share_target - st["c"]) for j in range(n + 1)]
    # пути по концам кварталов периода: кредитные книги — план квартального прохода или геометрический
    # путь; средства клиентов-бизнеса — геометрический
    lpath = {b: (paths[b] if paths is not None else _c_geo_path(st["E"][b], E[b], n)) for b in loans}
    bpath = {b: _c_geo_path(st["E"][b], E[b], n) for b in biz}
    avg_nb = {b: _c_path_mean(lpath[b]) for b in loans}
    for b in biz:
        avg_nb[b] = _c_path_mean(bpath[b])
    avg_nb[RETAIL_CURRENT] = _c_path_mean([c * f for c, f in zip(c_path, fr_path)])
    avg_nb[RETAIL_TERM] = _c_path_mean([(1.0 - c) * f for c, f in zip(c_path, fr_path)])
    fr_avg = _c_path_mean(fr_path)
    cf_avg = sum(avg_nb[b] for b in biz)
    funds_avg = fr_avg + cf_avg
    loans_avg = sum(avg_nb[b] for b in loans)
    loans_ac_avg = loans_avg - c_fv_part(avg_nb) if fv else loans_avg
    funds0 = fr0 + cf0
    loans0 = sum(st["E"][b] for b in loans)
    ac_start = loans0 - c_fv_part(st["E"]) if fv else loans0
    # поправка среднего балансирующих активов на кривизну небалансирующих статей: LA = пассивы без
    # балансирующих + капитал − прочие активы, а полусумма начала и конца у растущих статей — не среднее
    curve_la = ((1.0 + wtf) * (funds_avg - (funds0 + fr1 + cf1) / 2.0)
                + (r_ol - r_oa - 1.0) * (loans_avg - (loans0 + sum_loans) / 2.0)
                + r_al * (loans_ac_avg - (ac_start + loans_ac) / 2.0))
    extra0 = max(0.0, st["E"][WHOLESALE] - wtf * funds0)             # добор опта на начало периода
    la0 = st["E"][SECURITIES] + st["E"][LIQUIDITY]
    assets_nb_avg = (1.0 + r_oa) * loans_avg - r_al * loans_ac_avg
    if oaf:
        assets_nb_avg = assets_nb_avg + oaf
    cf_path = [sum(bpath[b][j] for b in biz) for j in range(n + 1)]
    loans_path = [sum(lpath[b][j] for b in loans) for j in range(n + 1)]
    # концы кварталов кредитов по амортизированной стоимости — знаменатель годовой CoR (М§0.3)
    ac_path = [sum(lpath[b][j] * ((1.0 - fv[b]) if b in fv else 1.0) for b in loans) for j in range(n + 1)]

    # --- ставки книг (М§4.4): средняя за период и на конец. Сжатие φ — двумя скалярами пути: φ_A снимает
    # спред кредитных книг Φ_A, φ_L × X_W,q удорожает пассивы Φ_L; X_W,q — разность опорных ставок книг
    # Φ_A мира и мира H с долями ω_b якоря (от текущего остатка кредитов добавка не зависит)
    phi_a, phi_l, omega = ctx["tr"]["phi_assets"], ctx["tr"]["phi_liab"], ctx["tr"]["phi_weights"]
    x_w = [sum(om * (wd[c_ref_field(books[b]["ref"])][j] - wh[c_ref_field(books[b]["ref"])][j])
               for b, om in omega.items()) for j in range(n)]
    ybar, y_q = {}, {}
    for b, sp in books.items():
        ref = c_ref_field(sp["ref"])
        tgt = []
        for j, q in enumerate(qs):
            rv = wd[ref][j]
            sv = c_spread_at(ctx, b, y, q)
            if sp["side"] == LOANS_SIDE:
                if sp.get("phi"):
                    sv -= phi_a * (rv - wh[ref][j])
                tgt.append(rv + sv)
            else:
                tgt.append(float(sp["beta"]) * rv + sv + (phi_l * x_w[j] if sp.get("phi") else 0.0))
        T = sum(tgt) / n
        k_end, k_avg = _c_partial(float(sp["rho"]), n)
        Ynew[b] = st["y"][b] + k_end * (T - st["y"][b])
        ybar[b] = st["y"][b] + k_avg * (T - st["y"][b])
        # ставка квартала j периода — та же замкнутая подстройка к средней цели (среднее по j = ybar)
        y_q[b] = [st["y"][b] + (1.0 - (1.0 - float(sp["rho"])) ** (j + 1)) * (T - st["y"][b]) for j in range(n)]

    # --- строки, не зависящие от балансирующих статей
    days_q = [c_q_len(y, q) for q in qs]
    kap = c_bnum(B, "credit.kappa")
    dev = ctx["dev"].get(r, {})
    # CoR клетки по кварталам (М§4.6): путь режима через мост + κ-добавка мира + отклонение A-P2u;
    # за период — среднее по дням (резервы начисляются по дням, М§0.3)
    cor_prof = [c_cor_path_engine(ctx, r, y, q) + kap * wd["kappa_gaps"][j] + _c_dev_at(dev.get("cor"), y, q)
                for j, q in enumerate(qs)]
    cor_c = sum(c * d for c, d in zip(cor_prof, days_q)) / p["days"]
    d_nim = sum(_c_dev_at(dev.get("nim"), y, q) for q in qs) / n
    near = c_traj_mean(c_bget(B, "regimes.near_nim_shift"), y, qs)        # ближний сдвиг ЧПМ (М§3.2)
    seg_rel = {"corporate": 1.0, "retail": 1.0}
    if c_bget(B, "credit.segment_relative.enabled"):
        ac0 = {sg: sum(A["E0"][b] * ((1.0 - fv[b]) if b in fv else 1.0) for b in loans
                       if books[b]["cor_segment"] == sg) for sg in seg_rel}
        tot = sum(ac0.values())
        norm = sum(ac0[sg] / tot * c_bnum(B, f"credit.segment_relative.{sg}") for sg in seg_rel)
        seg_rel = {sg: c_bnum(B, f"credit.segment_relative.{sg}") / norm for sg in seg_rel}
    seg_cor = {sg: cor_c * seg_rel[sg] for sg in seg_rel}
    llp = 0.0
    for b in loans:
        share = (1.0 - fv[b]) if b in fv else 1.0
        llp += seg_cor[books[b]["cor_segment"]] * share * avg_nb[b] * dfac
    # Кредитная переоценка кредитов по СС сверх опоры (М§4.6): FVC_q = f × (CoR_corporate,q − CoR_ref,q)
    # × Ē^СС_q × d_q/365. CoR_ref — путь режима-опоры книги до розыгрыша (книга-опора контекста) через
    # мост с той же сегментной поправкой, без κ-добавки и отклонения A-P2u (они — в CoR клетки и потому
    # действуют и на кредиты по СС); сдвиг путей CoR всех режимов опору не двигает.
    # Отклонение от опоры меняет величину и знак внутри года (профиль кризиса, затухание δ), поэтому
    # строка считается по кварталам: кредиты по СС растут внутри периода одним квартальным множителем.
    ref_prof = [c_cor_ref_engine(ctx, y, q) for q in qs]
    f_fv = c_bnum(B, "credit.fv_loans_factor")
    fv_avg_q, fvc_q = [0.0] * n, [0.0] * n              # у книги без fv_share строка FVC — ноль (М§4.6)
    for b, fvs in fv.items():
        ss0, ss1 = fvs * st["E"][b], fvs * E[b]
        ss_g = (ss1 / ss0) ** (1.0 / n) if ss0 > 0.0 and ss1 > 0.0 else 1.0
        rel_b = seg_rel[books[b]["cor_segment"]]
        for j in range(n):
            avg_j = ss0 * ss_g ** j * (1.0 + ss_g) / 2.0                     # средние кредиты по СС квартала
            fv_avg_q[j] = fv_avg_q[j] + avg_j
            fvc_q[j] = fvc_q[j] + (f_fv * rel_b * (cor_prof[j] - ref_prof[j])
                                   * avg_j * days_q[j] / DAYS_BASE)
    fvc = sum(fvc_q)
    # ЧКД, расходы, страхование — г/г к тому же кварталу (М§0.3, §4.7): база — факт или квартал
    # прошлого года клетки; кварталы года хранятся в состоянии (сезонность переносится из истории)
    wage = wd["wage_growth"]
    ov = {int(k): float(v) for k, v in (c_bget(B, "fees.growth_override") or {}).items()}
    fees_b = _c_yoy_quarters(ctx, st, "fees_net", y, qs)
    opex_b = _c_yoy_quarters(ctx, st, "opex", y, qs)
    ins_b = _c_yoy_quarters(ctx, st, "insurance_net", y, qs)
    link_f, link_i, link_c = ctx["links"]
    link_on = bool(link_f or link_i or link_c)
    rg = c_bget(B, "opex.real_growth")
    igw = c_bget(B, "other.insurance_growth_vs_wages")

    def c_volume_lines(v):
        """Комиссии, расходы и страхование кварталов периода (М§4.7). v — рост объёма периода (годовая
        форма связи с объёмом); None — связи нулевые, формулы образца."""
        if y in ov and y == y0 and p["stub"]:
            # рост за год в году якоря: оставшиеся кварталы достраивают год до цели одним темпом
            full_prev = sum(_c_fact_line(A, "fees_net", y - 1, q) for q in range(1, QY + 1))
            done = sum(_c_fact_line(A, "fees_net", y, q) for q in range(1, qa + 1))
            g_rest = (full_prev * (1.0 + ov[y]) - done) / sum(fees_b) - 1.0
            f_q = [x * (1.0 + g_rest) for x in fees_b]
        elif y in ov:
            f_q = [x * (1.0 + ov[y]) for x in fees_b]
        elif v is None or not link_f:
            gvw = c_bget(B, "fees.growth_vs_wages")
            f_q = [fees_b[j] * (1.0 + wage[j] + c_traj_at(gvw, y, q)) for j, q in enumerate(qs)]
        else:
            gvw = c_bget(B, "fees.growth_vs_wages")
            f_q = [fees_b[j] * (1.0 + wage[j] + c_traj_at(gvw, y, q) + link_f * (v - wage[j]))
                   for j, q in enumerate(qs)]
        if v is None or not link_c:
            o_q = [x * (1.0 + wage[j]) * (1.0 + c_traj_at(rg, y, qs[j])) for j, x in enumerate(opex_b)]
        else:
            o_q = [x * (1.0 + wage[j] + link_c * (v - wage[j])) * (1.0 + c_traj_at(rg, y, qs[j]))
                   for j, x in enumerate(opex_b)]
        if v is None or not link_i:
            i_q = [x * (1.0 + wage[j] + c_traj_at(igw, y, qs[j])) for j, x in enumerate(ins_b)]
        else:
            i_q = [x * (1.0 + wage[j] + c_traj_at(igw, y, qs[j]) + link_i * (v - wage[j]))
                   for j, x in enumerate(ins_b)]
        return f_q, o_q, i_q

    # рост объёма периода v (М§4.7) — годовая форма: сумма средних остатков базы кварталов периода к
    # сумме тех же кварталов прошлого года; база iea считается в цикле баланса (зависит от LA)
    link_base = ctx["link_base"]
    funds_path = [a + b for a, b in zip(fr_path, cf_path)]
    v_now = None
    if link_on and link_base != LINK_BASES[-1]:
        ends = loans_path if link_base == LINK_BASES[0] else funds_path
        v_now = c_volume_growth(ctx, st, link_base, y, qs, sum((a + b) / 2.0 for a, b in zip(ends, ends[1:])))
    fees_q, opex_q, ins_q = c_volume_lines(v_now)
    fees, opex, ins = sum(fees_q), sum(opex_q), sum(ins_q)
    idx, I = [], st["I"]
    for j in range(n):
        I *= (1.0 + wd["cpi"][j]) ** (1.0 / QY)
        idx.append(I)
    # Годовые суммы книги (М§0.3, §4.7): квартал = год × доля квартала × индекс цен мира; у «прочего» —
    # доли other.misc_quarter_shares, у непрофильного — 1/4. В году якоря правила разные:
    # непрофильный результат закрывает год остатком (книга − факт отчётных кварталов, поровну на
    # оставшиеся кварталы); «прочее» остатком не закрывается — уровень книги × доля квартала, как в
    # любом году, сумма года — выход модели
    m_sh = ctx["misc_shares"]
    even = {h: 1.0 / QY for h in range(1, QY + 1)}
    nc_q = _c_book_quarters(ctx, p, idx, "noncore.result_real", even, residual_of="noncore_net")
    ms_q = _c_book_quarters(ctx, p, idx, "other.misc_net_real", m_sh)
    noncore, misc = sum(nc_q), sum(ms_q)
    one = 0.0
    if r == R_CRISIS:
        ol = c_bget(B, "regimes.crisis.one_off_loss")
        oy, oq = c_per_parse(ol["period"])
        if oy == y and oq in qs:
            one = float(ol["amount"])
    tau_stat = [c_traj_at(c_bget(B, "tax.statutory"), y, q) for q in qs]
    tau_eff = sum(tau_stat) / n + c_bnum(B, "tax.effective_gap")
    ot = 0.0
    if int(c_bnum(B, "tax.one_off.year")) == y and 1 in qs:
        ot = c_bnum(B, "tax.one_off.prob") * c_bnum(B, "tax.one_off.amount")
    nci = c_bnum(B, "pnl.nci_share")
    tenor = c_bget(B, "oci.fvoci_tenor")
    y_end = wd[tenor][-1]
    y_prev = st["y_tenor"]
    M, D = c_bnum(B, "oci.fvoci_maturity"), c_bnum(B, "oci.fvoci_duration")
    pull = 1.0 - 0.25 / M
    # переоценка FVOCI по кварталам смены полугодия мира, с подтягиванием к номиналу до конца периода
    path_y = [y_prev] + list(wd[tenor])
    reval = sum((path_y[j + 1] - path_y[j]) * pull ** (n - 1 - j) for j in range(n))
    fvos = c_bnum(B, "oci.fvoci_share")
    cpn = A["cpn_annual"] if A["cpn_quarter"] in qs else 0.0
    cpn_tau = c_traj_at(c_bget(B, "tax.statutory"), y, A["cpn_quarter"]) if cpn else 0.0
    om = sum(c_traj_at(c_bget(B, "equity.other_movements"), y, q) for q in qs)
    nim_shift = c_traj_mean(c_bget(B, f"regimes.{r}.nim_shift"), y, qs)
    fvr_on = bool(c_bget(B, "other.fvtpl_bond_reval"))
    hq = qs[-1]
    paid_shift, dp_end, dpreg, left = 0.0, 0.0, 0.0, []
    if plan is None:
        agm = int(c_bnum(B, "dividends.calendar.agm_quarter"))
        pay_q = int(c_bnum(B, "dividends.calendar.payment_quarter"))
        reg_q = int(c_bnum(B, "dividends.calendar.reg_deduction_quarter"))
        declared_here = agm in qs       # и в неполном году якоря: решение — в своём квартале (М§17)
        # Дивиденды к выплате (М§5.4): каждая объявленная сумма несёт свои кварталы выплаты и вычета из
        # регуляторного капитала — по датам записи реестра (declared | paid), без записи или без даты в
        # ней — по календарю книги. Просроченная выплата (квартал записи раньше периода) уходит в первом
        # квартале.
        items = [dict(it) for it in st["pay"]]
        if declared_here and div:
            items.append({"amt": div, **_c_dividend_dates(ctx, y - 1)})
        div_list = [(qs.index(agm), div)] if (declared_here and div) else []
    else:
        # квартальный режим (М§5.7): очереди выплат и вычетов — номерами кварталов сетки; постоянная часть
        # остатка «дивиденды к выплате» якоря не выплачивается и в регуляторный капитал не возвращается
        items = []
        k_first = c_qidx(ctx["anchor"], y, qs[0])
        k_last = k_first + n - 1
        dp_end = st["dp_perm"]
        by_quarter = [0.0] * n
        for it in plan["divs"]:
            by_quarter[it["dec"] - k_first] += it["amt"]
        div = sum(by_quarter)
        div_list = [(j, amt) for j, amt in enumerate(by_quarter) if amt]
        for it in [dict(x) for x in st["dq"]] + [dict(x) for x in plan["divs"]]:
            if it["pay"] <= k_last:
                j_pay = max(it["pay"], k_first) - k_first
                paid_shift += ((n - (j_pay + 1) + 0.5) / n - 0.5) * it["amt"]
            else:
                dp_end += it["amt"]
            if it["reg"] > k_last:
                dpreg += it["amt"]
            if it["pay"] > k_last or it["reg"] > k_last:
                left.append(it)
    # Время капитальных потоков в среднем остатке балансирующих статей (М§4.2 шаг 5, §4.10):
    # предварительный баланс квартала — при BV_(q−1) − Div_q и DP_q, поэтому доход квартала j входит в
    # активы со следующего квартала — вес (n − j)/n (доход внутри года неравномерен: сезонность
    # расходов и комиссий, профиль CoR, — поэтому вес берётся по квартальному профилю дохода, а не
    # (n − 1)/(2n) равномерного); объявление дивиденда ликвидность не меняет, а выплата уменьшает её
    # уже на конец своего квартала — вес (n − j_выплаты + ½)/n. Оба — вместо ½ у полусуммы начала и конца.
    w_ci = [(n - (j + 1)) / n - 0.5 for j in range(n)]
    for it in items:
        when = it["pay"]
        if when is None:
            q_pay = pay_q if pay_q in qs else None
        elif when < (y, qs[0]):
            q_pay = qs[0]
        else:
            q_pay = when[1] if (when[0] == y and when[1] in qs) else None
        if q_pay is None:
            left.append(it)
            dp_end += it["amt"]
        else:
            paid_shift += ((n - (qs.index(q_pay) + 1) + 0.5) / n - 0.5) * it["amt"]
        # DPreg: + Div на конец квартала ГОСА, 0 с конца квартала отсечки (М§4.11, §5.4)
        reg = it["reg"] if it["reg"] is not None else (it["agm_year"], reg_q)
        if (it["agm_year"], agm) <= (y, hq) < reg:
            dpreg += it["amt"]
    at1, ncib = A["AT1"], A["NCI"]
    m_liq = c_bnum(B, "volumes.liquid_min_share")
    ssl = c_bnum(B, "volumes.securities_share_of_liquid")
    dia = c_bnum(B, "nii.dia_rate")

    def c_grow_w(base, start, end):
        g = end / start if start > 0.0 and end > 0.0 else 1.0
        w = [b_ * g ** ((j + 0.5) / n) for j, b_ in enumerate(base)]
        tot = sum(w)
        return [x / tot for x in w] if tot else [d / p["days"] for d in days_q]

    if paths is None:
        w_cr = c_grow_w([c * d for c, d in zip(cor_prof, days_q)], sum(st["E"][b] for b in loans), sum_loans)
    else:
        # путь кредитов задан планом: вес квартала — CoR × дни × средний остаток кредитов квартала
        w_cr = [c * d * (a + b) / 2.0 for c, d, a, b in zip(cor_prof, days_q, loans_path, loans_path[1:])]
        tot_cr = sum(w_cr)
        w_cr = [x / tot_cr for x in w_cr] if tot_cr else [d / p["days"] for d in days_q]

    # --- балансирующие статьи и ОПУ: фиксированная точка по BV на конец (М§4.10 в годовом виде)
    bv_end = st["BV"] + st.get("ci_guess", 0.0) - div
    ci = st.get("ci_guess", 0.0)
    ci_q = [ci / n] * n
    asset_books = [b for b, sp in books.items() if sp["side"] == LOANS_SIDE]
    one_at = c_per_parse(c_bget(B, "regimes.crisis.one_off_loss.period")) if one else None
    om_q = [c_traj_at(c_bget(B, "equity.other_movements"), y, q) for q in qs]
    ov_q = [c_traj_at(c_bget(B, "regimes.near_nim_shift"), y, q) + c_traj_at(c_bget(B, f"regimes.{r}.nim_shift"), y, q)
            + _c_dev_at(dev.get("nim"), y, q) for q in qs]              # сдвиги ЧПМ квартала (М§4.4)
    for _ in range(FIT_ITER):
        liab_nb = fr1 + cf1 + wh_base + OL + dp_end + at1 + ncib
        assets_nb = sum_loans - AL + OA
        la = liab_nb + bv_end - assets_nb
        la_min = m_liq * assets_nb / (1.0 - m_liq)
        extra = max(0.0, la_min - la)
        la = max(la, la_min)
        E[SECURITIES], E[LIQUIDITY], E[WHOLESALE] = ssl * la, (1.0 - ssl) * la, wh_base + extra
        avg = dict(avg_nb)
        shift_la = sum(w * c for w, c in zip(w_ci, ci_q)) - paid_shift + curve_la
        la_avg = (la0 + la) / 2.0 + shift_la
        extra_avg = (extra0 + extra) / 2.0
        if extra0 > 0.0 and extra > 0.0:
            # минимум ликвидности связывает на обоих концах периода: LA стоит на минимуме весь период, а
            # время капитальных потоков и кривизну несёт добор опта (он — разность минимума и свободной LA)
            la_avg = m_liq / (1.0 - m_liq) * assets_nb_avg
            extra_avg = la_avg - ((la0 - extra0 + la - extra) / 2.0 + shift_la)
        avg[SECURITIES], avg[LIQUIDITY] = ssl * la_avg, (1.0 - ssl) * la_avg
        avg[WHOLESALE] = wtf * funds_avg + extra_avg
        iea = sum(avg[b] for b in asset_books)
        if link_on and v_now is None:
            # база объёма — средние процентные активы шага (М§4.7)
            fees_q, opex_q, ins_q = c_volume_lines(c_volume_growth(ctx, st, link_base, y, qs, iea * n))
            fees, opex, ins = sum(fees_q), sum(opex_q), sum(ins_q)
        inc = sum(ybar[b] * avg[b] for b in asset_books) * dfac
        exp_ = sum(ybar[b] * avg[b] for b in books if b not in asset_books) * dfac
        dia_amt = dia * fr_avg * dfac
        ovl = (near + nim_shift + d_nim) * iea * dfac      # ближний сдвиг + сдвиг режима + A-P2u (М§4.4)
        nii = inc - exp_ - dia_amt + ovl
        fvr = 0.0
        if fvr_on:
            fvr = -(c_bnum(B, "oci.fvtpl_bond_duration") * (y_end - y_prev)
                    * c_bnum(B, "oci.fvtpl_bond_share") * avg[SECURITIES])
        pbt = nii - llp - fvc + fees + ins + misc + fvr + noncore - opex + one
        tax = tau_eff * pbt
        ni = pbt - tax - ot
        ni_sh = ni * (1.0 - nci)
        r_end = st["R"] * pull ** n - D * reval * fvos * avg[SECURITIES] * (1.0 - sum(tau_stat) / n)
        oci = r_end - st["R"]
        ci = ni_sh - cpn * (1.0 - cpn_tau) + oci + om
        # ЧПМ квартала внутри периода (ожидание A-P2u, М§12, и профиль ЧПД): ставки квартала y_q при
        # структуре баланса периода; сдвиги ЧПМ (ближний, режима, отклонение A-P2u) — квартала
        nim_q = []
        for j, q in enumerate(qs):
            d_rate = sum((y_q[b][j] - ybar[b]) * avg[b] * (1.0 if b in asset_books else -1.0) for b in books) / iea
            nim_q.append(nii / iea / dfac + d_rate + ov_q[j] - (near + nim_shift + d_nim))
        # профиль прибыли внутри периода (для времени капитальных потоков, E_q, точек проверки и
        # капитала на дату оценки): ЧКД, расходы, страхование, «прочее» и непрофильный — свои кварталы;
        # ЧПД — по дням × ЧПМ квартала × рост процентных активов внутри периода (геометрически от начала
        # к концу), резервы — по CoR квартала × дни × рост кредитов, FVC — свои кварталы, FVR — по дням;
        # разовый убыток и купон AT1 — в своих кварталах; фонд FVOCI — квартальной рекурсией М§4.9 на
        # среднем портфеле периода (OCI квартала — его приращение)
        w_nii = c_grow_w([d * m for d, m in zip(days_q, nim_q)] if min(nim_q) > 0.0 else days_q,
                         sum(st["E"][b] for b in asset_books), sum(E[b] for b in asset_books))
        r_q, rr = [], st["R"]
        for j in range(n):
            rr = rr * pull - D * (path_y[j + 1] - path_y[j]) * fvos * avg[SECURITIES] * (1.0 - sum(tau_stat) / n)
            r_q.append(rr)
        oci_q = [r_q[0] - st["R"]] + [r_q[j] - r_q[j - 1] for j in range(1, n)]
        ni_q, ci_q = {}, []
        for j, q in enumerate(qs):
            pbt_q = (nii * w_nii[j] + fvr * days_q[j] / p["days"] - llp * w_cr[j] - fvc_q[j]
                     + fees_q[j] + ins_q[j] + ms_q[j] + nc_q[j] - opex_q[j] + (one if one_at == (y, q) else 0.0))
            ni_q[(y, q)] = (pbt_q * (1.0 - tau_eff) - (ot if q == 1 else 0.0)) * (1.0 - nci)
            ci_q.append(ni_q[(y, q)] - (cpn * (1.0 - cpn_tau) if q == A["cpn_quarter"] else 0.0)
                        + oci_q[j] + om_q[j])
        new_bv = st["BV"] + ci - div
        done = abs(new_bv - bv_end) <= FIT_TOL * max(1.0, abs(new_bv))
        bv_end = new_bv
        if done:
            break


    # --- RWA и нормативы (М§4.11–§4.12) на конец периода
    dens = c_bget(B, "capital.rwa.density")
    dn = st["Dn"] * ((1.0 + c_bnum(B, "capital.rwa.density_drift_rate")) ** frac
                     if y <= int(c_bnum(B, "capital.rwa.density_drift_until")) else 1.0)
    fxp, xf, xf_q = st["fxp"], 1.0, [1.0] * n
    if c_bget(B, "capital.rwa.fx.enabled"):
        fx, pistar = c_bnum(B, "capital.rwa.fx.share"), c_bnum(B, "capital.rwa.fx.foreign_inflation")
        for j in range(n):
            fxp *= ((1.0 + wd["cpi"][j]) / (1.0 + pistar)) ** (1.0 / QY)
            xf_q[j] = 1.0 - fx + fx * fxp
        xf = 1.0 - fx + fx * fxp
    rwa = _c_rwa_of(ctx, r, y, hq, E, OA, dn, xf)
    drifting = y <= int(c_bnum(B, "capital.rwa.density_drift_until"))
    dn_q = [st["Dn"] * ((1.0 + c_bnum(B, "capital.rwa.density_drift_rate")) ** ((j + 1) / QY) if drifting else 1.0)
            for j in range(n)]
    cap = _c_capital(ctx, s, y, hq, bv_end, dpreg, r_end, rwa, {**st["ni_q"], **ni_q})
    row.update(nii=nii, llp=llp, fvc=fvc, fees=fees, opex=opex, ins=ins, misc=misc, noncore=noncore,
               fvr=fvr, one_off=one, pbt=pbt, tax=tax, ot=ot, ni=ni, ni_sh=ni_sh, oci=oci,
               cpn=cpn, cpn_net=cpn * (1.0 - cpn_tau), om=om, ci=ci, div=div, bv=bv_end, R=r_end, R_q=r_q,
               loans=sum_loans, loans_ac=loans_ac, iea=iea, iea_end=sum(E[b] for b in asset_books), funds=fr1 + cf1,
               securities=E[SECURITIES], liquidity=E[LIQUIDITY], wholesale=E[WHOLESALE],
               wholesale_extra=extra, oa=OA, ol=OL, al=AL, dp=dp_end, dpreg=dpreg, rwa=rwa,
               assets=sum_loans - AL + E[SECURITIES] + E[LIQUIDITY] + OA,
               liabilities=fr1 + cf1 + E[WHOLESALE] + OL + dp_end + bv_end + at1 + ncib,
               nim=nii / iea / dfac, nim_books=(nii - ovl) / iea / dfac, nim_q=nim_q,
               cor=cor_c, cor_mgmt=(c_to_mgmt(A, "cor", cor_c) if c_bget(B, "regimes.cor_basis") == "mgmt"
                                    else cor_c),
               cir=opex / (nii + fees + ins + misc + fvr) if (nii + fees + ins + misc + fvr) else None,
               roe=ni_sh / ((st["BV"] + bv_end) / 2.0), y_liq_end=Ynew[LIQUIDITY],
               y_sec_end=Ynew[SECURITIES], c_wh_end=Ynew[WHOLESALE],
               tau_eff=tau_eff, share_target=share_target, c=c1, ni_q=ni_q, ci_q=ci_q, shift_la=shift_la,
               near=near, nim_shift=nim_shift, misc_q=ms_q, noncore_q=nc_q, fvc_q=fvc_q,
               cor_q=cor_prof, cor_ref_q=ref_prof, idx_q=idx, fv_avg_q=fv_avg_q, days_q=days_q,
               loans_ac_avg=loans_ac_avg, paid_shift=paid_shift, curve_la=curve_la, la_avg=la_avg,
               wholesale_avg=avg[WHOLESALE], assets_nb_avg=assets_nb_avg, funds_avg=funds_avg,
               x_q=x_w, rates_end=dict(Ynew), div_list=div_list, m_q=m_q, fr_path=fr_path, cf_path=cf_path,
               loans_path=loans_path, loans_ac_ends=ac_path, dn_q=dn_q, xf_q=xf_q, v_volume=v_now,
               books_end={b: E[b] for b in loans},
               fees_q=fees_q, opex_q=opex_q, ins_q=ins_q, **cap)
    qv = dict(st["qv"])
    for j, q in enumerate(qs):
        qv[("fees_net", y, q)], qv[("opex", y, q)], qv[("insurance_net", y, q)] = fees_q[j], opex_q[j], ins_q[j]
    nst = {"E": E, "y": Ynew, "c": c1, "BV": bv_end, "R": r_end, "pay": left, "Dn": dn,
           "fxp": fxp, "I": I, "y_tenor": y_end, "D": st["D"], "ci_guess": ci,
           "ni_q": {**st["ni_q"], **ni_q}, "qv": qv}
    if plan is not None:
        nst.update(pay=[], dq=left, dp_perm=st["dp_perm"], Epot=st["Epot"])
    if link_on:
        # концы кварталов базы объёма — для роста «к тому же кварталу прошлого года» (М§4.7)
        vend = dict(st.get("vend", {}))
        for j, q in enumerate(qs):
            vend[(y, q)] = {LINK_BASES[0]: loans_path[j + 1], LINK_BASES[1]: funds_path[j + 1],
                            LINK_BASES[-1]: iea}
        nst["vend"] = vend
    return nst, row


PART_LETTERS = ("Q", "H")                 # буквы части года в ключе времени траектории: квартал и полугодие
PART_KEY_FORM = PART_LETTERS[0] + "n"      # форма хвоста ключа части года: буква и номер


def c_premium(B: dict, key: str, names: tuple, name: str, y: int, quarters=None) -> float:
    """Премия роста года (М§4.3): число (одна на все книги — форма образца) или словарь траекторий с
    ключами ровно names; значение словаря — значение траектории года. `quarters` — кварталы периода (их
    передаёт только премия средств клиентов): квартал, заданный в траектории ключом квартала или полугодия,
    читается этим ключом, квартал без такого ключа — значением года; премия периода — среднее его кварталов."""
    val = c_bget(B, key)
    if isinstance(val, dict):
        if sorted(str(k) for k in val) != sorted(names):
            raise ControlInputError(f"{key}: ключи словаря — не ровно {', '.join(names)} (М§4.3)")
        traj = val[name]
        timed = isinstance(traj, dict) and quarters is not None and any(c_premium_keyed(traj, y, q) for q in quarters)
        if not timed:
            return c_traj_mean(traj, y, range(1, QY + 1))
        plain = {k: v for k, v in traj.items() if not c_is_part_key(k)}      # значение года — без ключей частей года
        year = c_traj_mean(plain, y, range(1, QY + 1))
        return sum(c_traj_at(traj, y, q) if c_premium_keyed(traj, y, q) else year for q in quarters) / len(quarters)
    return c_bnum(B, key)


def c_is_part_key(key) -> bool:
    """Ключ квартала или полугодия траектории: год, буква части года (Q или H), номер части."""
    key = str(key)
    year, part = key[:-len(PART_KEY_FORM)], key[-len(PART_KEY_FORM):]
    return year.isdigit() and part[:len(PART_LETTERS[0])] in PART_LETTERS and part[len(PART_LETTERS[0]):].isdigit()


def c_premium_keyed(traj: dict, y: int, q: int) -> bool:
    """Квартал q года y задан в траектории ключом квартала или ключом своего полугодия."""
    names = {str(k) for k in traj}
    return f"{y}Q{q}" in names or f"{y}H{1 if q <= 2 else 2}" in names


def c_volume_growth(ctx: dict, st: dict, base: str, y: int, qs, now: float) -> float:
    """Рост объёма периода v (М§4.7) в годовой форме: now — сумма средних остатков базы по кварталам
    периода; делитель — та же сумма по тем же кварталам прошлого года (концы кварталов до якоря — факты
    balance.history, конец якоря — остатки якоря, позже — путь клетки)."""
    A, anchor = ctx["A"], ctx["anchor"]
    last = LINK_BASES[-1]

    def c_end(yy, qq):
        if (yy, qq) > anchor:
            return st["vend"][(yy, qq)][base]
        if (yy, qq) == anchor:
            E0, books = A["E0"], ctx["books"]
            if base == LINK_BASES[0]:
                return sum(E0[b] for b in ctx["loans"])
            if base == last:
                return sum(E0[b] for b, sp in books.items() if sp["side"] == LOANS_SIDE)
            return E0[RETAIL_CURRENT] + E0[RETAIL_TERM] + sum(E0[b] for b in ctx["biz"])
        val = A["history"].get(f"{yy}Q{qq}", {}).get(base)
        if val is None:
            raise ControlInputError(f"нет конца квартала balance.history.{yy}Q{qq}.{base} для связи с объёмом (М§4.7)")
        return float(val)

    prev = 0.0
    for q in qs:
        yy, qq = y - 1, q
        if base == last and (yy, qq) > anchor:
            prev += st["vend"][(yy, qq)][base]          # средние процентные активы шага того квартала
            continue
        py, pq = (yy - 1, QY) if qq == 1 else (yy, qq - 1)
        prev += (c_end(py, pq) + c_end(yy, qq)) / 2.0
    if prev <= 0.0:
        raise ControlInputError("база объёма прошлого года не положительна (М§4.7)")
    return now / prev - 1.0


def _c_rwa_of(ctx: dict, r, y: int, q: int, E: dict, OA: float, dn: float, xf: float) -> float:
    """RWA (М§4.11): плотности книг и прочих активов × дрейф плотности × валютный индекс × множитель
    режима. Постоянные прочие активы входят со своей плотностью; r = None — RWA_0 якоря (без множителя)."""
    dens, oaf = ctx["dens"], ctx["oaf"]
    base = sum(float(dens[b]) * E[b] for b in ctx["books"] if b in dens)
    if oaf:
        base = base + float(dens["other_assets"]) * (OA - oaf) + ctx["dens_oaf"] * oaf
    else:
        base = base + float(dens["other_assets"]) * OA
    rwa = base * dn * xf
    mult = ctx["rwa_mult"].get(r) if r is not None else None
    if mult is not None:
        rwa = rwa * c_traj_at(mult, y, q)               # роспуск надбавок режима — на все RWA клетки
    return rwa


def c_qidx(anchor: tuple, y: int, q: int) -> int:
    """Номер квартала (y, q) на сетке: якорь — 0, первый прогнозный — 1 (М§0.2)."""
    return (y - anchor[0]) * QY + (q - anchor[1])


def c_qper(anchor: tuple, k: int) -> tuple[int, int]:
    """Квартал сетки с номером k → (год, квартал в году)."""
    pos = anchor[0] * QY + (anchor[1] - 1) + k
    return pos // QY, pos % QY + 1


def c_qidx_of_date(anchor: tuple, d: dt.date) -> int:
    """Номер календарного квартала сетки, содержащего дату (М§5.7.2)."""
    return c_qidx(anchor, d.year, (d.month - 1) // 3 + 1)


def _c_dev_at(dv, y: int, q: int) -> float:
    """Затухающее отклонение A-P2u в квартале (y, q): ρ^k × m — от последнего наблюдения окна не позже
    этого квартала, k — кварталов после него (М§12). Квартал раньше первого наблюдения окна — ноль;
    наблюдённый квартал несёт своё отклонение, даже если за ним в окне есть более позднее."""
    if not dv:
        return 0.0
    last = None
    for ys, qs, m in dv["trail"]:
        if (ys, qs) <= (y, q):
            last = (ys, qs, m)
    if last is None:
        return 0.0
    return dv["rho"] ** ((y - last[0]) * QY + (q - last[1])) * last[2]


def c_cor_path_engine(ctx: dict, r: str, y: int, q: int) -> float:
    """Путь CoR режима в квартале в базисе движка (мост при cor_basis: mgmt, М§3.2, §4.6)."""
    c = c_traj_at(c_bget(ctx["B"], f"regimes.{r}.cor"), y, q)
    return c_to_engine(ctx["A"], "cor", c) if c_bget(ctx["B"], "regimes.cor_basis") == "mgmt" else c


def c_cor_ref_engine(ctx: dict, y: int, q: int) -> float:
    """Опора FVC в квартале (М§4.6): путь режима credit.fv_loans_ref книги-опоры — до розыгрыша осей,
    чувствительностей и поисков — в базисе движка."""
    B0 = ctx["B0"]
    c = c_traj_at(c_bget(B0, f"regimes.{ctx['fv_ref']}.cor"), y, q)
    return c_to_engine(ctx["A"], "cor", c) if c_bget(B0, "regimes.cor_basis") == "mgmt" else c


def _c_yoy_quarters(ctx: dict, st: dict, line: str, y: int, qs) -> list[float]:
    """База «к тому же кварталу прошлого года» по кварталам периода (М§0.3): факт до якоря
    включительно, иначе квартал прошлого года клетки."""
    A = ctx["A"]
    y0, qa = ctx["anchor"]
    out = []
    for q in qs:
        if (y - 1, q) <= (y0, qa):
            out.append(_c_fact_line(A, line, y - 1, q))
        else:
            out.append(st["qv"][(line, y - 1, q)])
    return out


def _c_book_quarters(ctx: dict, p: dict, idx: list[float], key: str, shares: dict,
                     residual_of: str | None = None) -> list[float]:
    """Годовая сумма книги по кварталам периода (М§0.3, §4.7): год × доля квартала × индекс цен.
    residual_of — строка фактов, которой год якоря закрывается остатком (книга − факт отчётных
    кварталов, по долям оставшихся кварталов): так считается непрофильный результат. Без неё
    («прочее») оставшиеся кварталы года якоря — та же формула, что в прочие годы."""
    B, A = ctx["B"], ctx["A"]
    y, qs = p["year"], p["quarters"]
    yearly = c_traj_mean(c_bget(B, key), y, range(1, QY + 1))
    if residual_of is None or not p["stub"]:
        return [yearly * shares[q] * idx[j] for j, q in enumerate(qs)]
    qa = ctx["anchor"][1]
    rest = yearly - sum(_c_fact_line(A, residual_of, y, q) for q in range(1, qa + 1))
    tot = sum(shares[q] for q in qs)
    if tot <= 0.0:
        raise ControlInputError(f"{key}: доли оставшихся кварталов года якоря в сумме 0 — остаток некуда разложить")
    return [rest * shares[q] / tot * idx[j] for j, q in enumerate(qs)]


def _c_capital(ctx: dict, s: str, y: int, h: int, bv: float, dpreg: float, R: float, rwa: float,
             ni_q: dict) -> dict:
    """K20, K11, Н20.0 и второй норматив (слот n11: отчётный и с прибылью периода), требования и полы в
    квартале (y, h) (М§4.11–§4.12)."""
    B = ctx["B"]
    f = c_bnum(B, "capital.n20.fvoci_recognition")
    bvreg = bv + dpreg - (1.0 - f) * R
    ratio = rwa / ctx["rwa0"]
    t2 = c_traj_at(c_bget(B, "capital.n20.t2"), y, h)
    k20 = bvreg - c_bnum(B, "capital.n20.deductions_anchor") * ratio + ctx["A"]["AT1"] + t2
    cut = [int(c) for c in c_bget(B, "capital.n11.audit_cutoffs")]
    e_q = _c_unaudited_quarters(cut, y, h)
    missing = [yq for yq in e_q if yq not in ni_q]
    if missing:
        raise ControlInputError(f"нет прибыли кварталов {missing} для E_q")
    e_un = sum(ni_q[yq] for yq in e_q)
    # из базового капитала исключается только прибыль неаудированного периода; убыток — уже в BV (М§4.11)
    e_out = e_un if e_un > 0.0 else 0.0
    k11 = bvreg - e_out - c_bnum(B, "capital.n11.deductions_anchor") * ratio
    dp20 = c_traj_at(c_bget(B, f"capital.reg_scenarios.{s}.deduction_pp.n20_0"), y, h)
    dp11 = c_traj_at(c_bget(B, f"capital.reg_scenarios.{s}.deduction_pp.n1_1"), y, h)
    n20 = k20 / rwa + c_bnum(B, "capital.n20.gap_pp") - dp20
    n11 = k11 / rwa + c_bnum(B, "capital.n11.gap_pp") - dp11
    n11_star = (k11 + e_out) / rwa + c_bnum(B, "capital.n11.gap_pp") - dp11
    fl20, fl11 = _c_floor(B, s, "n20_0", y, h), _c_floor(B, s, "n1_1", y, h)
    return {"k20": k20, "k11": k11, "n20": n20, "n11": n11, "n11_star": n11_star, "e_unaudited": e_un,
            "floor20": fl20, "floor11": fl11,
            "req20": max(c_bnum(B, "dividends.policy.threshold"), fl20 + c_bnum(B, "capital.mgmt_buffer.n20_0")),
            "req11": fl11 + c_bnum(B, "capital.mgmt_buffer.n1_1")}


def _c_start_state(ctx: dict) -> dict:
    A, B = ctx["A"], ctx["B"]
    tenor = c_bget(B, "oci.fvoci_tenor")
    node = tenor.split("_")[1].rstrip("y")
    ni_q = {}
    for per, rec in A["pnl"].items():
        if rec.get("ni_shareholders") is not None:
            ni_q[c_per_parse(per)] = float(rec["ni_shareholders"])
    fr = A["E0"][RETAIL_CURRENT] + A["E0"][RETAIL_TERM]
    # дивиденд, объявленный до даты фактов, уже вычтен из BV якоря; сумма к выплате — факт баланса,
    # кварталы выплаты и вычета — по записи реестра за этот год прибыли (ГОСА — в году якоря, не позже
    # якоря: иначе контекст отказал бы), иначе по календарю (М§5.4)
    start = {"E": dict(A["E0"]), "y": dict(A["rate0"]), "c": A["E0"][RETAIL_CURRENT] / fr,
             "BV": A["BV"], "R": A["R0"], "Dn": 1.0, "fxp": 1.0, "I": 1.0,
             "y_tenor": A["curve0"][node], "D": 0.0, "ni_q": ni_q, "qv": {}}
    if ctx["quarterly"]:
        # состояние якоря квартального режима (М§5.7.4): объявленная часть остатка — в очередях выплат и
        # вычетов, остаток — постоянное обязательство; уровни потенциального пути — остатки якоря (М§4.13.1)
        cal = ctx["divcal"]
        start.update(pay=[], dq=[dict(it) for it in cal["queue0"]], dp_perm=cal["perm"],
                     Epot={b: A["E0"][b] for b in ctx["loans"]})
        return start
    profit_year = ctx["anchor"][0] - 1 if A["DP_year"] is None else int(A["DP_year"])
    start["pay"] = [{"amt": A["DP"], **_c_dividend_dates(ctx, profit_year)}] if A["DP"] else []
    return start


# ============================================================================ дивиденды (М§5) в годовом шаге

REGISTER_BINDING = ("declared", "paid")   # объявленное — обязательство; `recommended` — только плашка (М§15.1)


def _c_register_binding(ctx: dict) -> list[dict]:
    """Записи реестра с объявленным дивидендом (решение ГОСА принято: declared или уже paid)."""
    return [rec for rec in ctx["A"]["register"] if rec.get("status", "declared") in REGISTER_BINDING]


def _c_register_rec(ctx: dict, year: int):
    for rec in _c_register_binding(ctx):
        if int(_c_nodeval(rec.get("year"))) == year:
            return rec
    return None


def _c_register_dps(ctx: dict, year: int):
    rec = _c_register_rec(ctx, year)
    return None if rec is None else float(_c_nodeval(rec["dps"]))


def _c_dividend_dates(ctx: dict, profit_year: int) -> dict:
    """Кварталы выплаты и вычета из регуляторного капитала дивиденда за год прибыли (М§5.4): у
    объявленной записи реестра (declared | paid) даты записи сильнее календаря книги — выплата в
    квартале pay_date, вычет в квартале отсечки record_date; нет записи или даты — None (календарь)."""
    out = {"agm_year": profit_year + 1, "pay": None, "reg": None}
    rec = _c_register_rec(ctx, profit_year)
    if rec is None:
        return out
    for key, field in (("pay", "pay_date"), ("reg", "record_date")):
        val = _c_nodeval(rec.get(field))
        if val:
            d = _c_as_date(val)
            out[key] = (d.year, (d.month - 1) // 3 + 1)
    return out


def _c_decide(ctx: dict, cell: dict, st: dict, i: int) -> tuple[float, dict]:
    """Решение года прибыли Y = год периода − 1: пробный проход, запас H, ступени, кризис, реестр."""
    B, A, p = ctx["B"], ctx["A"], ctx["periods"][i]
    yp = p["year"] - 1
    info = {"profit_year": yp}
    n_out, n_iss = A["N_out"], A["N_iss"]
    reg = _c_register_dps(ctx, yp)
    if reg is not None:
        info.update(kind="register", dps_register=reg)
        return reg * n_out / 1000.0, info
    if any((yp, q) not in st["ni_q"] for q in range(1, QY + 1)):
        raise ControlInputError(f"нет прибыли акционеров всех кварталов {yp} года для базы дивиденда (М§5.2)")
    ni_y = sum(v for (yy, _), v in st["ni_q"].items() if yy == yp)
    base = ni_y - (A["cpn_annual"] * (1.0 - c_traj_at(c_bget(B, "tax.statutory"), yp, A["cpn_quarter"]))
                   if c_bget(B, "dividends.policy.deduct_at1_after_tax") else 0.0)
    dev = c_traj_mean(c_bget(B, "dividends.payout_deviation"), yp, range(1, QY + 1))
    steps = c_bget(B, "dividends.policy.steps") or [
        {"payout": c_traj_mean(c_bget(B, "dividends.policy.payout"), yp, range(1, QY + 1)),
         "threshold": c_bnum(B, "dividends.policy.threshold")}]
    trial = _c_period(ctx, cell, st, i, 0.0)[1]
    cps = [int(c) for c in c_bget(B, "dividends.calendar.checkpoints")]
    y = p["year"]
    s = cell["scenario"]
    buf20 = c_bnum(B, "capital.mgmt_buffer.n20_0")
    hs = []
    for j, stp in enumerate(steps):
        pj = min(1.0, max(0.0, float(stp["payout"]) + dev))
        want = pj * max(0.0, base) * n_out / n_iss
        H = float("inf")
        for h in cps:
            # состояние в точке проверки h года y пробного прохода: капитал — BV начала года + CI
            # кварталов по h (квартальный профиль периода), фонд FVOCI — квартальная рекурсия, RWA —
            # геометрически между началом и концом года
            if h not in p["quarters"]:
                raise ControlInputError(f"точка проверки {h} вне кварталов периода {p['label']} (М§5.3)")
            j_h = p["quarters"].index(h)
            bv_h = st["BV"] + sum(trial["ci_q"][:j_h + 1])
            r_h = trial["R_q"][j_h]
            rwa_h = st["rwa"] * (trial["rwa"] / st["rwa"]) ** ((j_h + 1) / p["n"])
            ni_q = {**st["ni_q"], **trial["ni_q"]}
            cap = _c_capital(ctx, s, y, h, bv_h, 0.0, r_h, rwa_h, ni_q)
            req20 = max(float(stp["threshold"]), cap["floor20"] + buf20)
            H = min(H, (cap["n20"] - req20) * rwa_h, (cap["n11"] - cap["req11"]) * rwa_h)
        hs.append((want, H))
        if H >= want:
            base_div, H_used, step = want, H, j
            break
    else:
        want, H = hs[-1]
        base_div, H_used, step = max(0.0, min(want, H)), H, len(steps) - 1
    want1 = hs[0][0]
    info.update(kind="policy", base=base, want=want1, H=H_used, step=step, base_div=base_div)
    if (cell["regime"] == R_CRISIS and y == ctx["shock_year"]
            and c_bget(B, "dividends.crisis.skip_in_shock_year")):
        st["D"] += want1
        info.update(kind="crisis_skip")
        return 0.0, info
    catch = min(st["D"], max(0.0, H_used - base_div)) if c_bget(B, "dividends.crisis.catch_up") else 0.0
    eps = 0.0
    fy = int(c_bnum(B, "dividends.excess.from_profit_year"))
    if yp >= fy:
        # линейный ввод ε за ramp_years лет (М§5.3 п. 4): ε_Y = ε × min(1, (Y − from + 1)/ramp)
        ramp = int(c_bnum(B, "dividends.excess.ramp_years"))
        if ramp < 1:
            raise ControlInputError("dividends.excess.ramp_years — целое ≥ 1 (М прил. A)")
        eps = c_bnum(B, "dividends.excess.epsilon") * min(1.0, (yp - fy + 1) / ramp)
    exc = eps * max(0.0, H_used - base_div - catch)
    st["D"] -= catch
    info.update(catch=catch, excess=exc, eps=eps)
    return base_div + catch + exc, info


# ============================================================================ клетка целиком: путь, RI/DDM, терминал

def _c_cell_path(ctx: dict, cell: dict, upto_year: int | None = None) -> dict:
    """Годовой путь клетки и решения о дивидендах (до года upto_year включительно, если задан)."""
    B, A = ctx["B"], ctx["A"]
    st = _c_start_state(ctx)
    y0, qa = ctx["anchor"]
    cap0 = _c_capital(ctx, cell["scenario"], y0, qa, A["BV"], A["DP"], A["R0"], ctx["rwa0"], st["ni_q"])
    st["rwa"] = ctx["rwa0"]
    rows, decisions = [], {}
    if ctx["quarterly"]:
        # квартальный календарь (М§5.7) и рост, ограниченный капиталом (М§4.13): квартальный проход внутри года
        cap0 = _c_capital(ctx, cell["scenario"], y0, qa, A["BV"], c_dpreg_anchor(B, A), A["R0"], ctx["rwa0"],
                          st["ni_q"])
        made = []
        for i, p in enumerate(ctx["periods"]):
            if upto_year is not None and p["year"] > upto_year:
                break
            st, row = _c_year_quarterly(ctx, cell, st, i)
            st["rwa"] = row["rwa"]
            made.extend(row["decisions_q"])
            rows.append(row)
        out = {"rows": rows, "decisions": decisions, "anchor_capital": cap0, "decisions_q": made}
        if upto_year is None:
            out["decisions"] = c_profit_years(ctx, made)
        _c_year_margin(ctx, rows)
        return out
    agm = int(c_bnum(B, "dividends.calendar.agm_quarter"))
    for i, p in enumerate(ctx["periods"]):
        if upto_year is not None and p["year"] > upto_year:
            break
        div = 0.0
        if agm in p["quarters"] and not (p["stub"] and A["DP_year"] is not None
                                         and int(A["DP_year"]) == p["year"] - 1):
            # и в неполном году якоря: собрание после якоря решает в своём квартале (М§17), если факты не
            # говорят, что дивиденд за этот год прибыли уже объявлен и вычтен из BV якоря (М§5.4)
            div, info = _c_decide(ctx, cell, st, i)
            decisions[p["year"] - 1] = {**info, "div": div, "dps": div * 1000.0 / A["N_out"]}
        D_keep = st["D"]
        st, row = _c_period(ctx, cell, st, i, div)
        st["D"] = D_keep
        st["rwa"] = row["rwa"]
        row["D"] = D_keep
        rows.append(row)
    _c_year_margin(ctx, rows)
    return {"rows": rows, "decisions": decisions, "anchor_capital": cap0}


def _c_year_margin(ctx: dict, rows: list[dict]) -> None:
    """Годовые метрики движка по правилу печати (М§0.3): сумма года к среднему пяти концов кварталов — конец
    прошлого года и четыре конца года. ЧПМ — ЧПД к процентным активам, CoR — резервы к кредитам по
    амортизированной стоимости; C/I — расходы к доходу NII + F + INS + MISC + FVR (М§4.6). Концы кварталов —
    из квартального прохода капитала; у годовой ветви образца — геометрический путь между началом и концом
    года. Неполный год якоря значений не несёт (его годовая метрика смешивает факты отчётных кварталов,
    М§4.6)."""
    prev = ctx["tr"]["iea0"]
    for p, row in zip(ctx["periods"], rows):
        inner = ([x["iea"] for x in row["quarters"]] if "quarters" in row
                 else _c_geo_path(prev, row["iea_end"], p["n"])[1:])
        row["iea_ends"] = [prev] + inner
        row["income_cir"] = row["nii"] + row["fees"] + row["ins"] + row["misc"] + row["fvr"]
        row["nim_year"] = row["cor_year"] = row["cir_year"] = None
        if not p["stub"]:
            row["nim_year"] = row["nii"] / _c_ends_mean(row["iea_ends"])
            row["cor_year"] = row["llp"] / _c_ends_mean(row["loans_ac_ends"])
            row["cir_year"] = row["opex"] / row["income_cir"] if row["income_cir"] else None
        prev = row["iea_end"]


def _c_ends_mean(ends: list[float]) -> float:
    """Среднее концов кварталов года — знаменатель годового отношения (М§0.3)."""
    return sum(ends) / len(ends)


# ============================================================================ квартальный календарь дивидендов (М§5.7)

def c_div_calendar(B: dict, A: dict) -> dict:
    """Календарь квартального режима (М§5.7.2, §5.7.4), общий для клеток: правило закрытого квартала p_last
    по фактам, открытые кварталы прибыли с кварталами решения, вычета и выплаты (запись реестра сильнее
    карты лагов), состояние якоря — очереди объявленных дивидендов и постоянная часть остатка."""
    if "divcal" in A:
        return A["divcal"]
    anchor, facts_date = A["anchor"], A["facts_date"]
    cal = c_bget(B, "dividends.calendar")
    for key in ("decision_lag_quarters", "reg_deduction_lag_quarters", "payment_lag_quarters", "checkpoints_ahead"):
        if cal.get(key) is None:
            raise ControlInputError(f"dividends.calendar.{key}: нет ключа квартального режима (М§5.7.1)")
    if int(cal["checkpoints_ahead"]) != 0:
        raise ControlInputError("dividends.calendar.checkpoints_ahead: допустим только 0 (М§5.7.1)")
    lag_raw = cal["decision_lag_quarters"]
    if isinstance(lag_raw, dict):
        lags = {int(k): int(v) for k, v in lag_raw.items()}
        if sorted(lags) != list(range(1, QY + 1)):
            raise ControlInputError("dividends.calendar.decision_lag_quarters: ключи — не ровно 1…4 (М§5.7.1)")
    else:
        lags = {h: int(lag_raw) for h in range(1, QY + 1)}
    reg_lag, pay_lag = int(cal["reg_deduction_lag_quarters"]), int(cal["payment_lag_quarters"])
    if any(not 1 <= x <= QY for x in list(lags.values()) + [reg_lag, pay_lag]):
        raise ControlInputError("лаг календаря дивидендов вне 1…4 (М§5.7.1)")
    last_q = c_qidx(anchor, *c_per_parse(c_bget(B, "meta.last_period")))

    def c_day(rec, field):
        val = _c_nodeval(rec.get(field))
        return _c_as_date(val) if val else None

    def c_map(k):
        """Карта лагов квартала прибыли k: (квартал решения, вычета, выплаты)."""
        q_dec = k + lags[c_qper(anchor, k)[1]]
        return q_dec, max(q_dec, k + reg_lag), max(q_dec, k + pay_lag)

    # закрыт ли квартал прибыли до якоря, решает факт (М§5.7.2)
    closed, hist_dps = [], {}
    for rec in A["div_history"]:
        per = _c_nodeval(rec.get("period"))
        if not per:
            raise ControlInputError("строка dividends.history без квартала прибыли period (прил. B)")
        k = c_qidx(anchor, *c_per_parse(per))
        dps = _c_nodeval(rec.get("dps"))
        if dps is None:
            dps = _c_nodeval(rec.get("dps_ordinary"))
        hist_dps[k] = None if dps is None else float(dps)
        decided = c_day(rec, "decided_date")
        if decided is not None and decided <= facts_date:
            closed.append(k)
    if not closed:
        raise ControlInputError("в dividends.history нет решения не позже даты фактов: p_last не определён (М§5.7.2)")
    p_last = max(closed)
    register = {}
    for rec in A["register"]:
        if rec.get("status", "declared") not in REGISTER_BINDING:
            continue
        per = _c_nodeval(rec.get("period"))
        if not per:
            raise ControlInputError("запись реестра без квартала прибыли (М§5.7.6)")
        k = c_qidx(anchor, *c_per_parse(per))
        decided = c_day(rec, "decided_date")
        if k > p_last and decided is not None and decided <= facts_date:
            raise ControlInputError(f"запись реестра {per}: решение раньше даты фактов, а строки в истории "
                                    f"дивидендов нет (М§5.7.6)")
        q_dec, q_reg, q_pay = c_map(k)
        record, pay, ex = c_day(rec, "record_date"), c_day(rec, "pay_date"), c_day(rec, "ex_date")
        q_cell = max(1, q_dec, c_qidx_of_date(anchor, decided)) if decided is not None else max(1, q_dec)
        register[k] = {"p": k, "period": str(per), "dps": float(_c_nodeval(rec["dps"])), "q_cell": q_cell,
                       "R": c_qidx_of_date(anchor, record) if record is not None else q_reg,
                       "P": c_qidx_of_date(anchor, pay) if pay is not None else q_pay, "ex": ex}
    opened, by_q = {}, {}
    for k in range(p_last + 1, last_q):
        yy, hh = c_qper(anchor, k)
        q_dec, q_reg, q_pay = c_map(k)
        rec = register.get(k)
        q_cell = rec["q_cell"] if rec is not None else max(1, q_dec)
        if q_cell > last_q:
            continue                                    # решение остаётся терминалу (М§7)
        ent = {"p": k, "period": f"{yy}Q{hh}", "year": yy, "h": hh, "q_cell": q_cell,
               "q_reg": max(q_cell, rec["R"] if rec is not None else q_reg),
               "q_pay": max(q_cell, rec["P"] if rec is not None else q_pay),
               "dps_register": None if rec is None else rec["dps"]}
        opened[k] = ent
        by_q.setdefault(q_cell, []).append(ent)
    # состояние якоря: объявленные и не выплаченные дивиденды закрытых кварталов прибыли
    queue0, seen, total = [], set(), 0.0
    for it in A["DP_declared"]:
        k = c_qidx(anchor, *c_per_parse(it["period"]))
        if k > p_last:
            raise ControlInputError(f"balance.dividends_payable_declared: период {it['period']} не закрыт (М§5.7.4)")
        if k in seen:
            raise ControlInputError(f"balance.dividends_payable_declared: период {it['period']} повторяется")
        seen.add(k)
        rec = register.get(k)
        _, q_reg, q_pay = c_map(k)
        queue0.append({"amt": it["amount"], "dec": 0, "reg": rec["R"] if rec is not None else q_reg,
                       "pay": max(1, rec["P"] if rec is not None else q_pay)})
        total += it["amount"]
    if total > A["DP"] + 1e-9:
        raise ControlInputError("сумма balance.dividends_payable_declared больше остатка дивидендов к выплате")
    A["divcal"] = {"p_last": p_last, "open": opened, "by_q": by_q, "register": register, "queue0": queue0,
                   "perm": A["DP"] - total, "hist_dps": hist_dps, "last_q": last_q, "closed": sorted(closed)}
    return A["divcal"]


def c_dpreg_anchor(B: dict, A: dict) -> float:
    """DPreg на якоре (М§4.11): дивиденды, вычтенные из BV якоря, но ещё не вычтенные из регуляторного
    капитала. Квартальный режим — суммы очереди вычетов состояния якоря; годовой — остаток дивидендов к
    выплате (объявлен в квартал собрания, отсечка — позже якоря)."""
    if not c_is_quarterly(B):
        return A["DP"]
    return sum(it["amt"] for it in c_div_calendar(B, A)["queue0"] if it["reg"] >= 1)


def c_div_base(ctx: dict, ni_all: dict, k: int) -> float:
    """База решения за квартал прибыли k (М§5.7.3): средняя базы W последних кварталов; прибыль квартала
    не позже якоря — факт, позже — ряд клетки; купон бессрочных инструментов — в квартале его выплаты."""
    B, A, anchor = ctx["B"], ctx["A"], ctx["anchor"]
    window = int(c_bopt(B, "dividends.policy.base_window_quarters", 1))
    if not 1 <= window <= 2 * QY:
        raise ControlInputError("dividends.policy.base_window_quarters вне 1…8 (М§5.7.1)")
    deduct = bool(c_bget(B, "dividends.policy.deduct_at1_after_tax"))
    total = 0.0
    for x in range(k - window + 1, k + 1):
        yq = c_qper(anchor, x)
        if yq not in ni_all:
            raise ControlInputError(f"нет прибыли акционеров квартала {yq[0]}Q{yq[1]} для базы дивиденда (М§5.7.3)")
        total += ni_all[yq]
        if deduct and yq[1] == A["cpn_quarter"]:
            total -= A["cpn_annual"] * (1.0 - c_traj_at(c_bget(B, "tax.statutory"), yq[0], yq[1]))
    return total / window


def c_payout_share(B: dict, year: int) -> float:
    """Доля выплаты года прибыли (М§5.2): clip(payout + payout_deviation, 0, 1)."""
    return min(1.0, max(0.0, c_traj_mean(c_bget(B, "dividends.policy.payout"), year, range(1, QY + 1))
                        + c_traj_mean(c_bget(B, "dividends.payout_deviation"), year, range(1, QY + 1))))


def c_excess_share(B: dict, year: int) -> float:
    """ε года прибыли с линейным вводом (М§5.6)."""
    start = int(c_bnum(B, "dividends.excess.from_profit_year"))
    if year < start:
        return 0.0
    ramp = int(c_bnum(B, "dividends.excess.ramp_years"))
    if ramp < 1:
        raise ControlInputError("dividends.excess.ramp_years — целое ≥ 1 (М прил. A)")
    return c_bnum(B, "dividends.excess.epsilon") * min(1.0, (year - start + 1) / ramp)


def _c_req_glide(ctx: dict, s: str, k: int) -> tuple[float, float]:
    """Требования квартала k с глиссадой (М§4.13.1): req*_j = max по h = 0…H ( r_j,min(k+h, Q) − h × δ ).
    Без ограничения роста — требования без глиссады."""
    memo = ctx["glide_memo"]
    if (s, k) not in memo:
        B, rule = ctx["B"], ctx["growth"]
        ahead = rule["ahead"] if rule else 0
        step = rule["glide"] if rule else 0.0
        best20 = best11 = None
        for h in range(ahead + 1):
            yy, qq = c_qper(ctx["anchor"], min(k + h, ctx["Q"]))
            r20 = max(c_bnum(B, "dividends.policy.threshold"),
                      _c_floor(B, s, "n20_0", yy, qq) + c_bnum(B, "capital.mgmt_buffer.n20_0")) - h * step
            r11 = _c_floor(B, s, "n1_1", yy, qq) + c_bnum(B, "capital.mgmt_buffer.n1_1") - h * step
            best20 = r20 if best20 is None else max(best20, r20)
            best11 = r11 if best11 is None else max(best11, r11)
        memo[(s, k)] = (best20, best11)
    return memo[(s, k)]


def _c_bisect(fn, lo: float, hi: float) -> float:
    """Корень невозрастающей функции на отрезке делением пополам: fn(lo) ≥ 0 > fn(hi); возвращает
    наибольшую точку с fn ≥ 0 (в пределах сходимости)."""
    for _ in range(FIT_ITER):
        mid = (lo + hi) / 2.0
        if fn(mid) >= 0.0:
            lo = mid
        else:
            hi = mid
        if hi - lo <= PLAN_TOL:
            break
    return lo


def _c_quarter_capital(ctx: dict, s: str, y: int, h: int, R: float, ni_q: dict):
    """Нормативы конца квартала (y, h) как функция капитала, DPreg и RWA (М§4.11–§4.12): всё, что от них
    не зависит (вычеты якоря, инструменты, неаудированная прибыль, поправки, требования), считается один
    раз на квартал. Возвращает функцию (bv, dpreg, rwa) → нормативы и требования."""
    B = ctx["B"]
    keep = (1.0 - c_bnum(B, "capital.n20.fvoci_recognition")) * R
    ded20, ded11 = c_bnum(B, "capital.n20.deductions_anchor"), c_bnum(B, "capital.n11.deductions_anchor")
    extra20 = ctx["A"]["AT1"] + c_traj_at(c_bget(B, "capital.n20.t2"), y, h)
    cut = [int(c) for c in c_bget(B, "capital.n11.audit_cutoffs")]
    e_q = _c_unaudited_quarters(cut, y, h)
    if any(yq not in ni_q for yq in e_q):
        raise ControlInputError(f"нет прибыли кварталов для E_q на {y}Q{h}")
    e_un = sum(ni_q[yq] for yq in e_q)
    e_out = e_un if e_un > 0.0 else 0.0
    adj20 = c_bnum(B, "capital.n20.gap_pp") - c_traj_at(c_bget(B, f"capital.reg_scenarios.{s}.deduction_pp.n20_0"), y, h)
    adj11 = c_bnum(B, "capital.n11.gap_pp") - c_traj_at(c_bget(B, f"capital.reg_scenarios.{s}.deduction_pp.n1_1"), y, h)
    fl20, fl11 = _c_floor(B, s, "n20_0", y, h), _c_floor(B, s, "n1_1", y, h)
    req20 = max(c_bnum(B, "dividends.policy.threshold"), fl20 + c_bnum(B, "capital.mgmt_buffer.n20_0"))
    req11 = fl11 + c_bnum(B, "capital.mgmt_buffer.n1_1")
    rwa0 = ctx["rwa0"]

    def c_ratios(bv: float, dpreg: float, rwa: float) -> dict:
        bvreg = bv + dpreg - keep
        grow = rwa / rwa0
        k20 = bvreg - ded20 * grow + extra20
        k11 = bvreg - e_out - ded11 * grow
        return {"k20": k20, "k11": k11, "n20": k20 / rwa + adj20, "n11": k11 / rwa + adj11,
                "n11_star": (k11 + e_out) / rwa + adj11, "e_unaudited": e_un, "floor20": fl20, "floor11": fl11,
                "req20": req20, "req11": req11}

    return c_ratios


def _c_capital_pass(ctx: dict, cell: dict, st: dict, i: int, row: dict) -> tuple[dict, dict]:
    """Квартальный проход капитала внутри года (М§17; порядок М§5.7.4 и §4.13.2).

    По кварталам года: остатки кредитных книг, баланс и RWA на конец квартала, нормативы, требование с
    глиссадой, решения о дивиденде, доля прироста λ и навёрстывание. Совокупный доход и прибыль кварталов
    — профиль годовой строки row (её ОПУ посчитаны годовым шагом при прежнем плане года). Долю λ и долю
    навёрстывания θ контрольная модель ищет делением отрезка пополам по невязке условия роста, а не
    закрытой формулой с шагом секущей. Возвращает новый план года и выходы кварталов."""
    B, A, p = ctx["B"], ctx["A"], ctx["periods"][i]
    r, s = cell["regime"], cell["scenario"]
    y, qs, n = p["year"], p["quarters"], p["n"]
    loans, fv, oaf, rule, cal = ctx["loans"], ctx["fv"], ctx["oaf"], ctx["growth"], ctx["divcal"]
    k_first = c_qidx(ctx["anchor"], y, qs[0])
    ni_all = {**st["ni_q"], **row["ni_q"]}
    m = row["m_q"]
    n_out, n_iss = A["N_out"], A["N_iss"]
    wtf = c_bnum(B, "volumes.wholesale_to_funds")
    r_oa, r_ol = c_bnum(B, "volumes.other_assets_to_loans"), c_bnum(B, "volumes.other_liabilities_to_loans")
    r_al = c_bnum(B, "credit.allowance_ratio")
    m_liq = c_bnum(B, "volumes.liquid_min_share")
    ssl = c_bnum(B, "volumes.securities_share_of_liquid")
    outside = A["AT1"] + A["NCI"]
    skip_year = (r == R_CRISIS and y == ctx["shock_year"] and bool(c_bget(B, "dividends.crisis.skip_in_shock_year")))
    catch_on = bool(c_bget(B, "dividends.crisis.catch_up"))
    can_cut = rule is not None and rule["lam_min"] < 1.0 and any(m[b] > 0.0 for b in loans)
    E_prev, E_pot = {b: st["E"][b] for b in loans}, dict(st["Epot"])
    bv_prev, deferred, queue = st["BV"], st["D"], [dict(it) for it in st["dq"]]
    paths = {b: [st["E"][b]] for b in loans}
    year_divs, records, quarters = [], [], []
    for j, q in enumerate(qs):
        k = k_first + j
        for b in loans:
            E_pot[b] = E_pot[b] * (1.0 + m[b])
        todo = sorted(cal["by_q"].get(k, []), key=lambda e: e["p"])
        fixed = [{"amt": e["dps_register"] * n_out / 1000.0, "dec": k, "reg": e["q_reg"], "pay": e["q_pay"],
                  "p": e["p"]} for e in todo if e["dps_register"] is not None]
        own, calc_of = [], {}             # решения самой клетки (без записи реестра)
        for e in todo:
            base = c_div_base(ctx, ni_all, e["p"])
            pool = c_payout_share(B, e["year"]) * max(0.0, base)
            calc_of[e["p"]] = {"ent": e, "base": base, "pool": pool, "want": pool * n_out / n_iss}
            if e["dps_register"] is None:
                own.append(calc_of[e["p"]])
        live = [] if skip_year else own
        want_sum = sum(x["want"] for x in live)
        req20_g, req11_g = _c_req_glide(ctx, s, k)
        ratios = _c_quarter_capital(ctx, s, y, q, row["R_q"][j], ni_all)
        funds = row["fr_path"][j + 1] + row["cf_path"][j + 1]
        liab_fixed = funds + wtf * funds + outside

        def c_quarter_end(lam, extra_loans, model_divs):
            """Конец квартала на копии состояния: кредитные книги при доле прироста lam и добавке
            навёрстывания, дивиденды квартала — записи реестра и model_divs."""
            Eq = {b: E_prev[b] * (1.0 + (lam if m[b] > 0.0 else 1.0) * m[b]) + extra_loans.get(b, 0.0)
                  for b in loans}
            total = sum(Eq.values())
            ac = total - sum(fv[b] * Eq[b] for b in fv) if fv else total
            decided = fixed + model_divs
            bv = bv_prev + row["ci_q"][j] - sum(d["amt"] for d in decided)
            dp, dpreg = st["dp_perm"], 0.0
            for it in queue + decided:
                if it["pay"] > k:
                    dp += it["amt"]
                if it["reg"] > k:
                    dpreg += it["amt"]
            oa = r_oa * total + oaf
            assets_nb = total - r_al * ac + oa
            la = liab_fixed + r_ol * total + dp + bv - assets_nb
            la = max(la, m_liq * assets_nb / (1.0 - m_liq))
            bal = dict(Eq)
            bal[SECURITIES], bal[LIQUIDITY] = ssl * la, (1.0 - ssl) * la
            rwa = _c_rwa_of(ctx, r, y, q, bal, oa, row["dn_q"][j], row["xf_q"][j])
            cp = ratios(bv, dpreg, rwa)
            if rule is None:
                # без ограничения роста запас — по отчётным нормативам и требованию без глиссады (М§5.7.4)
                room = ((cp["n20"] - cp["req20"]) * rwa, (cp["n11"] - cp["req11"]) * rwa)
            else:
                room = ((cp["n20"] - req20_g) * rwa, (cp["n11_star"] - req11_g) * rwa)
            return {"E": Eq, "loans": total, "bv": bv, "dp": dp, "dpreg": dpreg, "rwa": rwa, "cap": cp,
                    "room": room, "iea": total + la}

        full = c_quarter_end(1.0, {}, [])
        lam, add, final = 1.0, {}, full
        if rule is None:
            h_ref = min(full["room"])
        else:
            low = c_quarter_end(rule["lam_min"], {}, []) if can_cut else full
            h_ref = min(low["room"]) if rule["order"] == ORDER_DIV_FIRST else min(full["room"])
        div_base = min(want_sum, max(0.0, h_ref)) if want_sum else 0.0
        if rule is not None:
            # ι: часть базового дивиденда, чей вычет из регуляторного капитала приходится на этот квартал
            same_q = sum(div_base * x["want"] / want_sum for x in live if x["ent"]["q_reg"] == k) if want_sum else 0.0
            g_full = [h - same_q for h in full["room"]]
            g_low = [h - same_q for h in low["room"]]
            if can_cut and min(g_full) < 0.0:
                shares = []
                for a in range(len(g_full)):
                    if g_full[a] >= 0.0 or g_low[a] - g_full[a] <= PLAN_TOL:
                        shares.append(1.0)              # норматив не нарушен или урезание его не поправляет
                    elif g_low[a] <= 0.0:
                        shares.append(rule["lam_min"])
                    else:
                        shares.append(_c_bisect(lambda x, a=a: c_quarter_end(x, {}, [])["room"][a] - same_q,
                                                rule["lam_min"], 1.0))
                lam = min(shares)
                final = full if lam == 1.0 else low if lam == rule["lam_min"] else c_quarter_end(lam, {}, [])
            if lam == 1.0 and min(g_full) >= 0.0 and rule["catch_up"] > 0.0:
                # навёрстывание роста (М§4.13.2 п. 5): доля κ/4 разрыва с потенциальным путём, общей долей θ
                gap = {b: max(0.0, E_pot[b] - full["E"][b]) for b in loans}
                if any(v > 0.0 for v in gap.values()):
                    whole = {b: rule["catch_up"] / QY * gap[b] for b in loans}
                    tried = c_quarter_end(1.0, whole, [])
                    if min(tried["room"]) - same_q >= 0.0:
                        add, final = whole, tried
                    else:
                        theta = _c_bisect(lambda x: min(c_quarter_end(
                            1.0, {b: x * whole[b] for b in loans}, [])["room"]) - same_q, 0.0, 1.0)
                        add = {b: theta * whole[b] for b in loans}
                        final = c_quarter_end(1.0, add, [])
        h_fin = min(final["room"])
        cut = bool(live) and div_base < want_sum - 1e-9
        # догоняющая выплата и избыток — раз в год, в решении за четвёртый квартал прибыли, при λ* = 1
        catch = excess = 0.0
        top = [x for x in live if x["ent"]["h"] == QY]
        if top and lam == 1.0:
            if catch_on:
                catch = min(deferred, max(0.0, h_fin - div_base))
            excess = c_excess_share(B, top[0]["ent"]["year"]) * max(0.0, h_fin - div_base - catch)
        model_divs = []
        for e in todo:
            calc = calc_of[e["p"]]
            rec = {"period": e["period"], "year": e["year"], "h": e["h"], "q": k, "base": calc["base"],
                   "want": calc["want"], "headroom": h_ref, "headroom_final": h_fin, "base_div": 0.0,
                   "catch": 0.0, "excess": 0.0, "cut": False, "lam": lam,
                   "dps_policy": calc["pool"] * 1000.0 / n_iss, "deferred_before": deferred}
            if e["dps_register"] is not None:
                rec.update(source="register", div=e["dps_register"] * n_out / 1000.0)
                rec["base_div"] = rec["div"]
            elif skip_year:
                rec.update(source="crisis_skip", div=0.0)
                if catch_on:
                    deferred += calc["want"]
            else:
                rec["base_div"] = div_base * calc["want"] / want_sum if want_sum else 0.0
                if e["h"] == QY:
                    rec.update(catch=catch, excess=excess)
                    deferred -= catch
                rec.update(source="policy", cut=cut, div=rec["base_div"] + rec["catch"] + rec["excess"])
                if rec["div"]:
                    model_divs.append({"amt": rec["div"], "dec": k, "reg": e["q_reg"], "pay": e["q_pay"], "p": e["p"]})
            rec.update(dps=rec["div"] * 1000.0 / n_out, deferred_after=deferred)
            records.append(rec)
        end = c_quarter_end(lam, add, model_divs)
        cp = end["cap"]
        E_prev, bv_prev = end["E"], end["bv"]
        decided = fixed + model_divs
        year_divs.extend(decided)
        queue = [it for it in queue + decided if it["pay"] > k or it["reg"] > k]
        for b in loans:
            paths[b].append(end["E"][b])
        quarters.append({"q": k, "lam": lam, "loans": end["loans"], "loans_potential": sum(E_pot.values()),
                         "catch_up": sum(add.values()), "div_model": sum(d["amt"] for d in model_divs),
                         "div": sum(d["amt"] for d in decided), "bv": end["bv"], "rwa": end["rwa"],
                         "n20": cp["n20"], "n11": cp["n11"], "n11_star": cp["n11_star"],
                         "req20": cp["req20"], "req11": cp["req11"], "req20_glide": req20_g,
                         "req11_glide": req11_g, "dp": end["dp"], "dpreg": end["dpreg"],
                         "headroom": h_ref, "headroom_final": h_fin, "iea": end["iea"]})
    plan = {"loans": paths, "divs": year_divs}
    return plan, {"quarters": quarters, "records": records, "deferred": deferred, "Epot": E_pot}


def _c_plan_gap(old: dict, new: dict) -> float:
    """Наибольшее расхождение двух планов года: остатки кредитных книг — долей, дивиденды — млрд ₽."""
    if old["loans"] is None or len(old["divs"]) != len(new["divs"]):
        return float("inf")
    gap = 0.0
    for b, path in new["loans"].items():
        for a, c in zip(old["loans"][b], path):
            gap = max(gap, abs(c - a) / max(abs(c), 1.0))
    for a, c in zip(old["divs"], new["divs"]):
        if (a["dec"], a["reg"], a["pay"]) != (c["dec"], c["reg"], c["pay"]):
            return float("inf")
        gap = max(gap, abs(c["amt"] - a["amt"]))
    return gap


def _c_year_quarterly(ctx: dict, cell: dict, st: dict, i: int) -> tuple[dict, dict]:
    """Год ветви с квартальным проходом капитала (М§17): годовые строки ОПУ при плане года (пути кредитных
    книг и решения о дивиденде по кварталам) и квартальный проход, который этот план пересчитывает на
    профиле прибыли годовой строки, — до совпадения плана. Возвращает (состояние, строка)."""
    p = ctx["periods"][i]
    plan = {"loans": None, "divs": []}
    for turn in range(FIT_ITER):
        nst, row = _c_period(ctx, cell, st, i, 0.0, plan)
        new_plan, info = _c_capital_pass(ctx, cell, st, i, row)
        gap = _c_plan_gap(plan, new_plan)
        if gap <= PLAN_TOL:
            break
        if turn >= FIT_ITER // 2 and plan["loans"] is not None and math.isfinite(gap):
            # медленная сходимость: полшага к новому плану
            for b, path in new_plan["loans"].items():
                new_plan["loans"][b] = [(a + c) / 2.0 for a, c in zip(plan["loans"][b], path)]
        plan = new_plan
    qr = info["quarters"]
    A, y = ctx["A"], p["year"]
    pot_end, act_end = qr[-1]["loans_potential"], qr[-1]["loans"]
    if i == 0:
        # за год якоря знаменатель роста — факт конца прошлого года (М§4.13.3)
        prev = A["history"].get(f"{y - 1}Q{QY}", {}).get(LINK_BASES[0]) if p["stub"] else sum(st["Epot"].values())
        pot_prev = act_prev = None if prev is None else float(prev)
    else:
        pot_prev, act_prev = sum(st["Epot"].values()), sum(st["E"][b] for b in ctx["loans"])
    row.update(quarters=qr, decisions_q=info["records"], plan_gap=gap, plan_turns=turn + 1,
               lam_q=[x["lam"] for x in qr], lam_min=min(x["lam"] for x in qr),
               catch_up=sum(x["catch_up"] for x in qr), div_model=sum(x["div_model"] for x in qr),
               loans_potential=pot_end, cut_share=1.0 - act_end / pot_end,
               growth_potential=None if pot_prev is None else pot_end / pot_prev - 1.0,
               growth_actual=None if act_prev is None else act_end / act_prev - 1.0,
               req20_glide=qr[-1]["req20_glide"], req11_glide=qr[-1]["req11_glide"],
               potential_end=dict(info["Epot"]), D=info["deferred"])
    nst["Epot"], nst["D"] = info["Epot"], info["deferred"]
    return nst, row


def c_profit_years(ctx: dict, made: list[dict]) -> dict:
    """Дивиденд и DPS по годам прибыли (М§5.7.5): сумма четырёх кварталов прибыли года — открытый квартал
    по решению клетки, закрытый — по строке истории. Закрытый квартал без своей строки, покрытый строкой
    истории более позднего квартала (решение «за девять месяцев» — одна строка, период — последний из
    кварталов), даёт ноль: его дивиденд — в той строке. Строка без числа DPS — отказ (null ≠ 0). Год входит,
    если хотя бы один его квартал открыт и ни одно его решение не лежит за сеткой."""
    A, cal, anchor = ctx["A"], ctx["divcal"], ctx["anchor"]
    by_p = {c_qidx(anchor, *c_per_parse(d["period"])): d for d in made}
    out = {}
    for year in sorted({e["year"] for e in cal["open"].values()}):
        ks = [c_qidx(anchor, year, h) for h in range(1, QY + 1)]
        if any(k > cal["p_last"] and k not in cal["open"] for k in ks):
            continue
        parts, dps, div, policy = {}, 0.0, 0.0, 0.0
        for k in ks:
            per = f"{year}Q{c_qper(anchor, k)[1]}"
            if k in by_p:
                parts[per] = by_p[k]
                dps += by_p[k]["dps"]
                div += by_p[k]["div"]
                policy += by_p[k]["dps_policy"]
            else:
                if k in cal["hist_dps"]:
                    hist = cal["hist_dps"][k]
                    if hist is None:
                        raise ControlInputError(f"строка dividends.history закрытого квартала {per} без DPS (М§5.7.5)")
                elif any(later > k for later in cal["closed"]):
                    hist = 0.0                          # покрыт строкой истории более позднего квартала
                else:
                    raise ControlInputError(f"нет строки dividends.history закрытого квартала {per} (М§5.7.5)")
                dps += hist
                policy += hist
                div += hist * A["N_out"] / 1000.0
        last_q = max((d["q"] for d in parts.values()), default=0)
        out[year] = {"kind": "quarterly", "div": div, "dps": dps, "dps_policy": policy, "quarters": parts,
                     "decision_year": c_qper(anchor, last_q)[0],
                     "cut": any(d["cut"] for d in parts.values())}
    return out


def c_cell_annual(ctx: dict, world: str, regime: str, scenario: str) -> dict:
    """Клетка (W, r, s): годовой путь, дивиденды, V_RI и V_DDM (М§6), терминал (М§7)."""
    cell = {"world": world, "regime": regime, "scenario": scenario}
    path = _c_cell_path(ctx, cell)
    out = {**cell, **path, "years": [p["year"] for p in ctx["periods"]]}
    out.update(_c_value_cell(ctx, cell, path["rows"], path["decisions"]))
    return out


def _c_value_cell(ctx: dict, cell: dict, rows: list[dict], decisions: dict) -> dict:
    B, A = ctx["B"], ctx["A"]
    ck, periods = ctx["clock"], ctx["periods"]
    df = ctx["disc"][cell["world"]]
    p0 = ck["p0"]
    bv_prev = A["BV"] if p0 == 0 else rows[p0 - 1]["bv"]
    r0 = rows[p0]
    # капитал на дату оценки (М§6.1): закрытые кварталы периода p0 целиком и доля e_q квартала q0 —
    # по квартальному профилю CI; дивиденд — вычтен, если конец квартала решения не позже v (М§0.2)
    whole = int(ck["pos"])
    ci_to_v = sum(r0["ci_q"][:whole]) + ((ck["pos"] - whole) * r0["ci_q"][whole] if whole < len(r0["ci_q"]) else 0.0)
    bv_v = bv_prev + ci_to_v - sum(amt for j, amt in r0["div_list"] if ck["t_start"][p0] + 0.25 * (j + 1) <= 0.0)
    v_ri, v_ddm, pv_ri = bv_v, 0.0, 0.0
    for i in range(p0, len(periods)):
        row = rows[i]
        te = ck["tau_end"][i]
        d_end = df(te)
        corr = 0.0
        for j, div in row["div_list"]:
            # дивиденд датируется концом квартала решения; решений в году — от нуля до нескольких (М§6.3)
            ta = ck["t_start"][i] + 0.25 * (j + 1)
            if ta > 0.0:
                v_ddm += div * df(ta)
                corr += div * (df(ta) / d_end - 1.0)
        if i == p0:
            k = 1.0 / d_end - 1.0
            ri = row["ci"] - ci_to_v - k * bv_v + corr
        else:
            k = df(ck["tau_end"][i - 1]) / d_end - 1.0
            ri = row["ci"] - k * rows[i - 1]["bv"] + corr
        row["k"], row["ri"] = k, ri
        pv_ri += ri * d_end
    last = rows[-1]
    tl = ck["tau_end"][len(periods) - 1]
    yl = periods[-1]["year"]
    mult = c_bnum(B, "valuation.terminal.excess_capital_multiple")
    n20_t, n11_t = last["n20"], last["n11_star"]
    if last["dpreg"]:
        # нормативы терминала — без дивидендов, вычтенных из BV, но ещё не из регуляторного капитала (М§7)
        n20_t, n11_t = n20_t - last["dpreg"] / last["rwa"], n11_t - last["dpreg"] / last["rwa"]
    x_t = mult * min((n20_t - last["req20"]) * last["rwa"],
                     (n11_t - last["req11"]) * last["rwa"])
    bv_star = last["bv"] - x_t
    k_t = df(tl) / df(tl + 1.0) - 1.0
    g_raw = c_g_terminal(B, cell["world"])
    g_t = min(g_raw, k_t - 0.0001)
    nci = c_bnum(B, "pnl.nci_share")
    # Доход на избыток — по маржинальной ставке балансирующих статей (М§7). Избыток: пока минимум
    # ликвидности не связывает — смесь доходностей бумаг и ликвидности на конце Q в их долях в LA,
    # дальше — ставка опта. Порог — не запас HLA, а H* = HLA / (1 − m): изъятый капитал уменьшает и LA, и
    # активы, от которых считается минимум. Недостаток — зеркально: добавленный капитал сначала гасит
    # добор опта WT (если минимум связывает), остальное ложится в балансирующие активы по смеси.
    m_liq = c_bnum(B, "volumes.liquid_min_share")
    hla = max(0.0, last["securities"] + last["liquidity"] - m_liq * last["assets"])
    h_star = hla / (1.0 - m_liq)
    wt = max(0.0, last["wholesale_extra"])
    sec = c_bnum(B, "volumes.securities_share_of_liquid")
    y_bal = sec * last["y_sec_end"] + (1.0 - sec) * last["y_liq_end"]
    if x_t > 0.0:
        y_x = y_bal * min(x_t, h_star) + last["c_wh_end"] * max(0.0, x_t - h_star)
    else:
        y_x = -(last["c_wh_end"] * min(-x_t, wt) + y_bal * max(0.0, -x_t - wt))
    ni_t1 = (last["pbt"] * (1.0 + g_t) - y_x) * (1.0 - last["tau_eff"]) * (1.0 - nci)
    tau_stat_l = c_traj_at(c_bget(B, "tax.statutory"), yl, A["cpn_quarter"])
    ci_t1 = ni_t1 - A["cpn_annual"] * (1.0 - tau_stat_l)
    roe_t_raw = ci_t1 / bv_star
    # угасание одностороннее (М§7): множитель действует только на положительный избыток ROE_T − k_T
    fade = c_bnum(B, "valuation.terminal.fade")
    roe_t = k_t + fade * max(roe_t_raw - k_t, 0.0) + min(roe_t_raw - k_t, 0.0)
    tv_ri = (roe_t - k_t) * bv_star / (k_t - g_t)
    tv_ddm = x_t + (roe_t - g_t) * bv_star / (k_t - g_t)
    d_l = df(tl)
    v_ri = bv_v + pv_ri + d_l * tv_ri
    v_ddm += d_l * tv_ddm
    return {"bv_v": bv_v, "v_ri": v_ri, "v_ddm": v_ddm, "pv_ri_explicit": pv_ri,
            "x_t": x_t, "hla": hla, "h_star": h_star, "wt": wt, "y_bal": y_bal, "y_x": y_x, "bv_star": bv_star,
            "k_t": k_t, "g_t": g_t, "g_t_capped": g_raw > k_t - 0.0001,
            "roe_t_raw": roe_t_raw, "roe_t": roe_t, "ni_t1": ni_t1, "ci_t1": ci_t1,
            "tv_ri": tv_ri, "tv_ddm": tv_ddm, "terminal_share": d_l * tv_ddm / v_ddm if v_ddm else None,
            "tau_l": tl, "df_l": d_l}


# ============================================================================ мост до цены (М§8.1)

def _c_register_amounts(ctx: dict) -> list[tuple[float, dt.date, dt.date | None]]:
    """Объявленные дивиденды реестра: (сумма DPS × N_out / 1000, дата вычета из BV модели, экс-дата).
    Вычет из BV модели — дата фактов (дивиденд вычтен в якоре) или конец квартала ГОСА клетки (М§8.1)."""
    B, A = ctx["B"], ctx["A"]
    facts_date = _c_as_date(c_bget(B, "meta.facts_date"))
    out = []
    if ctx["quarterly"]:
        # строка на запись — на квартал прибыли (М§8.1): вычет из BV модели — дата фактов у закрытого
        # квартала, иначе конец квартала клетки q_cell(period)
        cal = ctx["divcal"]
        for k, rec in sorted(cal["register"].items()):
            cell_end = c_q_last_day(*c_qper(ctx["anchor"], rec["q_cell"]))
            out.append((rec["dps"] * A["N_out"] / 1000.0, facts_date if k <= cal["p_last"] else cell_end, rec["ex"]))
        return out
    agm = int(c_bnum(B, "dividends.calendar.agm_quarter"))
    for rec in _c_register_binding(ctx):
        agm_end = c_q_last_day(int(_c_nodeval(rec["year"])) + 1, agm)
        ex = rec.get("ex_date")
        out.append((float(_c_nodeval(rec["dps"])) * A["N_out"] / 1000.0,
                    facts_date if agm_end <= facts_date else agm_end,
                    _c_as_date(_c_nodeval(ex)) if ex else None))
    return out


def c_bridge_register(ctx: dict) -> float:
    """B(v): объявленные дивиденды реестра от модельного вычета из BV до экс-даты, млрд ₽."""
    v = ctx["clock"]["v"]
    return sum(amount * ((1.0 if deduct <= v else 0.0) - (1.0 if ex is not None and ex <= v else 0.0))
               for amount, deduct, ex in _c_register_amounts(ctx))


def c_pending_register(ctx: dict) -> float:
    """D_pend (М§8.2): объявленные дивиденды, которые клетки ещё не вычли из BV (v раньше вычета) —
    они внутри V0 и дисконта за управление не несут; номинал, как в мосте, млрд ₽."""
    v = ctx["clock"]["v"]
    return sum(amount for amount, deduct, _ in _c_register_amounts(ctx) if v < deduct)


# ============================================================================ A-P2u (М§12)

def _c_qindex(y: int, q: int) -> int:
    return y * QY + (q - 1)


def c_expectations_ctl(ctx: dict, quarters) -> dict:
    """Ожидания режимов μ_x,r(q) (М§12): среднее слоя «свой взгляд» (веса миров × P(s | r)) по
    клеткам режима без отклонений A-P2u. CoR — путь режима через мост плюс κ-добавка мира
    (поквартально, точно); ЧПМ — ЧПМ движка клетки с ближним сдвигом и сдвигом режима из
    предварительного прохода клеток до года последнего квартала (годовой шаг: ЧПМ квартала внутри
    периода — ставки квартала при структуре баланса периода). Ключ результата — (x, r, год, квартал)."""
    B = ctx["B"]
    quarters = sorted({(int(y), int(q)) for y, q in quarters})
    where = {p["year"]: p["quarters"] for p in ctx["periods"]}
    for y, q in quarters:
        if q not in where.get(y, ()):
            raise ControlInputError(f"наблюдение A-P2u {y}Q{q} вне прогнозных кварталов сетки")
    pw = {w: float(c_bget(B, "joint.world_prob").get(w, 0.0)) for w in ctx["worlds"]}
    prs = c_bget(B, "joint.reg_prob_given_regime")
    regimes, scen = list(c_bget(B, "regimes.ids")), list(c_bget(B, "capital.reg_scenarios.ids"))
    lag, kap = int(c_bnum(B, "credit.real_rate_lag_q")), c_bnum(B, "credit.kappa")
    saved, ctx["dev"] = ctx["dev"], {}                  # предварительный проход — без отклонений (δ ≡ 0)
    try:
        nim0 = {}
        for w in (w for w in ctx["worlds"] if pw[w]):
            for r in regimes:
                for s in scen:
                    rows = _c_cell_path(ctx, {"world": w, "regime": r, "scenario": s},
                                        upto_year=quarters[-1][0])["rows"]
                    for p, row in zip(ctx["periods"], rows):
                        for j, q in enumerate(p["quarters"]):
                            nim0[(w, r, s, p["year"], q)] = row["nim_q"][j]
    finally:
        ctx["dev"] = saved
    mu = {}
    for y, q in quarters:
        for r in regimes:
            mu[("cor", r, y, q)] = sum(pw[w] * (c_cor_path_engine(ctx, r, y, q) + kap * _c_kappa_gap(B, w, y, q, lag))
                                       for w in pw if pw[w])
            mu[("nim", r, y, q)] = sum(pw[w] * float(prs[r][s]) * nim0[(w, r, s, y, q)]
                                       for w in pw if pw[w] for s in scen)
    return mu


def _c_frozen_mu(ctx: dict, o: dict) -> dict:
    """Замороженные ожидания режимов наблюдения квартала не позже якоря (М§12): словари mu_cor,
    mu_nim {режим: μ} в базисе записи — через тот же мост, что и само наблюдение. Нет μ наблюдённой
    величины — громкий отказ."""
    A = ctx["A"]
    y, q = c_per_parse(o["period"])
    out = {}
    for x in ("cor", "nim"):
        if o.get(x) is None:
            continue
        table = o.get(f"mu_{x}")
        for r in c_bget(ctx["B"], "regimes.ids"):
            if not isinstance(table, dict) or table.get(r) is None:
                raise ControlInputError(f"наблюдение A-P2u {o['period']} (квартал не позже якоря) без mu_{x}.{r}")
            val = float(table[r])
            out[(x, r, y, q)] = c_to_engine(A, x, val) if o.get("basis", "engine") == "mgmt" else val
    return out


def c_regime_update_ctl(ctx: dict) -> None:
    """Вероятности режимов после квартальных наблюдений CoR и ЧПМ и затухающие отклонения (М§12).
    Априорные стационарны, память — окно: фильтр стартует с базовых вероятностей книги и пустого
    состояния и проходит только последние joint.regime_update.window_obs наблюдений."""
    B, A = ctx["B"], ctx["A"]
    ru = "joint.regime_update"
    window = c_bget(B, f"{ru}.window_obs")
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise ControlInputError("joint.regime_update.window_obs — целое ≥ 1 (М прил. A)")
    floor_share = c_bnum(B, f"{ru}.floor_share")
    if not 0.0 <= floor_share <= 1.0:
        raise ControlInputError("joint.regime_update.floor_share вне [0; 1] (М прил. A)")
    obs = sorted(c_bget(B, f"{ru}.observations") or [], key=lambda o: c_per_parse(o["period"]))[-window:]
    prior = {r: float(v) for r, v in c_bget(B, "joint.regime_prob").items()}
    ctx["posterior"], ctx["dev"], ctx["mu"], ctx["updates"] = dict(prior), {}, {}, []
    if not obs:
        return
    # ожидания режимов: прогнозные кварталы — предварительный проход клеток; кварталы не позже якоря —
    # замороженные μ записи (их пишет перезаякоривание)
    ahead = [c_per_parse(o["period"]) for o in obs if c_per_parse(o["period"]) > ctx["anchor"]]
    mus = c_expectations_ctl(ctx, ahead) if ahead else {}
    for o in obs:
        if c_per_parse(o["period"]) <= ctx["anchor"]:
            mus.update(_c_frozen_mu(ctx, o))
    ctx["mu"] = mus
    sig = {x: c_bnum(B, f"{ru}.observables.{x}.sigma_pp") for x in ("cor", "nim")}
    rho = {x: c_bnum(B, f"{ru}.observables.{x}.rho_q") for x in ("cor", "nim")}
    cap = c_bnum(B, f"{ru}.max_shift_pp")
    floors = {r: floor_share * prior[r] for r in prior}
    state = {(x, r): None for x in ("cor", "nim") for r in prior}
    trail = {key: [] for key in state}
    post = dict(prior)
    for o in obs:
        y, q = c_per_parse(o["period"])
        qi = _c_qindex(y, q)
        like = {r: 1.0 for r in prior}
        for x in ("cor", "nim"):
            val = o.get(x)
            if val is None:
                continue
            val = float(val)
            if o.get("basis", "engine") == "mgmt":
                val = c_to_engine(A, x, val)
            se = float(o.get(f"se_{x}") or 0.0)
            for r in prior:
                dev = val - mus[(x, r, y, q)]
                prev = state[(x, r)]
                if prev is None:
                    k, err, P = 0, dev, sig[x] ** 2
                    m_prev = 0.0
                else:
                    k = qi - prev["qi"]
                    rk = rho[x] ** k
                    err = dev - rk * prev["m"]
                    P = sig[x] ** 2 * (1.0 - rho[x] ** (2 * k)) + rho[x] ** (2 * k) * prev["v"]
                    m_prev = rk * prev["m"]
                like[r] *= math.exp(-0.5 * err * err / (P + se * se))
                if se == 0.0:
                    m_new, v_new = dev, 0.0
                else:
                    wk = P / (P + se * se)
                    m_new, v_new = m_prev + wk * err, (1.0 - wk) * P
                state[(x, r)] = {"qi": qi, "m": m_new, "v": v_new, "y": y, "q": q}
                trail[(x, r)].append((y, q, m_new))
        tot = sum(post[r] * like[r] for r in post)
        raw = {r: post[r] * like[r] / tot for r in post}
        clipped = {r: post[r] + max(-cap, min(cap, raw[r] - post[r])) for r in post}
        z = sum(clipped.values())
        clipped = {r: c / z for r, c in clipped.items()}
        worst = max(abs(clipped[r] - post[r]) for r in post)
        if worst > cap + 1e-12:
            clipped = {r: post[r] + cap / worst * (clipped[r] - post[r]) for r in post}
        post = c_floor_probabilities(clipped, floors)       # пол — вслед за пределом сдвига
        ctx["updates"].append({"period": o["period"], "posterior": dict(post)})
    ctx["posterior"] = post
    for r in prior:
        ctx["dev"][r] = {}
        for x in ("cor", "nim"):
            stt = state[(x, r)]
            if stt is not None:
                ctx["dev"][r][x] = {"y": stt["y"], "q": stt["q"], "rho": rho[x], "m": stt["m"],
                                    "trail": trail[(x, r)]}


def c_floor_probabilities(prob: dict, floors: dict) -> dict:
    """Пол вероятности режима (М§12): режим ниже своего пола ставится на пол, остальные умножаются на
    общий множитель так, чтобы сумма была 1; если после этого ещё какой-то режим оказался ниже пола —
    он тоже ставится на пол, и шаг повторяется (режимов конечное число, сумма полов ≤ 1)."""
    out = dict(prob)
    pinned: set = set()
    while True:
        low = {r for r in out if r not in pinned and out[r] < floors[r]}
        if not low:
            return out
        pinned |= low
        free = [r for r in out if r not in pinned]
        room = 1.0 - sum(floors[r] for r in pinned)
        mass = sum(prob[r] for r in free)
        for r in pinned:
            out[r] = floors[r]
        for r in free:
            out[r] = prob[r] * room / mass if mass > 0.0 else 0.0


# ============================================================================ сетка, слои, точка (М§3, §8–§9)

def c_layer_weights(B: dict) -> dict[str, dict[str, float]]:
    return {"analytical": {w: float(v) for w, v in c_bget(B, "joint.world_prob").items()},
            "market_implied": {w: float(v) for w, v in c_bget(B, "joint.world_prob_market_implied").items()},
            "macro_neutral": {c_bget(B, "joint.macro_neutral_world"): 1.0}}


def c_price_of(v0: float, bridge: float, gov: float, n_div: float, pending: float = 0.0) -> float:
    """Цена (М§8.2): дисконт за управление — к V0 без объявленного дивиденда: ни мост B(v), ни
    сумма D_pend (объявлено, но ещё не вычтено из BV модели) дисконта не несут. Делится на N_div
    (М§8.4); суммы моста и D_pend — на акции в обращении, их делитель не трогает."""
    own = v0 - pending
    if own > 0.0:
        return (own * (1.0 - gov) + pending + bridge) * 1000.0 / n_div
    return (v0 + bridge) * 1000.0 / n_div


def c_control_run(book: dict | None = None, facts: dict | None = None, *, valuation_date=None,
                  base_book: dict | None = None) -> dict:
    """Вся контрольная модель: передача, 36 клеток, слои, низ/верх/точка при центральных значениях."""
    book = book if book is not None else c_book_machine()
    facts = facts if facts is not None else c_facts_bundle()
    ctx = c_control_context(book, facts, valuation_date=valuation_date, base_book=base_book)
    B, A = ctx["B"], ctx["A"]
    if c_bget(B, "dividends.policy.base") != "ifrs_ni_shareholders":
        raise ControlUnsupported("база дивиденда кроме ifrs_ni_shareholders не реализована")
    worlds = ctx["worlds"]
    regimes = list(c_bget(B, "regimes.ids"))
    scen = list(c_bget(B, "capital.reg_scenarios.ids"))
    cells = [c_cell_annual(ctx, w, r, s) for w in worlds for r in regimes for s in scen]
    lw = c_layer_weights(B)
    prs = c_bget(B, "joint.reg_prob_given_regime")
    layers = {}
    for name in LAYERS:
        P = {}
        for c in cells:
            P[(c["world"], c["regime"], c["scenario"])] = (
                lw[name].get(c["world"], 0.0) * ctx["posterior"][c["regime"]]
                * float(prs[c["regime"]][c["scenario"]]))
        v0 = sum(P[(c["world"], c["regime"], c["scenario"])] * c["v_ri"] for c in cells)
        bv = sum(P[(c["world"], c["regime"], c["scenario"])] * c["bv_v"] for c in cells)
        layers[name] = {"prob_sum": sum(P.values()), "v0": v0, "bv_v": bv,
                        "price": c_price_of(v0, ctx["bridge_amount"], ctx["gov"], A["N_div"],
                                            ctx["pending_amount"]),
                        "bv_per_share": bv * 1000.0 / A["N_div"],
                        "pb": v0 / bv if bv else None}
    lam = c_bnum(B, "joint.own_macro_confidence")
    low, high = layers["macro_neutral"]["price"], layers["analytical"]["price"]
    for c in cells:
        c["price"] = c_price_of(c["v_ri"], ctx["bridge_amount"], ctx["gov"], A["N_div"], ctx["pending_amount"])
        c["pb"] = c["v_ri"] / c["bv_v"]
    res = {"ctx": ctx, "transmission": ctx["tr"], "cells": cells, "layers": layers,
            "low": low, "high": high, "lam": lam, "point": low + lam * (high - low),
            "bridge_amount": ctx["bridge_amount"], "pending_amount": ctx["pending_amount"],
            "governance": ctx["gov"], "shock_year": ctx["shock_year"],
            "posterior": ctx["posterior"], "derived": ctx["derived"],
            "shares_out": A["N_out"], "divisor": A["N_div"], "quarterly": ctx["quarterly"],
            "growth_rule": ctx["growth"], "history_test": c_history_kind(B),
            "dps_history": c_dps_history_ctl(B, facts),
            "years": [p["year"] for p in ctx["periods"]]}
    res["central"] = c_central_cell(res)
    return res


def c_central_cell(res: dict) -> dict:
    """Центральная клетка книги — правилом, не литералом (INTERFACES §4.6): мир с наибольшим весом слоя
    «свой взгляд», режим с наибольшей вероятностью после A-P2u, сценарий капитала с наибольшей
    P(s | r) у этого режима; при равенстве — первый по порядку книги."""
    B = res["ctx"]["B"]
    pw = c_bget(B, "joint.world_prob")

    def c_first_max(ids, weight):
        best = ids[0]
        for x in ids[1:]:
            if weight(x) > weight(best):
                best = x
        return best

    w = c_first_max(list(c_bget(B, "worlds.ids")), lambda x: float(pw.get(x, 0.0)))
    r = c_first_max(list(c_bget(B, "regimes.ids")), lambda x: res["posterior"][x])
    prs = c_bget(B, "joint.reg_prob_given_regime")[r]
    sc = c_first_max(list(c_bget(B, "capital.reg_scenarios.ids")), lambda x: float(prs[x]))
    return {"cell": (w, r, sc), "label": "/".join((w, r, sc)), "scenario_weight": float(prs[sc]),
            "probability": float(pw[w]) * res["posterior"][r] * float(prs[sc])}


def c_cell_of(res: dict, world: str, regime: str, scenario: str) -> dict:
    for c in res["cells"]:
        if (c["world"], c["regime"], c["scenario"]) == (world, regime, scenario):
            return c
    raise KeyError((world, regime, scenario))


# ============================================================================ гейты знака и печатаемая маржа (М§4.5, §14.2)

def c_world_price(res: dict, world: str) -> float:
    """Цена мира (М§8.2): оценка при P(W) = 1 с вероятностями режимов и сценариев прогона — той же формулой,
    что цена слоя, на делителе N_div (М§8.4)."""
    ctx = res["ctx"]
    prs = c_bget(ctx["B"], "joint.reg_prob_given_regime")
    v0 = sum(res["posterior"][c["regime"]] * float(prs[c["regime"]][c["scenario"]]) * c["v_ri"]
             for c in res["cells"] if c["world"] == world)
    return c_price_of(v0, ctx["bridge_amount"], ctx["gov"], ctx["A"]["N_div"], ctx["pending_amount"])


def c_point_mass(res: dict) -> dict:
    """Вероятность клетки в точке (М§9): точка — смесь низа и верха с весом λ, поэтому вес мира —
    (1 − λ) × вес слоя «рыночные ставки как есть» + λ × вес слоя «свой взгляд»; режим и сценарий — как в слоях."""
    B = res["ctx"]["B"]
    weights = c_layer_weights(B)
    low, high = weights["macro_neutral"], weights["analytical"]
    prs = c_bget(B, "joint.reg_prob_given_regime")
    lam = res["lam"]
    out = {}
    for c in res["cells"]:
        world = (1.0 - lam) * low.get(c["world"], 0.0) + lam * high.get(c["world"], 0.0)
        out[(c["world"], c["regime"], c["scenario"])] = (world * res["posterior"][c["regime"]]
                                                         * float(prs[c["regime"]][c["scenario"]]))
    return out


def c_volume_sign(book: dict, facts: dict, res: dict | None = None, *, valuation_date=None) -> dict:
    """Числа гейта знака объёмных эффектов (М§4.5): сдвиг точки и цен миров при снятии остановки кредита в
    кризисе (loan_growth_override пуст) и поправок роста режимов (loan_growth_adj = 0). У книги с включённым
    ограничением роста обе стороны сравнения считаются при выключенном ограничении. res — готовый прогон
    этой книги: он служит базой, когда выключать нечего. У книги с ключом checks.volume_sign: {tol} (₽ на
    акцию) результат несёт допуск и условие гейта: ok ложно при сдвиге точки ниже −tol или сдвиге цены мира M
    ниже сдвига цены мира H больше чем на tol; без ключа гейта нет — только числа."""
    spec = c_bopt(book, "checks.volume_sign")
    tol = None
    if spec is not None:
        if not isinstance(spec, dict) or spec.get("tol") is None or float(spec["tol"]) < 0.0:
            raise ControlInputError("checks.volume_sign: нужен tol ≥ 0")
        tol = float(spec["tol"])
    base_book = copy.deepcopy(book)
    rule = c_bopt(base_book, "capital.growth_constraint")
    off = isinstance(rule, dict) and bool(rule.get("enabled"))
    if off:
        rule["enabled"] = False
    free_book = copy.deepcopy(base_book)
    free_book["regimes"][R_CRISIS]["loan_growth_override"] = {}
    for r in c_bget(free_book, "regimes.ids"):
        free_book["regimes"][r]["loan_growth_adj"] = 0.0
    if res is None or off:
        when = valuation_date if res is None else res["ctx"]["clock"]["v"]
        base = c_control_run(base_book, facts, valuation_date=when)
    else:
        base = res
    free = c_control_run(free_book, facts, valuation_date=base["ctx"]["clock"]["v"])
    ref_w = c_bget(base["ctx"]["B"], "nii.transmission.reference_world")
    d_point = free["point"] - base["point"]
    d_world = {w: c_world_price(free, w) - c_world_price(base, w) for w in base["ctx"]["worlds"]}
    ok = None if tol is None else not (d_point < -tol or d_world[W_MKT] < d_world[ref_w] - tol)
    return {"point": base["point"], "point_free": free["point"], "d_point": d_point, "d_world": d_world,
            "market_world": W_MKT, "reference_world": ref_w, "growth_constraint_off": off, "tol": tol, "ok": ok}


def c_stress_sign(book: dict, facts: dict, res: dict | None = None, *, valuation_date=None, tables=None):
    """Гейт знака стресса (ключ книги checks.stress_sign: {loss_step, tol}, оба — млрд ₽; нет ключа — None).

    (а) Убыток: сетка с разовым убытком режима шока, уменьшенным на loss_step (убыток больше); клетка режима
    шока нарушает, если её стоимость выше стоимости книги больше чем на tol. (б) Требование: в каждой паре
    «мир × режим» — по всем режимам, включая режим шока, — сценарий капитала с более высоким требованием Н20.0
    последнего года сетки нарушает, если его операционная прибыль акционеров последнего года выше, чем у
    сценария с более низким требованием, больше чем на tol. Считается на книге как она есть, с её правилом
    роста. Масса — вероятности точки нарушивших клеток (у пары — клетка более строгого сценария); наибольшее
    превышение — наибольший прирост стоимости или прибыли среди нарушений. В table — числа всех клеток и пар,
    не только нарушивших; tables — пара готовых таблиц (их числа от порога не зависят)."""
    spec = c_bopt(book, "checks.stress_sign")
    if spec is None:
        return None
    if not isinstance(spec, dict) or spec.get("loss_step") is None or spec.get("tol") is None:
        raise ControlInputError("checks.stress_sign: нужны loss_step и tol")
    step, tol = float(spec["loss_step"]), float(spec["tol"])
    if step <= 0.0 or tol < 0.0:
        raise ControlInputError("checks.stress_sign: loss_step > 0 и tol ≥ 0")
    if res is None:
        res = c_control_run(book, facts, valuation_date=valuation_date)
    by_loss, by_req = tables if tables is not None else _c_stress_tables(book, facts, res, step)
    bad_loss = [x for x in by_loss if x["dv"] > tol]
    bad_req = [x for x in by_req if x["d_profit"] > tol]
    cells = ({(x["world"], x["regime"], x["scenario"]) for x in bad_loss}
             | {(x["world"], x["regime"], x["stricter"]) for x in bad_req})
    weight = c_point_mass(res)
    excess = [x["dv"] for x in bad_loss] + [x["d_profit"] for x in bad_req]
    return {"loss": {"step": step, "cells": bad_loss, "table": by_loss},
            "requirement": {"cells": bad_req, "table": by_req}, "tol": tol,
            "mass": sum(weight[key] for key in cells), "max_excess": max(excess) if excess else 0.0,
            "worlds": [w for w in res["ctx"]["worlds"] if any(key[0] == w for key in cells)], "ok": not cells}


def _c_stress_tables(book: dict, facts: dict, res: dict, step: float) -> tuple[list, list]:
    """Числа гейта знака стресса: прирост стоимости каждой клетки режима шока при разовом убытке, увеличенном
    на step (пересчёт клеток режима шока на книге с подменой одного ключа), и разность прибыли последнего
    года в каждой паре сценариев с разным требованием Н20.0 последнего года во всех режимах каждого мира — по
    прогону книги res."""
    ctx = res["ctx"]
    scen = list(c_bget(ctx["B"], "capital.reg_scenarios.ids"))
    hit = copy.deepcopy(book)
    loss = hit["regimes"][R_CRISIS]["one_off_loss"]
    loss["amount"] = float(loss["amount"]) - step
    ctx_hit = c_control_context(hit, facts, valuation_date=ctx["clock"]["v"])
    by_loss = []
    for w in ctx["worlds"]:
        for s in scen:
            dv = c_cell_annual(ctx_hit, w, R_CRISIS, s)["v_ri"] - c_cell_of(res, w, R_CRISIS, s)["v_ri"]
            by_loss.append({"world": w, "regime": R_CRISIS, "scenario": s, "dv": dv})
    by_req = []
    for w in ctx["worlds"]:
        for r in c_bget(ctx["B"], "regimes.ids"):
            last = {s: c_cell_of(res, w, r, s)["rows"][-1] for s in scen}
            for upper in scen:
                for lower in scen:
                    if last[upper]["req20"] > last[lower]["req20"]:
                        by_req.append({"world": w, "regime": r, "stricter": upper, "looser": lower,
                                       "d_profit": last[upper]["ni_sh"] - last[lower]["ni_sh"]})
    return by_loss, by_req


def c_printed_margin(res: dict):
    """Печатаемая маржа после фазы роста (ключ книги checks.nim_lt: {target, tolerance, from_year}; нет ключа —
    None): среднее годовых ЧПМ упр. базиса модальной клетки за годы from_year … последний год сетки. Годовая
    ЧПМ — ЧПД года к среднему пяти концов кварталов процентных активов (М§0.3), в упр. базис — через мост."""
    ctx = res["ctx"]
    spec = c_bopt(ctx["B"], "checks.nim_lt")
    if spec is None:
        return None
    if not isinstance(spec, dict) or any(spec.get(k) is None for k in ("target", "tolerance", "from_year")):
        raise ControlInputError("checks.nim_lt: нужны target, tolerance и from_year")
    start = int(spec["from_year"])
    cell = c_cell_of(res, *res["central"]["cell"])
    by_year = {y: c_to_mgmt(ctx["A"], "nim", row["nim_year"]) for y, row in zip(res["years"], cell["rows"])
               if y >= start and row["nim_year"] is not None}
    if not by_year:
        raise ControlInputError("checks.nim_lt.from_year: на сетке нет полного года не раньше него")
    value = sum(by_year.values()) / len(by_year)
    target, tolerance = float(spec["target"]), float(spec["tolerance"])
    return {"cell": res["central"]["label"], "from_year": start, "target": target, "tolerance": tolerance,
            "value": value, "by_year": by_year, "ok": abs(value - target) <= tolerance}


# ============================================================================ уровни после фазы роста

def c_mix_weights(res: dict) -> dict[str, dict]:
    """Веса клеток четырёх смесей узла уровней: модальная клетка (вес 1), слой «свой взгляд», смесь точки и
    слой «рыночные ставки как есть». Вес клетки в слое — вес мира слоя × вероятность режима после A-P2u ×
    P(s | r) (М§3.4, §9); в смеси точки — λ-смесь двух слоёв."""
    B = res["ctx"]["B"]
    worlds = c_layer_weights(B)
    prs = c_bget(B, "joint.reg_prob_given_regime")

    def c_layer(name):
        return {(c["world"], c["regime"], c["scenario"]): (worlds[name].get(c["world"], 0.0)
                                                           * res["posterior"][c["regime"]]
                                                           * float(prs[c["regime"]][c["scenario"]]))
                for c in res["cells"]}

    return {MIX_MODAL: {tuple(res["central"]["cell"]): 1.0}, LAYER_OWN: c_layer(LAYER_OWN),
            MIX_POINT: c_point_mass(res), LAYER_MARKET: c_layer(LAYER_MARKET)}


def c_year_levels(res: dict, weight: dict) -> dict[int, dict]:
    """Годовые ЧПМ, CoR и C/I смеси клеток с весами weight, упр. базис: год → {nim, cor, cir}.

    Метрика смеси — отношение ожидаемых агрегатов: ожидание числителя к ожиданию знаменателя, а не ожидание
    отношений клеток. Числители — годовые суммы ЧПД, резервов и расходов; знаменатели ЧПМ и CoR — среднее
    пяти концов кварталов процентных активов и кредитов по амортизированной стоимости (М§0.3), знаменатель
    C/I — доход NII + F + INS + MISC + FVR (М§4.6). В упр. базис — через мост. Неполный год якоря значения не
    несёт. У смеси из одной клетки это годовые метрики самой клетки."""
    ctx = res["ctx"]
    A = ctx["A"]
    out = {}
    for i, p in enumerate(ctx["periods"]):
        if p["stub"]:
            continue
        tot = dict.fromkeys(("nii", "iea", "llp", "loans", "opex", "income"), 0.0)
        for c in res["cells"]:
            k = weight.get((c["world"], c["regime"], c["scenario"]), 0.0)
            if not k:
                continue
            row = c["rows"][i]
            tot["nii"] += k * row["nii"]
            tot["iea"] += k * _c_ends_mean(row["iea_ends"])
            tot["llp"] += k * row["llp"]
            tot["loans"] += k * _c_ends_mean(row["loans_ac_ends"])
            tot["opex"] += k * row["opex"]
            tot["income"] += k * row["income_cir"]
        if not (tot["iea"] and tot["loans"] and tot["income"]):
            raise ControlInputError(f"уровни года {p['year']}: у смеси нет веса или знаменатель — ноль")
        out[p["year"]] = {"nim": c_to_mgmt(A, "nim", tot["nii"] / tot["iea"]),
                          "cor": c_to_mgmt(A, "cor", tot["llp"] / tot["loans"]),
                          "cir": c_to_mgmt(A, "cir", tot["opex"] / tot["income"])}
    return out


def c_levels(res: dict, from_year: int | None = None):
    """Уровни после фазы роста: простые средние годовых упр. ЧПМ, CoR и C/I за годы from_year … последний год
    сетки — для модальной клетки, слоя «свой взгляд», смеси точки и слоя «рыночные ставки как есть».
    from_year — аргумент или ключ книги checks.window_backtest.from_year; нет ни того, ни другого — None.
    → {from_year, years, mixes: {смесь: {nim, cor, cir, by_year}}}."""
    if from_year is None:
        spec = c_bopt(res["ctx"]["B"], "checks.window_backtest")
        if spec is None:
            return None
        if not isinstance(spec, dict) or spec.get("from_year") is None:
            raise ControlInputError("checks.window_backtest: нужен from_year")
        from_year = spec["from_year"]
    start = int(from_year)
    mixes, years = {}, []
    for name, weight in c_mix_weights(res).items():
        by_year = {y: v for y, v in c_year_levels(res, weight).items() if y >= start}
        if not by_year:
            raise ControlInputError("уровни после фазы роста: на сетке нет полного года не раньше from_year")
        years = sorted(by_year)
        mixes[name] = {x: sum(v[x] for v in by_year.values()) / len(by_year) for x in ("nim", "cor", "cir")}
        mixes[name]["by_year"] = by_year
    return {"from_year": start, "years": years, "mixes": mixes}


def c_window_backtest(res: dict):
    """Гейт сверки с окном фактов (ключ книги checks.window_backtest: {from_year, cor: [низ, верх], cir: [низ,
    верх]}; нет ключа — None): уровни CoR и C/I слоя «рыночные ставки как есть» — средние за годы from_year …
    последний год сетки — внутри коридоров книги, края включены. Маржа гейтом не сверяется: она печатается."""
    spec = c_bopt(res["ctx"]["B"], "checks.window_backtest")
    if spec is None:
        return None
    lanes = {}
    for x in ("cor", "cir"):
        lane = spec.get(x) if isinstance(spec, dict) else None
        if not isinstance(lane, (list, tuple)) or len(lane) != 2 or float(lane[0]) > float(lane[1]):
            raise ControlInputError(f"checks.window_backtest.{x}: нужен коридор [низ, верх]")
        lanes[x] = (float(lane[0]), float(lane[1]))
    levels = c_levels(res)
    layer = levels["mixes"][LAYER_MARKET]
    bad = [x for x, (lo, hi) in lanes.items() if not lo <= layer[x] <= hi]
    return {"from_year": levels["from_year"], "years": levels["years"], "layer": LAYER_MARKET,
            "cor": layer["cor"], "cir": layer["cir"], "nim": layer["nim"], "cor_range": lanes["cor"],
            "cir_range": lanes["cir"], "outside": bad, "ok": not bad}


def c_cir_level(res: dict):
    """Уровень C/I, с которым сверяется цель книги (ключ checks.cir_lt: {target, tolerance, from_year} и
    необязательный scope; нет ключа — None): среднее годовых упр. C/I за годы from_year … последний год сетки.
    Без scope (или scope: modal_cell) — модальная клетка, как у образца; scope: market_layer — слой «рыночные
    ставки как есть», отношение ожидаемых агрегатов."""
    spec = c_bopt(res["ctx"]["B"], "checks.cir_lt")
    if spec is None:
        return None
    if not isinstance(spec, dict) or any(spec.get(k) is None for k in ("target", "tolerance", "from_year")):
        raise ControlInputError("checks.cir_lt: нужны target, tolerance и from_year")
    scope = spec.get("scope")
    if scope not in (None, SCOPE_MODAL, SCOPE_MARKET):
        raise ControlInputError(f"checks.cir_lt.scope: {scope!r}")
    mix = LAYER_MARKET if scope == SCOPE_MARKET else MIX_MODAL
    start = int(spec["from_year"])
    by_year = {y: v["cir"] for y, v in c_year_levels(res, c_mix_weights(res)[mix]).items() if y >= start}
    if not by_year:
        raise ControlInputError("checks.cir_lt.from_year: на сетке нет полного года не раньше него")
    value = sum(by_year.values()) / len(by_year)
    target, tolerance = float(spec["target"]), float(spec["tolerance"])
    return {"scope": scope, "mix": mix, "cell": res["central"]["label"] if mix == MIX_MODAL else None,
            "from_year": start, "target": target, "tolerance": tolerance, "value": value, "by_year": by_year,
            "ok": abs(value - target) <= tolerance}


# ============================================================================ DPS истории (М§5.2, прил. C)

def c_history_kind(B: dict) -> str:
    """Вид теста истории выплат (М§5.2): exact без ключа, cap — потолок политики, none — выключен."""
    kind = c_bopt(B, "dividends.policy.history_test", HIST_EXACT)
    if kind not in (HIST_EXACT, HIST_CAP, HIST_NONE):
        raise ControlInputError(f"dividends.policy.history_test: {kind!r} (М§5.2)")
    return kind


def c_cap_history_ctl(B: dict, facts: dict) -> list[dict]:
    """Тест истории вида cap (М§5.2): по годам фактов dividends.years — сумма объявленных пулов решений
    года против потолка политики × отчётная прибыль акционеров; неполный год — диагностика (ok = None)."""
    cap = c_bopt(B, "dividends.policy.cap")
    if cap is None or not 0.0 < float(cap) <= 1.0:
        raise ControlInputError("dividends.policy.cap: нужен потолок в (0; 1] при тесте истории cap (М§5.2)")
    dv = facts.get("dividends", {})
    out = []
    for year, node in sorted((dv.get("years") or {}).items(), key=lambda kv: int(kv[0])):
        ni = _c_nodeval(node.get("ni_shareholders"))
        if ni is None:
            raise ControlInputError(f"dividends.years.{year}.ni_shareholders: null (М§5.2)")
        pool = 0.0
        for rec in dv.get("history", []):
            if int(_c_nodeval(rec.get("year"))) != int(year):
                continue
            part = _c_nodeval(rec.get("pool_declared"))
            if part is None:
                raise ControlInputError(f"строка dividends.history {rec.get('period')} без pool_declared (М§5.2)")
            pool += float(part)
        complete = bool(_c_nodeval(node.get("complete")))
        limit = float(cap) * float(ni)
        out.append({"year": int(year), "pool": pool, "ni_shareholders": float(ni),
                    "share": pool / float(ni) if float(ni) else None, "cap": float(cap), "limit": limit,
                    "complete": complete, "ok": (pool <= limit + 1e-9) if complete else None})
    return out


def c_dps_history_ctl(B: dict, facts: dict) -> list[dict]:
    """Тест истории выплат вида книги (М§5.2). exact — формула пула на фактах истории в точной десятичной
    арифметике, округление книги; cap — строки теста потолка; none — пусто."""
    kind = c_history_kind(B)
    if kind == HIST_CAP:
        return c_cap_history_ctl(B, facts)
    if kind == HIST_NONE:
        return []
    mode = c_bget(B, "dividends.policy.dps_rounding")
    n_iss = Decimal(str(c_fnum(facts, "shares", "issued_total")))
    out = []
    for rec in facts.get("dividends", {}).get("history", []):
        vals = {k: _c_nodeval(rec.get(k)) for k in ("year", "ni_shareholders", "at1_coupon",
                                                 "tax_statutory", "dps_ordinary")}
        if any(vals[k] is None for k in ("ni_shareholders", "at1_coupon", "tax_statutory")):
            continue
        year = int(vals["year"])
        payout = Decimal(str(c_traj_mean(c_bget(B, "dividends.policy.payout"), year, range(1, QY + 1))))
        base = (Decimal(str(vals["ni_shareholders"]))
                - Decimal(str(vals["at1_coupon"])) * (Decimal(1) - Decimal(str(vals["tax_statutory"]))))
        exact = payout * base * Decimal(1000) / n_iss
        rnd = ROUND_CEILING if mode == "ceil_kopeck" else ROUND_HALF_UP
        dps = exact.quantize(Decimal("0.01"), rounding=rnd)
        declared = vals["dps_ordinary"]
        out.append({"year": year, "exact": float(exact), "dps": float(dps),
                    "declared": None if declared is None else float(declared),
                    "ok": declared is not None and dps == Decimal(str(declared)).quantize(Decimal("0.01"))})
    return out


# ============================================================================ печать сводки

def _c_fmt(x, nd=1):
    return "—" if x is None else f"{x:,.{nd}f}".replace(",", " ")


def c_summary_lines(res: dict, central=None) -> list[str]:
    ctx = res["ctx"]
    rule = central is None
    central = tuple(res["central"]["cell"] if rule else central)
    A = ctx["A"]
    tr = res["transmission"]
    branch = ("годовая, квартальный проход капитала" + (", рост ограничен капиталом" if ctx["growth"] else "")
              if ctx["quarterly"] else "годовая")
    L = [f"Контрольная модель ({branch}), книга " + str(c_bget(ctx["B"], "meta.version")),
         f"дата оценки {ctx['clock']['v']}, период p0 = {ctx['periods'][ctx['clock']['p0']]['label']}, "
         f"e = {ctx['clock']['e']:.4f}",
         f"передача: σ0_A = {tr['sigma0']:.6f}, σ0_L = {tr['sigma0_liab']:.6f} (доля активов {tr['split']}, "
         f"к спредам с {ctx['sigma0_from']}), φ = {tr['phi']:.6f}, "
         f"T_real = {tr['t_real']:.6f}, target_eng = {tr['target_eng']:.6f}, T(W) = "
         + ", ".join(f"{w} {v:.4f}" for w, v in tr["t_local"].items()),
         f"раскладка сжатия: доля кредитных книг {tr['phi_split']}, φ_A = {tr['phi_assets']:.6f}, "
         f"φ_L = {tr['phi_liab']:.6f}; кредитная маржа стационара: "
         + ", ".join(f"{w} {v:.4f}" for w, v in tr["loan_margin"].items()),
         "эффективные LT-спреды: " + "; ".join(
             f"{b}: " + ", ".join(f"{w} {v:.4f}" for w, v in ws.items()) for b, ws in tr["lt_spread"].items()),
         "пары: " + ", ".join(f"{k} {'—' if v is None else f'{v:.6f}'}" for k, v in tr["pairs"].items())
         + f"; ROE-эквивалент T* = {tr['roe_equiv']:.4f}, пар: "
         + ", ".join(f"{k} {'—' if v is None else f'{v:.4f}'}" for k, v in tr["roe_equiv_pairs"].items()),
         f"RWA_0 модели = {_c_fmt(ctx['rwa0'])} (Базель {_c_fmt(A['rwa_basel'])})",
         f"вероятности режимов: " + ", ".join(f"{r} {p:.4f}" for r, p in res["posterior"].items()),
         f"мост B(v) = {_c_fmt(res['bridge_amount'], 2)}, D_pend = {_c_fmt(res['pending_amount'], 2)}, "
         f"дисконт за управление = {res['governance']:.4f}, год шока кризиса {res['shock_year']}"]
    for name in LAYERS:
        ly = res["layers"][name]
        L.append(f"слой {name}: V0 = {_c_fmt(ly['v0'])}, BV_v = {_c_fmt(ly['bv_v'])}, P/B = {ly['pb']:.3f}, "
                 f"цена = {ly['price']:.2f} ₽")
    L.append(f"низ = {res['low']:.2f} ₽, верх = {res['high']:.2f} ₽, λ = {res['lam']}, "
             f"точка = {res['point']:.2f} ₽")
    c = c_cell_of(res, *central)
    cap0 = c["anchor_capital"]
    L.append(f"якорь: Н20.0 модели {cap0['n20']:.4f} (факт {A['n20_fact']:.4f}), "
             f"второй норматив модели {cap0['n11']:.4f} (факт слота n1_1_bank {A['n11_fact']:.4f})")
    if rule:
        L.append(f"центральная клетка по правилу: {res['central']['label']}, вероятность в слое «свой взгляд» "
                 f"{res['central']['probability']:.4f}, вес сценария {res['central']['scenario_weight']:.2f}")
    L.append(f"клетка {'/'.join(central)}: V = {_c_fmt(c['v_ri'])}, V_DDM = {_c_fmt(c['v_ddm'])}, BV_v = {_c_fmt(c['bv_v'])}, "
             f"X_T = {_c_fmt(c['x_t'])}, запас LA над минимумом = {_c_fmt(c['hla'])} (порог связывания "
             f"{_c_fmt(c['h_star'])}), доход на избыток = "
             f"{_c_fmt(c['y_x'])} (ставка смеси {c['y_bal']:.4f}), ROE'_T = {c['roe_t']:.4f}, "
             f"k_T = {c['k_t']:.4f}, g_T = {c['g_t']:.4f}, "
             f"TV_RI = {_c_fmt(c['tv_ri'])}, доля терминала = {c['terminal_share']:.3f}")
    head = ["год", "ЧПД", "резервы", "FVC", "ЧКД", "расходы", "непроф.", "прочее", "PBT", "ЧП акц.", "CI", "BV",
            "RWA", "Н20.0", "Н20.1", "ЧПМ", "CoR", "ROE", "DPS за год"]
    L.append(" | ".join(head))
    for p, row in zip(ctx["periods"], c["rows"]):
        dec = c["decisions"].get(p["year"])
        L.append(" | ".join([p["label"] + ("*" if p["stub"] else ""), _c_fmt(row["nii"]), _c_fmt(row["llp"]),
                             _c_fmt(row["fvc"]),
                             _c_fmt(row["fees"]), _c_fmt(row["opex"]), _c_fmt(row["noncore"]), _c_fmt(row["misc"]),
                             _c_fmt(row["pbt"]), _c_fmt(row["ni_sh"]), _c_fmt(row["ci"]), _c_fmt(row["bv"]),
                             _c_fmt(row["rwa"]), f"{row['n20']:.4f}", f"{row['n11']:.4f}",
                             f"{row['nim']:.4f}", f"{row['cor']:.4f}", f"{row['roe']:.4f}",
                             "—" if dec is None else f"{dec['dps']:.2f}"]))
    if ctx["quarterly"]:
        L.append("год | рост кредитных книг: потенциальный | фактический | доля урезанного | min λ | "
                 "навёрстывание | треб. Н20.0 с глиссадой | Н20.1 с глиссадой | дивиденд модели")
        for p, row in zip(ctx["periods"], c["rows"]):
            L.append(" | ".join([p["label"] + ("*" if p["stub"] else ""),
                                 "—" if row["growth_potential"] is None else f"{row['growth_potential']:.4f}",
                                 "—" if row["growth_actual"] is None else f"{row['growth_actual']:.4f}",
                                 f"{row['cut_share']:.4f}", f"{row['lam_min']:.4f}", _c_fmt(row["catch_up"]),
                                 f"{row['req20_glide']:.4f}", f"{row['req11_glide']:.4f}", _c_fmt(row["div_model"], 2)]))
        L.append("DPS кварталов прибыли: " + ", ".join(
            f"{d['period']} {d['dps']:.2f} ({d['source']})" for d in c["decisions_q"]))
    L.append("клетки (V_RI, млрд ₽; цена ₽; |V_DDM/V_RI − 1|):")
    for cc in res["cells"]:
        L.append(f"  {cc['world']} {cc['regime']:<8} {cc['scenario']:<8} V = {_c_fmt(cc['v_ri'])} "
                 f"цена {cc['price']:.1f} P/B {cc['pb']:.3f} ROE'_T {cc['roe_t']:.4f} k_T {cc['k_t']:.4f} "
                 f"X_T {_c_fmt(cc['x_t'])} ddm {abs(cc['v_ddm'] / cc['v_ri'] - 1):.1e}")
    for h in res["dps_history"]:
        if res["history_test"] == HIST_CAP:
            verdict = "диагностика (год неполный)" if h["ok"] is None else "ok" if h["ok"] else "ПРЕВЫШЕНИЕ"
            L.append(f"потолок выплат {h['year']}: объявлено {_c_fmt(h['pool'], 3)}, отчётная прибыль акционеров "
                     f"{_c_fmt(h['ni_shareholders'], 3)}, доля {h['share']:.4f} при потолке {h['cap']}, {verdict}")
            continue
        L.append(f"DPS истории {h['year']}: формула {h['dps']:.2f} (точно {h['exact']:.5f}), "
                 f"объявлен {h['declared']}, {'ok' if h['ok'] else 'РАСХОЖДЕНИЕ'}")
    if res["divisor"] != res["shares_out"]:
        L.append(f"делитель N_div = {_c_fmt(res['divisor'], 3)} млн шт. (в обращении {_c_fmt(res['shares_out'], 3)})")
    return L


def c_gate_lines(book: dict, facts: dict, res: dict) -> list[str]:
    """Числа гейтов знака, печатаемая маржа и уровни после фазы роста строками сводки (ключ --gates): два-три
    прогона сетки сверх основного; уровни считаются по клеткам основного прогона."""
    sign = c_volume_sign(book, facts, res)
    L = ["знак объёмных эффектов" + (" (обе стороны — без ограничения роста)" if sign["growth_constraint_off"] else "")
         + f": точка {sign['point']:.2f} → {sign['point_free']:.2f} ₽, сдвиг {sign['d_point']:+.2f} ₽; миры: "
         + ", ".join(f"{w} {d:+.2f}" for w, d in sign["d_world"].items())
         + ("; ключа checks.volume_sign в книге нет — гейта нет" if sign["ok"] is None
            else f"; допуск {sign['tol']} ₽, условие гейта {'выполнено' if sign['ok'] else 'нарушено'}")]
    stress = c_stress_sign(book, facts, res)
    if stress is None:
        L.append("знак стресса: ключа checks.stress_sign в книге нет — гейта нет")
    else:
        L.append(f"знак стресса (убыток больше на {_c_fmt(stress['loss']['step'])} млрд ₽, допуск {stress['tol']} млрд ₽): "
                 f"клеток с ростом стоимости {len(stress['loss']['cells'])} из {len(stress['loss']['table'])}, "
                 f"пар сценариев с ростом прибыли {len(stress['requirement']['cells'])} из "
                 f"{len(stress['requirement']['table'])}; масса {stress['mass']:.4f}, наибольшее превышение "
                 f"{_c_fmt(stress['max_excess'], 2)} млрд ₽" + ("" if stress["ok"] else "; миры: " + ", ".join(stress["worlds"])))
        for x in stress["loss"]["cells"]:
            L.append(f"  убыток: {x['world']}/{x['regime']}/{x['scenario']} стоимость {x['dv']:+.2f} млрд ₽")
        for x in stress["requirement"]["cells"]:
            L.append(f"  требование: {x['world']}/{x['regime']} {x['stricter']} против {x['looser']} "
                     f"прибыль {x['d_profit']:+.2f} млрд ₽")
    margin = c_printed_margin(res)
    if margin is not None:
        L.append(f"печатаемая маржа после фазы роста, клетка {margin['cell']}, с {margin['from_year']} года: "
                 f"{margin['value']:.4f} при цели {margin['target']} ± {margin['tolerance']}")
    window = c_window_backtest(res)
    if window is not None:
        names = {MIX_MODAL: "модальная клетка", LAYER_OWN: "слой «свой взгляд»", MIX_POINT: "смесь точки",
                 LAYER_MARKET: "слой «рыночные ставки как есть»"}
        for mix, lv in c_levels(res)["mixes"].items():
            L.append(f"уровни с {window['from_year']} года, {names[mix]}: ЧПМ {lv['nim']:.4f}, CoR {lv['cor']:.4f}, "
                     f"C/I {lv['cir']:.4f}")
        L.append(f"сверка с окном фактов, слой «рыночные ставки как есть»: CoR {window['cor']:.4f} в коридоре "
                 f"{window['cor_range'][0]}…{window['cor_range'][1]}, C/I {window['cir']:.4f} в коридоре "
                 f"{window['cir_range'][0]}…{window['cir_range'][1]} — "
                 + ("выполнено" if window["ok"] else "нарушено: " + ", ".join(window["outside"])))
    level = c_cir_level(res)
    if level is not None:
        where = "слой «рыночные ставки как есть»" if level["cell"] is None else f"клетка {level['cell']}"
        L.append(f"уровень C/I для цели книги, {where}, с {level['from_year']} года: {level['value']:.4f} при цели "
                 f"{level['target']} ± {level['tolerance']}")
    return L


def _c_jsonable(x):
    if isinstance(x, dict):
        return {str(k): _c_jsonable(v) for k, v in x.items() if k != "ctx"}
    if isinstance(x, (list, tuple)):
        return [_c_jsonable(v) for v in x]
    if isinstance(x, (dt.date,)):
        return x.isoformat()
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def c_cli(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Контрольная модель: годовая, с квартальным проходом капитала (М§17)")
    ap.add_argument("--book", help="машинная книга (по умолчанию data/assumptions/assumptions.yaml)")
    ap.add_argument("--draft", action="store_true", help="шаблон книги + миры и надстройка (своя сборка)")
    ap.add_argument("--worlds-lt", default="", help="узел LT кривой миров для --draft: N=<доля>,H=<доля>")
    ap.add_argument("--facts", help="каталог фактов (по умолчанию data/facts)")
    ap.add_argument("--date", help="дата оценки YYYY-MM-DD (по умолчанию — книги)")
    ap.add_argument("--json", help="записать полный результат в JSON")
    ap.add_argument("--gates", action="store_true", help="числа гейтов знака, печатаемая маржа и уровни после фазы роста (ещё два-три прогона)")
    a = ap.parse_args(argv)
    if a.draft:
        lt = {k: float(v) for k, v in (kv.split("=") for kv in a.worlds_lt.split(",") if kv)}
        book = c_book_from_draft(curve_lt=lt)
    else:
        book = c_book_machine(Path(a.book) if a.book else None)
    facts = c_facts_bundle(Path(a.facts) if a.facts else None)
    res = c_control_run(book, facts, valuation_date=a.date)
    for line in c_summary_lines(res) + (c_gate_lines(book, facts, res) if a.gates else []):
        print(line)
    if a.json:
        Path(a.json).write_bytes(json.dumps(_c_jsonable(res), ensure_ascii=False, indent=1).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(c_cli())
