# -*- coding: utf-8 -*-
"""Числа книги, которые следуют из суждений и из пути баланса, — вывод на ядре одной командой (MODEL §3.5).

Часть ключей книги — не суждения, а корни правил: их значение следует из суждения и из решения передачи ставки либо
из пути баланса клеток. Лист выводит их на ядре с включённым ограничением роста. Суждения, заданные числом, лист не
трогает: связи расходов и услуг с портфелем, премии роста, цель передачи, уровень маржи — ключ цели
`nii.nim_lt_target_mgmt`, стационарная маржа мира уровня `nii.transmission.level_world` на составе баланса якоря, —
и цель расходов к доходам (`checks.cir_lt`) читаются из книги.

Где считается каждое число:
  * решением передачи на составе баланса якоря — доли σ0 и φ на кредитных книгах и уровень мира-опоры решателя
    под суждение об уровне маржи (печать и проверка: ключ книги лист не меняет);
  * на МОДАЛЬНОЙ КЛЕТКЕ (мир с наибольшим весом слоя «свой взгляд» × режим с наибольшей вероятностью × его модальный
    сценарий капитала) — ближний сдвиг маржи, инструменты капитала и их стоимость, спред услуг года якоря;
  * на том, что судит гейт `cir_lt` (ключ `checks.cir_lt.scope`: `market_layer` — слой «рыночные ставки как есть»,
    отношение ожидаемых агрегатов; без ключа — модальная клетка), — корни расходов, концы оси уровня расходов и
    оба конца оси-связки гибкости.

Шаги — в порядке зависимости:
  bridge        мост упр. ↔ движок фактов — печать и сверка;
  level         суждение об уровне маржи — печать и проверка: ключ цели `nii.nim_lt_target_mgmt` равен стационарной
                марже мира уровня на составе баланса якоря; рядом — стационарная маржа миров и уровень мира-опоры,
                который решатель передачи нашёл под суждение;
  splits        доли σ0 и φ на кредитных книгах по правилам книги (A-N7, A-N8) при ключе и цели передачи книги;
  near          ближний сдвиг ЧПМ: 3-й и 4-й кварталы года якоря — путь книги; далее прямая к марже, которую клетка
                печатает в первом квартале года схода без сдвига; с года схода — ноль;
  t2            инструменты капитала: траектория в рублях, держащая долю якоря в RWA клетки;
  cost          стоимость прироста инструментов сверх якоря: спред к оптовому фондированию × внешняя доля прироста
                (доля внешних инструментов на якоре — лист capital) × прирост — траекторией `other.misc_net_real`
                в ценах базового года;
  fees          спред услуг года якоря: рост услуг г/г в оставшихся кварталах года якоря идёт от факта — равен
                середине между ростом последнего отчётного квартала и ростом отчётной части года;
  opex          корни реального роста расходов под C/I упр. того, что судит гейт `cir_lt`: второе полугодие года
                якоря — уровень первого полугодия с сезонной разностью прошлого года; цель гейта в 2030 году, в 2032
                году и в среднем за годы гейта; концы оси уровня расходов — корни под 44 и 50 %.
Шаги splits … opex связаны (доли двигают спреды, маржа — капитал и рост, рост — расходы и инструменты) и
повторяются, пока каждое выводимое число не перестанет меняться: мера — изменение числа к величине, которой оно
управляет (инструменты и «прочее» — к своему значению; сдвиг маржи — к уровню маржи; спред услуг и корни расходов —
к темпу 1 + r); порог и наибольшее число кругов — ключи командной строки. После сходимости выводятся:
  transmission  цель передачи ставки (суждение книги): решатель в центре и на концах оси — сжатие φ, стационарная маржа
                миров, парные передачи, запас гейта пола спреда; мир уровня на оси неподвижен (проверка); верх оси —
                наибольшая цель не выше структурной оценки, которую решатель решает;
  ends          ось уровня маржи — само суждение: на её концах печатаются уровень мира-опоры и запас гейта пола
                спреда; низ оси доли φ — наименьшая доля, при которой гейт стоимости средств клиентов к ключевой
                ставке ещё проходит (не ниже прежнего низа оси);
                ось-связка «гибкость расходов и услуг к портфелю»: при связях каждого конца корни расходов и спред
                услуг, при которых C/I (полугодие года якоря, 2030, 2032, среднее лет гейта) и уровень услуг (год
                якоря, 2030 год, последний год сетки) те же, что в центре; коридор доли оптового фондирования по сетке;
                окно фактов (поля `checks.window_backtest`): наименьший, наибольший и средний квартал окна по упр.
                ЧПМ, стоимости риска и расходам к доходам — ряды эмитента фактов; доля кредитов в процентных активах
                в определении движка — среднее концов кварталов окна по истории баланса фактов, доля якоря — счёт ядра;
  need          проверка, а не правило: отношение кредитов к средствам клиентов модальной клетки по годам и «нужда
                баланса» — уровень премии роста средств клиентов (форма оси премии), при котором кредиты модальной
                клетки равны её средствам клиентов на конец названного года; на каждой пробе связанные шаги выводятся
                заново. Саму премию лист не трогает: она суждение книги.
Результат — строки для шаблона книги и out/derive_out.json (`keys` — значения с точностью записи шаблона). После
вывода числа ЗАМОРАЖИВАЮТСЯ: «цена правила», справочные варианты, оси полосы, обратный расчёт и сравнение версий их не
пересчитывают — иначе более жёсткое требование к капиталу увеличивало бы прибыль.

Запуск из корня репозитория (книга и факты — те, что читает ядро):
  python -B data/assumptions/evidence/path/derive_on_engine.py                 # все шаги, печать строк шаблона
  python -B data/assumptions/evidence/path/derive_on_engine.py --steps bridge,level --no-write
  python -B data/assumptions/evidence/path/derive_on_engine.py --start data/assumptions/evidence/path/out/derive_start.json
                                                               # повтор вывода, давшего замороженные числа книги
Запуск без --start начинает с чисел самой книги: на замороженной книге это ещё один круг связанных шагов — числа
остаются в пределах точности записи.
Код выхода: 0 — выведено; 2 — ядро ещё не исполняет ветви книги; 1 — отказ книги, фактов или поиска.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "capital"))
import instrument_spread  # noqa: E402

NEAR_BOOK_PATH = {"2026Q3": 0.1153, "2026Q4": 0.1148}   # путь книги, упр.: месячные формы банка за июль–август 2026 года
#                                          (два основания и их прошлая ошибка — лист near_margin.py, суждение A-C4b)
NEAR_LAST_YEAR = 2029                    # последний год ближнего сдвига: с 2030 года — 0
NIM_AXIS_STATIONARY = (0.103, 0.116)     # концы оси суждения об уровне маржи — стационарной марже мира уровня (низ — средняя
#                                          окна за вычетом неопределённости переноса на другие ставки; верх — лучший квартал окна)
NIM_KEY, LEVEL_WORLD = "nii.nim_lt_target_mgmt", "nii.transmission.level_world"
OPEX_AXIS_CIR = (0.44, 0.50)             # концы оси уровня расходов в C/I упр.
OPEX_GROUPS = (("2027", "2028", "2029", "2030"), ("2031", "2032"))   # годы одного корня; последний год группы — год цели
CIR_ANCHOR_HALF = 0.4636                 # C/I упр. второго полугодия года якоря: уровень первого полугодия с сезонной
#                                          разностью прошлого года (лист pnl, шаг 3: «ориентир C/I упр. 2П2026»)
FEES_KEYS = ("2027", "2028", "2029", "2030")   # годы среднего корня спреда услуг (после года якоря, до LT)
FEES_LT_FROM = 2031
BUNDLE_ENDS = {"low": {"opex.volume_link": 0.3, "fees.volume_link": 0.4},
               "high": {"opex.volume_link": 0.7, "fees.volume_link": 0.8}}
TRANSMISSION_AXIS = (0.0, 0.12)          # ось цели передачи — суждение книги, диапазон свидетельств: низ — ноль (история
#                                          знака не определяет); верх — структурная оценка баланса якоря. Шаг проверяет,
#                                          что решатель решает цель на концах; не решает на верху — верх опускается до
#                                          наибольшей решаемой цели
HISTORY_FILE = HERE.parent / "nii" / "inputs" / "stage1" / "calib" / "nii" / "out" / "transmission_out.json"
MISC_FILE = HERE.parent / "pnl" / "out" / "misc_tax_nci.json"
SHARE_STEP = 0.01                        # доли σ0 и φ пишутся с шагом 0,01, вниз
PHI_AXIS_LOW = 0.30                      # низ оси доли φ — не ниже этой доли и не дальше порога гейта стоимости средств клиентов
#                                          к ключевой ставке; если предел гейта пола спреда опускает центр ниже — низ оси 0
FUNDS_GATE = "checks.funds_cost_to_key"  # гейт стоимости средств клиентов: сторож раскладки сжатия со стороны средств
WHOLESALE_MARGIN = 0.05                  # запас коридора доли оптового фондирования вокруг счёта ядра
PREMIUM_PATHS = ("volumes.funds_share_drift.retail", "volumes.funds_share_drift.corporate")
PREMIUM_SHAPE = {"2027": 1.0, "2028": 1.0, "2029": 0.8, "2030": 0.6, "2031": 0.4}   # форма оси премии средств: уровень в
#                                          2027–2028 годах и сход к нулю к 2032 году (доли уровня по годам)
NEED_YEAR = 2030                         # «нужда баланса»: кредиты модальной клетки равны её средствам клиентов на конец года
NEED_ROUNDS = 3                          # кругов связанных шагов на пробе уровня премии
MARKET_LAYER, MODAL_SCOPE = "market_layer", "modal_cell"
STEPS = ("bridge", "level", "splits", "near", "t2", "cost", "fees", "opex", "transmission", "ends", "need")
LINKED = ("splits", "near", "t2", "cost", "fees", "opex")
WAVE = "ядро ещё не исполняет ветви книги второй формы банка"
QUIET = [False]                          # пробы «нужды баланса» повторяют связанные шаги молча


def say(*args) -> None:
    if not QUIET[0]:
        print(*args)


class NeedCore(RuntimeError):
    """Ядро не готово к выводу: нет ветви, ряда клетки или функции."""


def repo_root() -> Path:
    """Корень репозитория: каталог с model/book.py выше листа."""
    root = HERE
    while not (root / "model" / "book.py").exists():
        if root.parent == root:
            raise NeedCore("не найден каталог model/ выше листа — запуск из дерева репозитория")
        root = root.parent
    return root


class Engine:
    """Тонкая обёртка над ядром: книга с подменами → модальная клетка и сетка."""

    def __init__(self, book_path: Path | None, facts_dir: Path | None):
        root = repo_root()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from model import book_schema
            from model import levels
            from model.book import load_book, load_facts
            from model.cell import run_cell
            from model.credit import bridge_from_facts
            from model.grid import make_context, modal_cell, run_grid, year_mgmt
            from model.live import live_from_book
            from model.nii import solve_transmission
            from model.uncertainty import trial_book
        except ImportError as exc:                              # ядро в сборке
            raise NeedCore(f"{WAVE}: {exc}") from exc
        self.schema, self.run_cell, self.make_context = book_schema, run_cell, make_context
        self.modal_cell, self.year_mgmt, self.solve, self.trial_book = modal_cell, year_mgmt, solve_transmission, trial_book
        self.run_grid, self.live_from_book, self.levels = run_grid, live_from_book, levels
        self.BookError = book_schema.BookError
        self.facts = load_facts(facts_dir)
        try:
            self.book = load_book(book_path, facts=self.facts)
        except book_schema.BookError as exc:
            if "не реализовано" in str(exc):
                raise NeedCore(f"{WAVE}:\n  " + str(exc).replace("\n", "\n  ")) from exc
            raise
        pending = getattr(book_schema, "pending", None)
        left = pending(self.book.source if hasattr(self.book, "source") else self.book.data) if pending else []
        if left:
            raise NeedCore(f"{WAVE}:\n  " + "\n  ".join(left))
        self.bridge = bridge_from_facts(self.facts)
        self.overrides: dict = {}                              # выведенные ключи: путь → значение (без округления записи)
        self.evaluations = 0
        self.grids = 0

    def current(self, extra: dict | None = None):
        ov = dict(self.overrides)
        ov.update(extra or {})
        return self.trial_book(self.book, ov) if ov else self.book

    def cell(self, extra: dict | None = None):
        """(контекст, модальная клетка) книги с выведенными ключами и подменами `extra`."""
        book = self.current(extra)
        ctx = self.make_context(book, self.facts)
        key = self.modal_cell(book, ctx.posterior)
        self.evaluations += 1
        return ctx, self.run_cell(ctx, *key)

    def grid(self, extra: dict | None = None):
        """Сетка книги с выведенными ключами и подменами `extra` (цена, дата и реестр — книги)."""
        book = self.current(extra)
        self.grids += 1
        return self.run_grid(book, self.facts, self.live_from_book(book, self.facts))

    def value(self, path: str):
        """Текущее значение ключа: выведенное, иначе — книги."""
        return copy.deepcopy(self.overrides[path]) if path in self.overrides else copy.deepcopy(self.book.get(path))


# ------------------------------------------------------------------ помощники
def bisect(fn, lo: float, hi: float, steps: int = 60, tol: float = 1e-10) -> float:
    """Корень монотонной fn на [lo; hi] (знаки на концах обязаны различаться): хорда с поправкой «Иллинойс» — отрезок
    всегда держит корень, шаг сходится быстрее деления пополам; стоп — отрезок или невязка меньше `tol`."""
    f_lo, f_hi = fn(lo), fn(hi)
    if f_lo == 0:
        return lo
    if f_hi == 0:
        return hi
    if f_lo * f_hi > 0:
        raise RuntimeError(f"на отрезке [{lo}; {hi}] корня нет: значения {f_lo:+.6f} и {f_hi:+.6f}")
    side = 0
    x = lo
    for _ in range(steps):
        x = (lo * f_hi - hi * f_lo) / (f_hi - f_lo)
        f_x = fn(x)
        if abs(f_x) < tol or abs(hi - lo) < tol:
            return x
        if f_x * f_hi > 0:
            hi, f_hi = x, f_x
            if side == -1:
                f_lo /= 2
            side = -1
        else:
            lo, f_lo = x, f_x
            if side == 1:
                f_hi /= 2
            side = 1
    return x


def flow(d: dict) -> str:
    """Словарь в строку потока YAML: ключи времени — в кавычках, LT и LT_from — без."""
    parts = []
    for k, v in d.items():
        key = k if k in ("LT", "LT_from") else json.dumps(str(k))
        if isinstance(v, float):                                # без экспоненты: число шаблона читает человек
            text = f"{v:.9f}".rstrip("0")
            v = text + "0" if text.endswith(".") else text
        parts.append(f"{key}: {v}")
    return "{" + ", ".join(parts) + "}"


def floor_to(x: float, step: float) -> float:
    return round(int(x / step + 1e-9) * step, 6)


def nim_mgmt_q(eng: Engine, cell, q: int) -> float:
    return float(eng.bridge.to_mgmt_nim(float(cell.quarters["nim"][q])))


def anchor_quarters(ctx) -> list[int]:
    """Прогнозные кварталы года якоря."""
    tl = ctx.timeline
    return [q for q in tl.quarters_of_year(tl.anchor_year) if q >= 1]


def cir_scope(book) -> str:
    """Что судит гейт долгосрочного C/I: слой «рыночные ставки как есть» или модальная клетка (ключ книги)."""
    return str(dict(book.get("checks.cir_lt")).get("scope", MODAL_SCOPE))


def subject(eng: Engine, run) -> tuple[dict, str]:
    """Вероятности клеток того, что судит гейт `cir_lt`, и подпись: слой — вероятности слоя; модальная клетка —
    единица у одной клетки (смесь из одной клетки даёт ряды самой клетки)."""
    book = run.ctx.book
    if cir_scope(book) == MARKET_LAYER:
        return dict(run.layers["macro_neutral"].prob), "слой «рыночные ставки как есть»"
    key = eng.modal_cell(book, run.ctx.posterior)
    return {c.key: (1.0 if c.key == key else 0.0) for c in run.cells}, "модальная клетка " + "/".join(key)


def cir_year(eng: Engine, run, prob: dict, year: int) -> float:
    """C/I упр. года смеси клеток (отношение ожидаемых агрегатов — та же функция, что у гейта и узла уровней)."""
    return float(eng.levels.mix_year(run, prob, year)["mgmt"]["cir"])


def cir_quarters(eng: Engine, run, prob: dict, qs) -> float:
    """C/I упр. прогнозных кварталов `qs` смеси клеток: ожидаемые расходы к ожидаемому доходу (ЧПД, услуги,
    страхование, прочее, переоценка облигаций), мостом в упр. базис."""
    ex = lambda name: sum(float(eng.levels.expect(run, prob, name, q)) for q in qs)  # noqa: E731
    return float(eng.bridge.to_mgmt_cir(ex("opex") / sum(ex(k) for k in ("nii", "fees", "ins", "misc", "fvr"))))


def fees_year(eng: Engine, run, prob: dict, year: int) -> float:
    """Услуги нетто года смеси клеток (факт отчётных кварталов плюс ожидание)."""
    return float(eng.levels.year_flow(run, prob, "fees", year))


def year_sum(ctx, cell, name: str, year: int) -> float:
    return sum(float(cell.quarters[name][q]) for q in ctx.timeline.quarters_of_year(year) if 1 <= q <= ctx.timeline.Q)


def fees_traj(s0: float, mid: float, lt: float, anchor_year: int) -> dict:
    d = {str(anchor_year): s0}
    d.update({y: mid for y in FEES_KEYS})
    d.update({"LT": lt, "LT_from": FEES_LT_FROM})
    return d


def opex_traj(base: dict, anchor_year: int, r0: float, r1: float, r2: float, r3: float) -> dict:
    d = dict(base)
    d[str(anchor_year)] = r0
    d.update({k: r1 for k in OPEX_GROUPS[0]})
    d.update({k: r2 for k in OPEX_GROUPS[1]})
    d["LT"] = r3
    return d


def level_world(book) -> str:
    """Мир уровня книги (`nii.transmission.level_world`): ключ цели маржи — стационарная маржа этого мира на составе
    баланса якоря. Книга без ключа — отказ: суждение об уровне маржи в мире окна не задано."""
    world = book.opt(LEVEL_WORLD)
    if world is None:
        raise RuntimeError(f"книга без ключа {LEVEL_WORLD}: суждение об уровне маржи в мире окна не задано")
    return str(world)


def stationary_mgmt(eng: Engine, world: str, extra: dict | None = None) -> float:
    """Стационарная маржа мира на составе баланса якоря, упр. базис."""
    tr = eng.solve(eng.current(extra), eng.facts, eng.bridge)
    return float(eng.bridge.to_mgmt_nim(float(tr.nss[world])))


# ------------------------------------------------------------------ шаги
def step_bridge(eng: Engine, out: dict) -> None:
    b = eng.bridge
    out["bridge"] = {"nim": b.nim_value, "cor": b.cor_value, "cir": b.cir_value}
    say(f"мост упр. ↔ движок (факты): ЧПМ {b.nim_value:+.6f}, CoR {b.cor_value:+.6f}, C/I {b.cir_value:+.6f}")


def _floor_headroom(book, tr) -> tuple[float, str, str]:
    floors = book.get("checks.lt_spread_floor")
    return min((tr.lt_spread[b][w] - float(floors[b]), b, w) for b in tr.lt_spread for w in tr.lt_spread[b])


def _solved(tr, target: float) -> bool:
    return abs(tr.t_real - target) < 1e-9 and tr.phi >= 0


def step_transmission(eng: Engine, out: dict) -> None:
    book = eng.current()
    centre = float(book.get("nii.transmission.target"))
    top = TRANSMISSION_AXIS[1]
    while top > centre and not _solved(eng.solve(eng.current({"nii.transmission.target": top}), eng.facts, eng.bridge), top):
        top = round(top - 0.01, 2)
    rows = {}
    world, key = level_world(book), float(book.get(NIM_KEY))
    drift = 0.0                                                 # наибольший уход стационарной маржи мира уровня от ключа на оси
    for name, t in (("low", TRANSMISSION_AXIS[0]), ("centre", centre), ("high", top)):
        tr = eng.solve(eng.current({"nii.transmission.target": t}), eng.facts, eng.bridge)
        gap = _floor_headroom(book, tr)
        drift = max(drift, abs(float(eng.bridge.to_mgmt_nim(float(tr.nss[world]))) - key))
        rows[name] = {"target": t, "phi": round(tr.phi, 4), "t_real": round(tr.t_real, 9), "solved": _solved(tr, t),
                      "nss": {w: round(eng.bridge.to_mgmt_nim(v), 5) for w, v in tr.nss.items()},
                      "reference_level": round(float(eng.bridge.to_mgmt_nim(float(tr.reference_level))), 5),
                      "pairs": {k: None if v is None else round(v, 4) for k, v in tr.pairs.items()},
                      "floor_headroom": [round(gap[0], 5), gap[1], gap[2]]}
    out["transmission"] = {"axis": [TRANSMISSION_AXIS[0], top], "structural_top": TRANSMISSION_AXIS[1],
                           "top_is_solver_limit": top < TRANSMISSION_AXIS[1], "level_world": world,
                           "level_world_fixed": drift < 1e-9, "level_world_drift": drift, "rows": rows}
    say(f"nii.transmission.target: {centre} (суждение книги); ось {TRANSMISSION_AXIS[0]}…{top}"
        + (" — верх опущен до наибольшей решаемой цели" if top < TRANSMISSION_AXIS[1] else " — решатель решает цель на всей оси")
        + f"; стационарная маржа мира уровня {world} на оси "
        + ("неподвижна" if drift < 1e-9 else f"УХОДИТ от ключа на {100 * drift:.4f} п.п."))
    for name, r in rows.items():
        say(f"   {name:6s} цель {r['target']:+.2f}: φ {r['phi']:.3f}, решено: {'да' if r['solved'] else 'НЕТ'}; стационарная ЧПМ упр. миров "
            + ", ".join(f"{w} {100 * v:.2f} %" for w, v in r["nss"].items())
            + "; пары " + ", ".join(f"{k} {'—' if v is None else format(v, '+.3f')}" for k, v in r["pairs"].items())
            + f"; запас пола спреда {100 * r['floor_headroom'][0]:+.2f} п.п. ({r['floor_headroom'][1]}, мир {r['floor_headroom'][2]})")


def step_level(eng: Engine, out: dict) -> None:
    """Суждение об уровне маржи — печать и проверка, ключа лист не меняет: ключ цели — стационарная маржа мира
    уровня на составе баланса якоря; уровень мира-опоры решатель передачи находит под него сам."""
    book = eng.current()
    world, key = level_world(book), float(book.get(NIM_KEY))
    tr = eng.solve(book, eng.facts, eng.bridge)
    levels = {w: round(eng.bridge.to_mgmt_nim(float(v)), 5) for w, v in tr.nss.items()}
    got = float(eng.bridge.to_mgmt_nim(float(tr.nss[world])))
    ref = float(eng.bridge.to_mgmt_nim(float(tr.reference_level)))
    out["level"] = {"key": key, "world": world, "stationary": round(got, 9), "stationary_by_world": levels,
                    "reference_world": str(tr.reference_world), "reference_level": round(ref, 6), "sigma0": round(tr.sigma0, 5)}
    say(f"{NIM_KEY}: {key:.5f}    # суждение книги: стационарная маржа мира {world} на составе якоря {100 * got:.3f} %; "
        "по мирам: " + ", ".join(f"{w} {100 * v:.2f} %" for w, v in levels.items())
        + f"; выведенный уровень мира-опоры {tr.reference_world} {100 * ref:.3f} %; σ0 {100 * tr.sigma0:+.2f} п.п.")


def step_splits(eng: Engine, out: dict) -> None:
    """Доли σ0 и φ на кредитных книгах — ключи, заданные правилом (A-N7, A-N8): пересчитываются при новом уровне маржи и
    новой цели передачи. σ0: наибольшая доля, при которой гейт пола спреда проходит в мире отсчёта (сжатия там нет).
    φ: наибольшая доля не выше доли по наклонам истории (сжатие истории к полному сжатию φ), при которой гейт пола
    спреда проходит в центре книги."""
    book = eng.current()
    floors = book.get("checks.lt_spread_floor")
    ref = str(book.get("nii.transmission.reference_world"))
    full = eng.solve(eng.current({"nii.sigma0_split": 1.0, "nii.phi_split": 0.0}), eng.facts, eng.bridge)
    none = eng.solve(eng.current({"nii.sigma0_split": 0.0, "nii.phi_split": 0.0}), eng.facts, eng.bridge)
    limit_s = 1.0
    for b in full.lt_spread:
        drop = none.lt_spread[b][ref] - full.lt_spread[b][ref]              # сдвиг всей долей на активах
        if drop > 1e-12:
            limit_s = min(limit_s, (none.lt_spread[b][ref] - float(floors[b])) / drop)
    s_split = floor_to(max(0.0, limit_s), SHARE_STEP)
    p0 = eng.solve(eng.current({"nii.sigma0_split": s_split, "nii.phi_split": 0.0}), eng.facts, eng.bridge)
    p1 = eng.solve(eng.current({"nii.sigma0_split": s_split, "nii.phi_split": 1.0}), eng.facts, eng.bridge)
    limit_p, tight = 1.0, None
    for b in p0.lt_spread:
        for w in p0.lt_spread[b]:
            drop = p0.lt_spread[b][w] - p1.lt_spread[b][w]
            if drop > 1e-12:
                cap = (p0.lt_spread[b][w] - float(floors[b])) / drop
                if cap < limit_p:
                    limit_p, tight = cap, (b, w)
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))["history_phi_assets"]
    by_history = float(history) / p0.phi
    p_limit = floor_to(max(0.0, limit_p), SHARE_STEP)
    p_split = min(floor_to(min(by_history, 1.0), SHARE_STEP), p_limit)
    eng.overrides["nii.sigma0_split"], eng.overrides["nii.phi_split"] = s_split, p_split
    tr = eng.solve(eng.current(), eng.facts, eng.bridge)
    gap = _floor_headroom(book, tr)
    out["splits"] = {"sigma0_split": s_split, "sigma0_limit": round(limit_s, 4), "phi_split": p_split,
                     "phi_by_history": round(by_history, 4), "phi_limit": round(limit_p, 4), "phi_limit_at": list(tight or ()),
                     "history_compression": round(float(history), 4), "phi": round(tr.phi, 4),
                     "axis_sigma0": [0.0, s_split], "axis_phi": [PHI_AXIS_LOW if p_split > PHI_AXIS_LOW else 0.0, p_limit],
                     "floor_headroom": [round(gap[0], 5), gap[1], gap[2]],
                     "lt_spread": {b: {w: round(v, 5) for w, v in row.items()} for b, row in tr.lt_spread.items()}}
    say(f"nii.sigma0_split: {s_split}    # предел гейта пола спреда в мире {ref}: {limit_s:.3f}")
    say(f"nii.phi_split: {p_split}    # по истории наклонов {history:.3f} / φ {p0.phi:.3f} = {by_history:.3f}; предел гейта {limit_p:.3f}"
        + (f" ({tight[0]}, мир {tight[1]})" if tight else "") + f"; ось {out['splits']['axis_phi'][0]}…{p_limit}; "
        f"запас пола в центре {100 * gap[0]:+.2f} п.п. ({gap[1]}, мир {gap[2]})")


def _near_traj(shift: dict[str, float]) -> dict:
    """Квартальные ключи → траектория книги: ключ года — среднее своих квартальных ключей, LT 0 с года после последнего."""
    traj: dict = {}
    years = sorted({k[:4] for k in shift})
    for y in years:
        qs = [(k, v) for k, v in sorted(shift.items()) if k.startswith(y)]
        for k, v in qs:
            traj[k] = v
        traj[y] = sum(v for _, v in qs) / len(qs)
    traj.update({"LT": 0.0, "LT_from": int(years[-1]) + 1})
    return traj


def step_near(eng: Engine, out: dict) -> None:
    ctx, cell = eng.cell()
    tl = ctx.timeline
    quarters = [q for q in range(1, tl.Q + 1) if int(tl.period(q)[:4]) <= NEAR_LAST_YEAR]
    q_end = quarters[-1] + 1                                    # первый квартал года схода: сдвига нет
    fixed = {tl.index(p): v for p, v in NEAR_BOOK_PATH.items()}
    q_from = max(fixed)
    have = eng.value("regimes.near_nim_shift")
    shift = {tl.period(q): float(have.get(tl.period(q), 0.0)) for q in quarters}
    for _ in range(40):                                         # сдвиг += желаемая ЧПМ − ЧПМ клетки
        eng.overrides["regimes.near_nim_shift"] = _near_traj(shift)
        ctx, cell = eng.cell()
        level_end = nim_mgmt_q(eng, cell, q_end)
        worst = 0.0
        for q in quarters:
            want = fixed[q] if q in fixed else fixed[q_from] + (level_end - fixed[q_from]) * (q - q_from) / (q_end - q_from)
            miss = want - nim_mgmt_q(eng, cell, q)
            shift[tl.period(q)] += miss
            worst = max(worst, abs(miss))
        if worst < 2e-8:
            break
    traj = _near_traj(shift)
    eng.overrides["regimes.near_nim_shift"] = traj
    ctx, cell = eng.cell()
    path = {tl.period(q): round(nim_mgmt_q(eng, cell, q), 5) for q in range(1, min(tl.Q, q_end + 4) + 1)}
    step = path[tl.period(q_end)] - path[tl.period(q_end - 1)]
    slope = (path[tl.period(q_end)] - fixed[q_from]) / (q_end - q_from)
    out["near"] = {"nim_mgmt_path": path, "level_first_free_quarter": path[tl.period(q_end)],
                   "step_into_first_free_quarter": round(step, 6), "line_step_per_quarter": round(slope, 6)}
    say("regimes.near_nim_shift: упр. ЧПМ клетки: " + ", ".join(f"{p} {100 * v:.2f}" for p, v in list(path.items())[:6])
        + f" … {tl.period(q_end - 1)} {100 * path[tl.period(q_end - 1)]:.2f}, {tl.period(q_end)} {100 * path[tl.period(q_end)]:.2f} (без сдвига); "
        f"шаг прямой {100 * slope:+.3f} п.п. за квартал, шаг на стыке {100 * step:+.3f} п.п.")


def step_t2(eng: Engine, out: dict) -> None:
    ctx, cell = eng.cell()
    tl = ctx.timeline
    t2_anchor = eng.facts.v("capital", "t2_recognized")
    if t2_anchor is None:
        raise RuntimeError("факты: нет узла capital.t2_recognized — уровень инструментов капитала якоря")
    share = float(t2_anchor) / float(cell.quarters["rwa"][0])
    last_year = int(tl.period(tl.Q)[:4])
    traj: dict = {}
    for _ in range(40):                                         # неподвижная точка: инструменты ↔ RWA клетки
        rwa = cell.quarters["rwa"]
        new: dict = {tl.period(0): float(t2_anchor)}            # ключ квартала якоря — факт: строка якоря воспроизводит норматив
        tail = []
        for q in range(1, tl.Q + 1):
            p = tl.period(q)
            v = share * float(rwa[q])
            if int(p[:4]) == last_year:
                tail.append(v)
            else:
                new[p] = v
        new[str(last_year)] = sum(tail) / len(tail)
        new["LT"] = new[str(last_year)]
        moved = max(abs(new[k] - traj.get(k, 0.0)) / new[k] for k in new)
        traj = new
        eng.overrides["capital.n20.t2"] = traj
        ctx, cell = eng.cell()
        if moved < 1e-9:
            break
    out["t2"] = {"share_of_rwa": round(share, 5), "first": round(traj[tl.period(1)], 2), "last": round(traj["LT"], 2)}
    say(f"capital.n20.t2: доля якоря {100 * share:.3f} % RWA клетки; {tl.period(0)} {traj[tl.period(0)]:.3f} → {tl.period(1)} "
        f"{traj[tl.period(1)]:.1f} → {last_year} {traj['LT']:.1f} млрд ₽")


def step_cost(eng: Engine, out: dict) -> None:
    """Стоимость прироста инструментов сверх якоря: спред к оптовому фондированию × внешняя доля прироста × средний
    прирост квартала × дни / 365; годовая сумма — в ценах базового года (делением на индекс цен мира клетки)
    вычитается из уровня «прочего». Внешняя доля — доля внешних инструментов на якоре (лист capital): купон по
    внутригрупповым инструментам в прибыли группы исключается."""
    book = eng.current()
    ctx, cell = eng.cell()
    tl = ctx.timeline
    spread = instrument_spread.spread_to_wholesale(float(book.get("nii.books.wholesale.spread")["LT"]))
    external = instrument_spread.external_share(str(book.get("meta.facts_date")))
    s = float(spread["to_wholesale"]) * float(external["share"])
    index = ctx.worlds[cell.world].price_index
    shares = {int(k): float(v) for k, v in book.get("other.misc_quarter_shares").items()}
    level = misc_level()
    t2, anchor = ctx.prep.t2, float(ctx.prep.t2[0])
    years = sorted({int(tl.period(q)[:4]) for q in range(1, tl.Q + 1)})
    traj, cost = {}, {}
    for y in years:
        qs = [q for q in tl.quarters_of_year(y) if 1 <= q <= tl.Q]
        c = sum(((float(t2[q - 1]) + float(t2[q])) / 2 - anchor) * s * tl.d(q) / 365 for q in qs)
        weight = sum(float(index[q]) * shares[int(tl.period(q)[5])] for q in qs)
        cost[str(y)] = c
        traj[str(y)] = level - c / weight
    traj["LT"] = traj[str(years[-1])]
    eng.overrides["other.misc_net_real"] = traj
    out["cost"] = {"spread": spread, "external": external, "spread_on_increment": round(s, 6), "level": level,
                   "cost_nominal": {k: round(v, 3) for k, v in cost.items()},
                   "increment_year_end": {str(y): round(float(t2[tl.quarters_of_year(y)[-1]]) - anchor, 1) for y in years}}
    say(f"other.misc_net_real: спред к оптовому фондированию {100 * spread['to_wholesale']:.2f} п.п. (надбавка к ключевой "
        f"{100 * spread['margin_to_key']:.2f} п.п. минус спред оптового фондирования {100 * spread['wholesale_lt_spread']:+.2f} п.п.) × "
        f"внешняя доля {100 * external['share']:.1f} % = {100 * s:.2f} п.п. на прирост; стоимость прироста, млрд ₽: "
        + ", ".join(f"{y} {v:.1f}" for y, v in cost.items()))


def misc_level() -> float:
    """Уровень «прочего» без стоимости инструментов капитала (A-O3): медиана квартала × 4, млрд ₽ в ценах года якоря —
    число листа pnl (то же правило сверяет pnl_book.py)."""
    return float(round(json.loads(MISC_FILE.read_text(encoding="utf-8"))["median_q"] * 4))


def _fees_growth(eng: Engine, ctx, cell) -> float:
    """Средний рост услуг г/г прогнозных кварталов года якоря."""
    hist = ctx.prep.hist["fees"]
    qs = anchor_quarters(ctx)
    return sum(float(cell.quarters["fees"][q]) / float(hist[q - 4]) - 1 for q in qs) / len(qs)


def fees_goal(eng: Engine, ctx) -> dict:
    """Цель роста услуг г/г оставшихся кварталов года якоря: середина между ростом последнего отчётного квартала и
    ростом отчётной части года (оба — факты)."""
    hist = ctx.prep.hist["fees"]
    tl = ctx.timeline
    done = [q for q in tl.quarters_of_year(tl.anchor_year) if q <= 0]
    last = float(hist[0]) / float(hist[-4]) - 1
    part = sum(float(hist[q]) for q in done) / sum(float(hist[q - 4]) for q in done) - 1
    return {"last_quarter": last, "reported_part_of_year": part, "goal": (last + part) / 2}


def step_fees(eng: Engine, out: dict) -> None:
    ctx, _ = eng.cell()
    y0 = ctx.timeline.anchor_year
    have = eng.value("fees.growth_vs_wages")
    mid, lt = float(have.get(FEES_KEYS[0], 0.0)), float(have.get("LT", 0.0))
    goal = fees_goal(eng, ctx)

    def miss(x: float) -> float:
        c, cell = eng.cell({"fees.growth_vs_wages": fees_traj(x, mid, lt, y0)})
        return _fees_growth(eng, c, cell) - goal["goal"]

    free = miss(0.0) + goal["goal"]
    s0 = bisect(miss, -0.20, 0.20)
    eng.overrides["fees.growth_vs_wages"] = fees_traj(s0, mid, lt, y0)
    ctx, cell = eng.cell()
    hist = ctx.prep.hist["fees"]
    by_q = {ctx.timeline.period(q): round(float(cell.quarters["fees"][q]) / float(hist[q - 4]) - 1, 5) for q in anchor_quarters(ctx)}
    out["fees"] = {"goal": {k: round(v, 5) for k, v in goal.items()}, "without_spread": round(free, 5), "growth_by_quarter": by_q}
    say(f"fees.growth_vs_wages.{y0}: {s0:+.5f}    # рост услуг г/г: " + ", ".join(f"{p} {100 * v:+.1f} %" for p, v in by_q.items())
        + f"; цель {100 * goal['goal']:.2f} % = середина между {100 * goal['last_quarter']:.1f} % (последний квартал) и "
        f"{100 * goal['reported_part_of_year']:.1f} % (отчётная часть года); без спреда формула даёт {100 * free:.1f} %")


def _gate_years(book) -> tuple[int, ...]:
    return tuple(range(int(book.get("checks.cir_lt")["from_year"]), int(book.get("meta.last_period")[:4]) + 1))


def _opex_roots(eng: Engine, goals: dict, start: tuple, extra: dict | None = None) -> tuple:
    """Корни расходов (год якоря, 2027–2030, 2031–2032, LT) под цели C/I того, что судит гейт: полугодие года
    якоря, год конца первой группы, год конца второй, среднее лет гейта. `extra` — подмены книги (конец оси-связки)."""
    book = eng.current(extra)
    base = copy.deepcopy(dict(book.get("opex.real_growth")))
    y0 = int(book.get("meta.anchor_period")[:4])
    lt_years = _gate_years(book)

    def cir_of(roots: tuple, what) -> float:
        ov = dict(extra or {})
        ov["opex.real_growth"] = opex_traj(base, y0, *roots)
        run = eng.grid(ov)
        prob, _ = subject(eng, run)
        if what == "half":
            return cir_quarters(eng, run, prob, anchor_quarters(run.ctx))
        return sum(cir_year(eng, run, prob, y) for y in what) / len(what)

    r0, r1, r2, r3 = start
    r0 = bisect(lambda x: cir_of((x, r1, r2, r3), "half") - goals["half"], -0.15, 0.25)
    r1 = bisect(lambda x: cir_of((r0, x, r2, r3), (int(OPEX_GROUPS[0][-1]),)) - goals["first"], -0.08, 0.12)
    r2 = bisect(lambda x: cir_of((r0, r1, x, r3), (int(OPEX_GROUPS[1][-1]),)) - goals["second"], -0.08, 0.12)
    r3 = bisect(lambda x: cir_of((r0, r1, r2, x), lt_years) - goals["lt"], -0.05, 0.05)
    return r0, r1, r2, r3


def _opex_start(eng: Engine, extra: dict | None = None) -> tuple:
    have = eng.value("opex.real_growth")
    y0 = str(int(eng.book.get("meta.anchor_period")[:4]))
    return float(have[y0]), float(have[OPEX_GROUPS[0][0]]), float(have[OPEX_GROUPS[1][0]]), float(have["LT"])


def _cir_picture(eng: Engine, extra: dict | None = None) -> dict:
    """C/I упр. того, что судит гейт, и рядом — модальной клетки: полугодие года якоря, годы целей, среднее лет гейта."""
    run = eng.grid(extra)
    book = run.ctx.book
    prob, title = subject(eng, run)
    tl = run.ctx.timeline
    years = [y for y in range(tl.anchor_year + 1, tl.last_year + 1)]
    path = {str(y): cir_year(eng, run, prob, y) for y in years}
    gate = eng.levels.cir_lt_value(run)
    lt_years = _gate_years(book)
    key = eng.modal_cell(book, run.ctx.posterior)
    one = {c.key: (1.0 if c.key == key else 0.0) for c in run.cells}
    return {"subject": title, "half": cir_quarters(eng, run, prob, anchor_quarters(run.ctx)), "first": path[OPEX_GROUPS[0][-1]],
            "second": path[OPEX_GROUPS[1][-1]], "lt": sum(path[str(y)] for y in lt_years) / len(lt_years), "path": path,
            "gate_value": None if gate is None else float(gate["value"]),
            "modal_lt": sum(cir_year(eng, run, one, y) for y in lt_years) / len(lt_years),
            "modal_path": {str(y): cir_year(eng, run, one, y) for y in years}}


def step_opex(eng: Engine, out: dict) -> None:
    book = eng.current()
    gate = book.get("checks.cir_lt")
    target = float(gate["target"])
    base = copy.deepcopy(dict(book.get("opex.real_growth")))
    y0 = int(book.get("meta.anchor_period")[:4])
    missing = [k for g in OPEX_GROUPS for k in g if k not in base]
    if missing or "LT" not in base or str(y0) not in base:
        raise RuntimeError(f"opex.real_growth: нет ключей {missing or ['LT', str(y0)]} — форма траектории не та, что у листа")
    goals = {"half": CIR_ANCHOR_HALF, "first": target, "second": target, "lt": target}
    roots = _opex_roots(eng, goals, _opex_start(eng))
    traj = opex_traj(base, y0, *roots)
    eng.overrides["opex.real_growth"] = traj
    pic = _cir_picture(eng)
    out["opex"] = {"subject": pic["subject"], "scope": cir_scope(book),
                   "cir_mgmt_path": {k: round(v, 5) for k, v in pic["path"].items()}, "cir_anchor_half": round(pic["half"], 5),
                   "cir_lt_mean": round(pic["lt"], 5), "target": target, "goal_anchor_half": CIR_ANCHOR_HALF,
                   "modal_cell_cir_lt_mean": round(pic["modal_lt"], 5),
                   "modal_cell_cir_path": {k: round(v, 5) for k, v in pic["modal_path"].items()}}
    say(f"opex.real_growth: {y0} {roots[0]:+.5f}; {OPEX_GROUPS[0][0]}–{OPEX_GROUPS[0][-1]} {roots[1]:+.5f}; "
        f"{OPEX_GROUPS[1][0]}–{OPEX_GROUPS[1][-1]} {roots[2]:+.5f}; LT {roots[3]:+.5f}    # C/I упр., {pic['subject']}: 2-е полугодие {y0} года "
        f"{100 * pic['half']:.2f} %, {OPEX_GROUPS[0][-1]} — {100 * pic['first']:.2f} %, {OPEX_GROUPS[1][-1]} — {100 * pic['second']:.2f} %, "
        f"среднее лет гейта {100 * pic['lt']:.2f} % (цель {100 * target:.0f} %); модальная клетка в среднем за годы гейта — "
        f"{100 * pic['modal_lt']:.2f} %")


# ------------------------------------------------------------------ концы осей (после сходимости, на записанных числах)
def ends_opex_axis(eng: Engine, out: dict) -> None:
    base = eng.value("opex.real_growth")
    year = int(OPEX_GROUPS[0][-1])

    def miss(shift: float, goal: float) -> float:
        d = dict(base)
        d.update({k: float(base[k]) + shift for k in OPEX_GROUPS[0]})
        run = eng.grid({"opex.real_growth": d})
        prob, _ = subject(eng, run)
        return cir_year(eng, run, prob, year) - goal

    lo = bisect(lambda x: miss(x, OPEX_AXIS_CIR[0]), -0.10, 0.05)
    hi = bisect(lambda x: miss(x, OPEX_AXIS_CIR[1]), -0.05, 0.10)
    out["ends"]["opex_axis"] = {"low": round(lo, 3), "high": round(hi, 3), "cir": list(OPEX_AXIS_CIR)}
    say(f"ось «Расходы: реальный рост {OPEX_GROUPS[0][0]}–{OPEX_GROUPS[0][-1]}»: low {round(lo, 3)}, high {round(hi, 3)} "
        f"(C/I {year} года {OPEX_AXIS_CIR[0]:.0%} и {OPEX_AXIS_CIR[1]:.0%})")


def ends_margin_axis(eng: Engine, out: dict) -> None:
    """Концы оси уровня маржи — само суждение (ключ цели — стационарная маржа мира уровня): на концах печатаются
    стационарная маржа мира уровня по счёту решателя, выведенный уровень мира-опоры и запас гейта пола спреда."""
    world = level_world(eng.current())
    lo, hi = NIM_AXIS_STATIONARY
    got, ref, floors = [], [], {}
    for name, k in (("low", lo), ("high", hi)):
        tr = eng.solve(eng.current({NIM_KEY: k}), eng.facts, eng.bridge)
        got.append(round(float(eng.bridge.to_mgmt_nim(float(tr.nss[world]))), 5))
        ref.append(round(float(eng.bridge.to_mgmt_nim(float(tr.reference_level))), 5))
        gap = _floor_headroom(eng.current(), tr)
        floors[name] = [round(gap[0], 5), gap[1], gap[2]]
    out["ends"]["margin_axis"] = {"low": lo, "high": hi, "world": world, "stationary": got,
                                  "stationary_goal": list(NIM_AXIS_STATIONARY), "reference_level": ref, "floor_headroom": floors}
    say(f"ось «ЧПМ после фазы роста» и диапазон строки обратного расчёта: low {lo}, high {hi} — само суждение: стационарная маржа мира "
        f"{world} {100 * got[0]:.2f} и {100 * got[1]:.2f} %; уровень мира-опоры на концах {100 * ref[0]:.2f} и {100 * ref[1]:.2f} %; "
        f"запас пола спреда на концах {100 * floors['low'][0]:+.2f} и {100 * floors['high'][0]:+.2f} п.п.")


def ends_phi_axis(eng: Engine, out: dict) -> None:
    """Низ оси доли φ на кредитных книгах: наименьшая доля (вверх до шага записи), при которой гейт стоимости средств
    клиентов к ключевой ставке проходит на записанных числах центра, но не ниже прежнего низа оси. Меньшая доля на
    кредитах — большая добавка к стоимости средств клиентов: дальше порога гейта ось не идёт. Книга без гейта — низ
    прежний."""
    axis = out.setdefault("splits", {}).get("axis_phi")
    centre = float(eng.value("nii.phi_split"))
    gate = eng.current().opt(FUNDS_GATE)
    if axis is None or gate is None or axis[0] == 0.0:
        return
    limit = float(gate["max"])

    def worst(share: float) -> float:
        node = eng.levels.funds_cost_to_key(eng.grid({"nii.phi_split": share}))
        return max(float(row["ratio"]) for row in node["by_world"].values())

    at_floor, at_centre = worst(PHI_AXIS_LOW), worst(centre)
    if at_centre > limit:
        raise RuntimeError(f"гейт стоимости средств клиентов срабатывает в центре книги: {at_centre:.4f} при пороге {limit}")
    low = PHI_AXIS_LOW
    if at_floor > limit:                                        # порог достигается внутри прежней оси
        root = bisect(lambda x: worst(x) - limit, PHI_AXIS_LOW, centre, tol=1e-7)
        low = min(centre, round(math.ceil(root / SHARE_STEP - 1e-9) * SHARE_STEP, 6))
    out["splits"]["axis_phi"] = [low, axis[1]]
    out["ends"]["phi_axis"] = {"low": low, "high": axis[1], "gate_max": limit, "funds_cost_to_key_at_low": round(worst(low), 4),
                               "funds_cost_to_key_at_centre": round(at_centre, 4),
                               "funds_cost_to_key_at_floor": round(at_floor, 4), "floor": PHI_AXIS_LOW}
    say(f"ось «доля φ на кредитных книгах»: low {low}, high {axis[1]} — стоимость средств клиентов к ключевой ставке (наибольшая "
        f"по мирам) на низу {worst(low):.4f}, в центре {at_centre:.4f} при пороге гейта {limit}; при доле {PHI_AXIS_LOW} — {at_floor:.4f}")


def ends_bundle(eng: Engine, out: dict, tol: float) -> None:
    """Ось-связка: при связях конца — корни расходов и спред услуг, при которых C/I и уровень услуг того, что судит
    гейт `cir_lt`, в контрольных точках те же, что в центре. Прочие выведенные числа (ключ цели, сдвиг, инструменты)
    — центра."""
    run = eng.grid()
    prob, title = subject(eng, run)
    tl = run.ctx.timeline
    y0, last_year = tl.anchor_year, tl.last_year
    mid_year = int(FEES_KEYS[-1])
    cir_goal = _cir_picture(eng)
    fee_goal = {"anchor": fees_year(eng, run, prob, y0), "mid": fees_year(eng, run, prob, mid_year),
                "last": fees_year(eng, run, prob, last_year)}
    centre_fees, centre_opex = eng.value("fees.growth_vs_wages"), eng.value("opex.real_growth")
    modal = run.cell(*eng.modal_cell(run.ctx.book, run.ctx.posterior))
    ni_of = lambda cl: {str(y): round(float(cl.annual["ni_sh"][cl.years.index(y)]), 2) for y in (y0, mid_year, last_year)}  # noqa: E731
    result = {}
    for end, links in BUNDLE_ENDS.items():
        fees = [float(centre_fees[str(y0)]), float(centre_fees[FEES_KEYS[0]]), float(centre_fees["LT"])]
        roots = _opex_start(eng)
        rounds = 0
        for rounds in range(1, 9):
            before = fees + list(roots)

            def fee_miss(vals, year, goal):
                ov = dict(links)
                ov["fees.growth_vs_wages"] = fees_traj(vals[0], vals[1], vals[2], y0)
                ov["opex.real_growth"] = opex_traj(centre_opex, y0, *roots)
                r = eng.grid(ov)
                p, _ = subject(eng, r)
                return fees_year(eng, r, p, year) / goal - 1

            fees[0] = bisect(lambda x: fee_miss([x, fees[1], fees[2]], y0, fee_goal["anchor"]), -0.25, 0.25)
            fees[1] = bisect(lambda x: fee_miss([fees[0], x, fees[2]], mid_year, fee_goal["mid"]), -0.15, 0.15)
            fees[2] = bisect(lambda x: fee_miss([fees[0], fees[1], x], last_year, fee_goal["last"]), -0.10, 0.10)
            ov = dict(links)
            ov["fees.growth_vs_wages"] = fees_traj(fees[0], fees[1], fees[2], y0)
            roots = _opex_roots(eng, cir_goal, roots, ov)
            if max(abs(a - b) for a, b in zip(before, fees + list(roots))) < tol:
                break
        ov = dict(links)
        ov["fees.growth_vs_wages"] = fees_traj(*(round(v, 4) for v in fees), y0)
        ov["opex.real_growth"] = opex_traj(centre_opex, y0, *(round(v, 4) for v in roots))
        r = eng.grid(ov)
        p, _ = subject(eng, r)
        pic = _cir_picture(eng, ov)
        paths = dict(links)
        paths.update({f"opex.real_growth.{k}": v for k, v in ov["opex.real_growth"].items() if k != "LT_from"})
        paths.update({f"fees.growth_vs_wages.{k}": v for k, v in ov["fees.growth_vs_wages"].items() if k != "LT_from"})
        result[end] = {"paths": paths, "rounds": rounds,
                       "cir": {k: round(pic[k], 5) for k in ("half", "first", "second", "lt")},
                       "fees": {"anchor": round(fees_year(eng, r, p, y0), 3), "mid": round(fees_year(eng, r, p, mid_year), 3),
                                "last": round(fees_year(eng, r, p, last_year), 3)},
                       "ni_sh_modal_cell": ni_of(r.cell(*eng.modal_cell(r.ctx.book, r.ctx.posterior))), "point": round(float(r.point), 2)}
        say(f"связка, конец {end} (связи {links['opex.volume_link']} / {links['fees.volume_link']}), кругов {rounds}: спред услуг "
            + " / ".join(f"{v:+.4f}" for v in fees) + "; корни расходов " + " / ".join(f"{v:+.4f}" for v in roots))
    order = ["opex.volume_link", "fees.volume_link"] + [f"opex.real_growth.{k}" for k in centre_opex if k != "LT_from"] \
        + [f"fees.growth_vs_wages.{k}" for k in centre_fees if k != "LT_from"]
    out["ends"]["bundle"] = {"subject": title, "paths": order, "low": {p: result["low"]["paths"][p] for p in order},
                             "high": {p: result["high"]["paths"][p] for p in order},
                             "centre": {"cir": {k: round(cir_goal[k], 5) for k in ("half", "first", "second", "lt")},
                                        "fees": {k: round(v, 3) for k, v in fee_goal.items()},
                                        "ni_sh_modal_cell": ni_of(modal), "point": round(float(run.point), 2)},
                             "check": {e: {k: result[e][k] for k in ("cir", "fees", "ni_sh_modal_cell", "point", "rounds")} for e in result}}
    say("   paths: [" + ", ".join(order) + "]")
    for e in ("low", "high"):
        say(f"   {e}: {{" + ", ".join(f"{p}: {out['ends']['bundle'][e][p]}" for p in order) + "}")


def ends_wholesale(eng: Engine, out: dict) -> None:
    """Коридор доли оптового фондирования: счёт ядра на сетке книги с выведенными ключами. Правило: низ — доля якоря
    минус запас, верх — наибольшая доля на конец года по клеткам плюс запас; запас — WHOLESALE_MARGIN; до 0,01."""
    run = eng.grid()
    book = run.ctx.book
    tl = run.ctx.timeline
    ends = [q for q in (tl.quarters_of_year(y)[-1] for y in run.cells[0].years) if 1 <= q <= tl.Q]
    share = lambda c, q: float(c.quarters["wholesale"][q]) / (float(c.quarters["funds"][q]) + float(c.quarters["wholesale"][q]))  # noqa: E731
    modal = run.cell(*eng.modal_cell(book, run.ctx.posterior))
    anchor = share(modal, 0)
    worst = max((max(share(c, q) for q in ends), c.label) for c in run.cells)
    low = min(min(share(c, q) for q in ends) for c in run.cells)
    corridor = [round(int((anchor - WHOLESALE_MARGIN) * 100 + 1e-9) / 100, 2), round(-int(-(worst[0] + WHOLESALE_MARGIN) * 100 - 1e-9) / 100, 2)]
    out["ends"]["wholesale_share"] = {"anchor": round(anchor, 4), "min": round(low, 4), "max": round(worst[0], 4), "max_cell": worst[1],
                                      "modal_by_year": {str(tl.period(q)[:4]): round(share(modal, q), 4) for q in ends},
                                      "corridor": corridor, "margin": WHOLESALE_MARGIN}
    say(f"checks.wholesale_share: {corridor}    # доля якоря {100 * anchor:.1f} %; по {len(run.cells)} клеткам на конец года {100 * low:.1f}…{100 * worst[0]:.1f} % "
        f"(наибольшая — {worst[1]}); запас {100 * WHOLESALE_MARGIN:.0f} п.п.")


WINDOW_METRICS = (("nim", "nim_exact", 5, 4), ("cor", "cor_exact", 5, 5), ("cir", "cir_exact", 5, 5))   # поле окна, узел фактов,
#                                          знаков концов и знаков среднего: точность записи шаблона


def ends_window(eng: Engine, out: dict) -> None:
    """Окно фактов для печати рядом с уровнями (поля `checks.window_backtest`). Кварталы окна — кварталы истории
    баланса фактов (концы кварталов после покупки Росбанка по якорь). Упр. ЧПМ, стоимость риска и расходы к доходам —
    ряды эмитента фактов: наименьший, наибольший и средний квартал. Доля кредитов в процентных активах в определении
    движка (кредитные книги к кредитам, долговым бумагам и ликвидности): окно — среднее концов кварталов по истории
    баланса; якорь — счёт ядра (узел уровней)."""
    history = eng.facts.file("balance")["history"]
    quarters = eng.facts.file("mgmt_quarterly")["quarters"]
    window = sorted(history)
    node: dict = {"quarters": window}
    for name, fact, nd_end, nd_mean in WINDOW_METRICS:
        vals = [float(quarters[q][fact]["v"]) for q in window]
        node[name] = {"min": round(min(vals), nd_end), "max": round(max(vals), nd_end), "mean": round(sum(vals) / len(vals), nd_mean),
                      "min_quarter": window[vals.index(min(vals))], "max_quarter": window[vals.index(max(vals))]}
    share = {q: float(history[q]["loans"]["v"]) / float(history[q]["iea"]["v"]) for q in window}
    facts_node = eng.levels.window_facts(eng.grid())
    node["loans_share"] = {"by_quarter_end": {q: round(v, 5) for q, v in share.items()}, "window": round(sum(share.values()) / len(share), 4),
                           "anchor_on_engine": None if facts_node is None else round(float(facts_node["loans_share"]["anchor"]), 5)}
    out["ends"]["window"] = node
    say("окно фактов " + f"{window[0]}–{window[-1]}: " + "; ".join(
        f"{name} {100 * node[name]['min']:.2f}…{100 * node[name]['max']:.2f} % (среднее {100 * node[name]['mean']:.2f} %)" for name, *_ in WINDOW_METRICS)
        + f"; кредиты в процентных активах (определение движка): окно {100 * node['loans_share']['window']:.2f} %, якорь "
        + ("—" if facts_node is None else f"{100 * node['loans_share']['anchor_on_engine']:.2f} %"))


def diagnostics(eng: Engine, out: dict) -> None:
    """Картина модальной клетки на выведенных ключах: что проверить после вывода."""
    ctx, cell = eng.cell()
    tl = ctx.timeline
    years = [y for y in cell.years if all(q >= 1 for q in tl.quarters_of_year(y)) and all(q <= tl.Q for q in tl.quarters_of_year(y))]
    rows = {}
    for y in cell.years:
        last = [q for q in tl.quarters_of_year(y) if q <= tl.Q][-1]
        qs = [q for q in tl.quarters_of_year(y) if 1 <= q <= tl.Q]
        rows[str(y)] = {
            "loans_to_funds": round(float(cell.quarters["loans"][last]) / float(cell.quarters["funds"][last]), 4),
            "wholesale_share": round(float(cell.quarters["wholesale"][last])
                                     / (float(cell.quarters["funds"][last]) + float(cell.quarters["wholesale"][last])), 4),
            "lam_min": round(min(float(cell.quarters["lam"][q]) for q in qs), 3),
            "cut_share": round(1 - float(cell.quarters["loans"][last]) / float(cell.quarters["loans_potential"][last]), 4),
            "n20": round(float(cell.quarters["n20"][last]), 4),
            "t2_share_of_rwa": round(float(ctx.prep.t2[last]) / float(cell.quarters["rwa"][last]), 5),
            "roe": None if y not in years or cell.annual["roe"][cell.years.index(y)] is None else round(float(cell.annual["roe"][cell.years.index(y)]), 4),
        }
    anchor = {"loans_to_funds": round(float(cell.quarters["loans"][0]) / float(cell.quarters["funds"][0]), 4)}
    near = [q for q in range(0, tl.Q + 1) if tl.year(q) == tl.anchor_year]      # якорь и прогнозные кварталы его года
    funds = {tl.period(q): {"retail": round(float(cell.quarters["funds_retail"][q]), 1),
                            "corporate": round(float(cell.quarters["funds"][q]) - float(cell.quarters["funds_retail"][q]), 1),
                            "total": round(float(cell.quarters["funds"][q]), 1),
                            "loans_to_funds": round(float(cell.quarters["loans"][q]) / float(cell.quarters["funds"][q]), 4)} for q in near}
    out["modal_cell"] = {"label": cell.label, "anchor": anchor, "funds_anchor_year": funds, "years": rows,
                         "roe_t": round(float(cell.roe_t), 4), "k_t": round(float(cell.k_t), 4),
                         "terminal_share": round(float(cell.terminal_share), 4), "flags": sorted(cell.flags)}
    say("   средства клиентов по кварталам года якоря, млрд ₽ (физлица / бизнес / кредиты к средствам): "
        + "; ".join(f"{p} {v['retail']:.1f} / {v['corporate']:.1f} / {100 * v['loans_to_funds']:.1f} %" for p, v in funds.items()))
    say(f"модальная клетка {cell.label}: ROE терминала {100 * cell.roe_t:.1f} % при стоимости капитала {100 * cell.k_t:.1f} %; "
        f"доля терминала {100 * cell.terminal_share:.0f} %; флаги: {sorted(cell.flags) or 'нет'}")
    say("   кредиты к средствам клиентов на конец года (проверка, не правило): якорь " + f"{100 * anchor['loans_to_funds']:.1f} %; "
        + ", ".join(f"{y} {100 * r['loans_to_funds']:.1f}" for y, r in rows.items()))
    worst = max(rows.items(), key=lambda kv: kv[1]["cut_share"])
    say(f"   наибольшая доля урезанного роста — {100 * worst[1]['cut_share']:.1f} % в {worst[0]} году; "
        f"минимум доли прироста по годам: " + (", ".join(f"{y} {r['lam_min']}" for y, r in rows.items() if r["lam_min"] < 1) or "везде 1"))


# ------------------------------------------------------------------ «нужда баланса» премии роста средств клиентов
def premium_overrides(eng: Engine, level: float) -> dict:
    """Траектории премии роста средств клиентов при уровне `level` в форме оси (ключ года якоря — как в книге)."""
    ov = {}
    for path in PREMIUM_PATHS:
        traj = copy.deepcopy(dict(eng.book.get(path)))
        missing = [y for y in PREMIUM_SHAPE if y not in traj]
        if missing:
            raise RuntimeError(f"{path}: нет ключей {missing} — форма траектории не та, что у листа")
        traj.update({y: level * share for y, share in PREMIUM_SHAPE.items()})
        ov[path] = traj
    return ov


def _loans_to_funds(eng: Engine, year: int, extra: dict | None = None) -> float:
    ctx, cell = eng.cell(extra)
    q = ctx.timeline.quarters_of_year(year)[-1]
    return float(cell.quarters["loans"][q]) / float(cell.quarters["funds"][q])


def step_need(eng: Engine, out: dict, tol: float) -> None:
    """«Нужда баланса» (проверка, не правило центра): уровень премии роста средств клиентов в форме её оси, при
    котором кредиты модальной клетки равны её средствам клиентов на конец NEED_YEAR. На каждой пробе связанные шаги
    выводятся заново (число зависит от центра: премия двигает маржу, капитал и рост). Премию книги лист не трогает."""
    keep = copy.deepcopy(eng.overrides)
    book_ratio = _loans_to_funds(eng, NEED_YEAR)
    probes: list[dict] = []

    def ratio_at(level: float) -> float:
        eng.overrides = copy.deepcopy(keep)
        eng.overrides.update(premium_overrides(eng, level))
        QUIET[0] = True
        try:
            scratch: dict = {}
            before = flat(eng)
            for _ in range(NEED_ROUNDS):
                for s in LINKED:
                    RUNNERS[s](eng, scratch)
                after = flat(eng)
                change, _ = worst_change(before, after)
                before = after
                if change < tol:
                    break
        finally:
            QUIET[0] = False
        r = _loans_to_funds(eng, NEED_YEAR)
        probes.append({"level": round(level, 6), "loans_to_funds": round(r, 5)})
        return r

    try:
        x0, x1 = 0.0, 0.05
        f0, f1 = ratio_at(x0) - 1.0, ratio_at(x1) - 1.0
        for _ in range(8):                                      # секущая: отношение почти линейно по уровню премии
            if abs(f1) < 2e-4 or f1 == f0:
                break
            x0, x1, f0 = x1, x1 - f1 * (x1 - x0) / (f1 - f0), f1
            f1 = ratio_at(x1) - 1.0
        need = x1
    finally:
        eng.overrides = keep
    axis = None
    try:
        axes = eng.book.get("valuation.uncertainty.axes")
        axis = next(a for a in axes if any(str(p).startswith(PREMIUM_PATHS[0]) for p in a["paths"]))
    except Exception:                                           # noqa: BLE001 — оси премии в книге нет
        axis = None
    ends = {}
    if axis is not None and axis.get("kind") == "bundle":       # отношение на концах оси — при выведенных числах центра
        for end in ("low", "high"):
            ov = {}
            for path in PREMIUM_PATHS:
                traj = copy.deepcopy(dict(eng.book.get(path)))
                traj.update({p.rsplit(".", 1)[1]: float(v) for p, v in axis[end].items() if p.startswith(path + ".")})
                ov[path] = traj
            ends[end] = round(_loans_to_funds(eng, NEED_YEAR, ov), 4)
    out["need"] = {"year": NEED_YEAR, "shape": PREMIUM_SHAPE, "level": round(need, 4), "loans_to_funds_at_level": probes[-1]["loans_to_funds"],
                   "loans_to_funds_book": round(book_ratio, 4), "loans_to_funds_at_axis_ends": ends, "probes": probes,
                   "relinked_rounds": NEED_ROUNDS}
    say(f"«нужда баланса» (проверка, не правило): премия роста средств клиентов {100 * need:+.1f} п.п. в 2027–2028 годах со сходом к нулю к "
        f"2032 году — при ней кредиты модальной клетки равны её средствам клиентов на конец {NEED_YEAR} года; при премии книги "
        f"отношение {100 * book_ratio:.1f} %" + (f", на концах оси {100 * ends['low']:.1f} и {100 * ends['high']:.1f} %" if ends else "")
        + f"; проб {len(probes)}")


# ------------------------------------------------------------------ сходимость и запись
def flat(eng: Engine) -> dict[str, tuple[float, float]]:
    """Выводимые числа связанных шагов: имя → (значение, величина, к которой относится изменение)."""
    nim = float(eng.value(NIM_KEY))                             # уровень маржи — суждение книги: мера сдвига маржи
    out: dict[str, tuple[float, float]] = {}
    for path in ("nii.sigma0_split", "nii.phi_split"):
        out[path] = (float(eng.value(path)), 1.0)
    for k, v in eng.value("regimes.near_nim_shift").items():
        if k != "LT_from":
            out[f"regimes.near_nim_shift.{k}"] = (float(v), nim)
    for k, v in eng.value("capital.n20.t2").items():
        out[f"capital.n20.t2.{k}"] = (float(v), float(v))
    for k, v in eng.value("other.misc_net_real").items():
        out[f"other.misc_net_real.{k}"] = (float(v), float(v))
    for name in ("fees.growth_vs_wages", "opex.real_growth"):
        for k, v in eng.value(name).items():
            if k != "LT_from":
                out[f"{name}.{k}"] = (float(v), 1.0 + float(v))
    return out


def worst_change(a: dict, b: dict) -> tuple[float, str]:
    best = (0.0, "")
    for k, (v, scale) in b.items():
        old = a.get(k, (None, None))[0]
        change = float("inf") if old is None else abs(v - old) / abs(scale)
        if change > best[0]:
            best = (change, k)
    return best


def written(eng: Engine) -> dict:
    """Выведенные ключи с точностью записи шаблона."""
    keys: dict = {"nii.sigma0_split": float(eng.value("nii.sigma0_split")), "nii.phi_split": float(eng.value("nii.phi_split"))}
    near = eng.value("regimes.near_nim_shift")
    keys["regimes.near_nim_shift"] = _near_traj({k: round(float(v), 5) for k, v in near.items() if "Q" in k})
    t2 = eng.value("capital.n20.t2")
    first = next(iter(t2))
    keys["capital.n20.t2"] = {k: (round(float(v), 3) if k == first else round(float(v), 1)) for k, v in t2.items()}
    keys["other.misc_net_real"] = {k: round(float(v), 2) for k, v in eng.value("other.misc_net_real").items()}
    keys["fees.growth_vs_wages"] = {k: (v if k == "LT_from" else round(float(v), 4)) for k, v in eng.value("fees.growth_vs_wages").items()}
    keys["opex.real_growth"] = {k: (v if k == "LT_from" else round(float(v), 4)) for k, v in eng.value("opex.real_growth").items()}
    return keys


def frozen_check(eng: Engine, out: dict) -> None:
    """Проверка на записанных (округлённых) ключах: цели гейтов, путь года якоря, доля инструментов."""
    book = eng.current()
    ctx, cell = eng.cell()
    tl = ctx.timeline
    world, key = level_world(book), float(book.get(NIM_KEY))
    stationary = stationary_mgmt(eng, world)
    pic = _cir_picture(eng)
    cir_gate = book.get("checks.cir_lt")
    share0 = float(ctx.prep.t2[0]) / float(cell.quarters["rwa"][0])
    last_year = tl.last_year
    t2_err = max(abs(float(ctx.prep.t2[q]) / float(cell.quarters["rwa"][q]) - share0) for q in range(1, tl.Q + 1) if tl.year(q) != last_year)
    near = [nim_mgmt_q(eng, cell, tl.index(p)) for p in NEAR_BOOK_PATH]
    out["frozen_check"] = {"nim_stationary": round(stationary, 9), "nim_level_world": world,
                           "nim_stationary_ok": abs(stationary - key) <= 1e-9,
                           "cir_lt_value": round(pic["gate_value"] if pic["gate_value"] is not None else pic["lt"], 6),
                           "cir_lt_subject": pic["subject"],
                           "cir_lt_ok": abs(pic["lt"] - float(cir_gate["target"])) <= float(cir_gate["tolerance"]),
                           "cir_lt_modal_cell": round(pic["modal_lt"], 6),
                           "near_anchor_year": [round(v, 6) for v in near], "t2_share_error": round(t2_err, 7),
                           "fees_growth_anchor_year": round(_fees_growth(eng, ctx, cell), 6), "cir_anchor_half": round(pic["half"], 6)}
    say(f"на записанных ключах: стационарная маржа мира уровня {world} {100 * stationary:.3f} % (ключ цели — суждение книги: "
        f"{'равна ключу' if out['frozen_check']['nim_stationary_ok'] else 'НЕ РАВНА КЛЮЧУ'}); C/I лет гейта, {pic['subject']}, {100 * pic['lt']:.3f} % "
        f"(гейт cir_lt {'в допуске' if out['frozen_check']['cir_lt_ok'] else 'ВНЕ ДОПУСКА'}), модальная клетка {100 * pic['modal_lt']:.2f} %; "
        f"путь года якоря " + " / ".join(f"{100 * v:.3f}" for v in near) + f" %; отклонение доли инструментов до {100 * t2_err:.4f} п.п.")


def print_keys(keys: dict) -> None:
    print("— строки шаблона (значения с точностью записи) —")
    for path, v in keys.items():
        print(f"{path}: {flow(v) if isinstance(v, dict) else v}")


RUNNERS = {"bridge": step_bridge, "transmission": step_transmission, "level": step_level, "splits": step_splits, "near": step_near,
           "t2": step_t2, "cost": step_cost, "fees": step_fees, "opex": step_opex}


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="вывод на ядре чисел книги, зависящих от решения передачи и пути баланса")
    ap.add_argument("--book", type=Path, default=None, help="машинная книга (по умолчанию — data/assumptions/assumptions.yaml)")
    ap.add_argument("--facts", type=Path, default=None, help="каталог фактов (по умолчанию — data/facts)")
    ap.add_argument("--steps", default=",".join(STEPS), help="шаги через запятую: " + ", ".join(STEPS))
    ap.add_argument("--rounds", type=int, default=8, help="наибольшее число кругов связанных шагов (по умолчанию 8)")
    ap.add_argument("--tol", type=float, default=1e-4, help="порог сходимости: наибольшее относительное изменение числа за круг")
    ap.add_argument("--no-write", action="store_true", help="не писать out/derive_out.json")
    ap.add_argument("--out", type=Path, default=None, help="куда писать JSON результата (по умолчанию — out/derive_out.json листа)")
    ap.add_argument("--start", type=Path, default=None,
                    help="JSON со стартовыми значениями выводимых ключей (поле keys): вывод начинается с них, а не с чисел "
                         "книги — так повторяется вывод, давший замороженные числа (out/derive_start.json)")
    a = ap.parse_args(argv)
    steps = [s.strip() for s in a.steps.split(",") if s.strip()]
    unknown = [s for s in steps if s not in STEPS]
    if unknown:
        print("незнакомые шаги:", ", ".join(unknown))
        return 1
    out: dict = {}
    try:
        eng = Engine(a.book, a.facts)
        if a.start is not None:                                 # старт вывода — значения до вывода
            eng.overrides.update(json.loads(a.start.read_text(encoding="utf-8"))["keys"])
        book = eng.book
        try:
            constrained = bool(book.get("capital.growth_constraint.enabled"))
        except eng.BookError:                                   # ключа нет — рост задан (форма без ограничения)
            constrained = False
        linked = [s for s in steps if s in LINKED]
        if not constrained and linked:
            print("ВНИМАНИЕ: ограничение роста в книге выключено — числа выводятся на клетке без ограничения")
        print(f"книга {book.get('meta.version')} от {book.get('meta.date')}, якорь {book.get('meta.anchor_period')}; порядок шагов: "
              + " → ".join(steps))
        for s in steps:
            if s not in linked and s not in ("transmission", "ends", "need"):
                RUNNERS[s](eng, out)
        history = []
        if linked:
            before = flat(eng)
            for i in range(1, max(1, a.rounds) + 1):
                print(f"— круг {i} связанных шагов —")
                for s in linked:
                    RUNNERS[s](eng, out)
                after = flat(eng)
                change, where = worst_change(before, after)
                history.append({"round": i, "max_relative_change": change, "at": where})
                print(f"   наибольшее изменение за круг: {change:.2e} ({where})")
                before = after
                if change < a.tol:
                    break
            out["convergence"] = {"tol": a.tol, "rounds": history, "converged": history[-1]["max_relative_change"] < a.tol}
            if not out["convergence"]["converged"]:
                print(f"ВНИМАНИЕ: за {len(history)} кругов сходимость {a.tol:g} не достигнута")
            keys = written(eng)
            eng.overrides.update(copy.deepcopy(keys))           # дальше — на записанных числах
            frozen_check(eng, out)
            diagnostics(eng, out)
            out["keys"] = keys
            if "level" in steps:                                # суждение об уровне — на записанных долях
                step_level(eng, out)
        if "transmission" in steps:                             # решатель на оси цели передачи — на записанных долях
            step_transmission(eng, out)
        if "ends" in steps:
            if not linked:
                out["keys"] = {}
            out["ends"] = {}
            print("— концы осей —")
            ends_opex_axis(eng, out)
            ends_margin_axis(eng, out)
            ends_phi_axis(eng, out)
            ends_bundle(eng, out, a.tol)
            ends_wholesale(eng, out)
            ends_window(eng, out)
        if "need" in steps:
            print("— проверка: кредиты к средствам клиентов и «нужда баланса» —")
            step_need(eng, out, a.tol)
        if linked:
            print_keys(out["keys"])
        out["evaluations"] = {"cells": eng.evaluations, "grids": eng.grids}
    except NeedCore as exc:
        print(str(exc))
        return 2
    except Exception as exc:                                    # отказ книги, фактов, поиска корня
        print(f"ОТКАЗ вывода ({type(exc).__name__}): {exc}")
        return 1
    if not a.no_write:
        target = a.out or HERE / "out" / "derive_out.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"готово: прогонов модальной клетки {eng.evaluations}, сеток {eng.grids}; строки шаблона — в книгу с пометкой «ВЫВЕДЕНО НА ЯДРЕ» и датой")
    return 0


if __name__ == "__main__":
    sys.exit(main())
