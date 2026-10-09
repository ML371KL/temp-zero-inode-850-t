"""Годовой путь смеси клеток и уровни после фазы роста (М§14.5).

Одна функция годового пути (`mix_year`) — у `paths.annual` выпуска, узла `point_path` таблиц книги, узла
`levels` и гейтов, которые судят уровни слоя (`window_backtest`, `cir_lt` с областью «слой», М§14.2). Строка
года смеси — факт отчётных кварталов плюс ожидание клеток под заданными вероятностями; отношения года —
отношение ожидаемых агрегатов (ЧПД к среднему пяти концов кварталов процентных активов, резервы — к средним
кредитам по амортизированной стоимости, расходы — к операционному доходу), а не ожидание отношений клеток.
Упр. базис — правило «год с отчётными кварталами» (`model.grid.year_mgmt`, М§4.6). Смесь из одной клетки
(вероятность 1) даёт годовые ряды самой клетки: модальная клетка считается той же функцией, что слои.
Рядом со строками узел уровней несёт окно фактов, из которого взяты суждения, — подузел `window`
(`window_facts`): числа окна — поля книги в ключе `checks.window_backtest`, доля кредитов якоря — состояние
якоря сетки; строкой уровней окно не является.

Узлы — только при своих ключах книги: `levels` — при `checks.window_backtest` (первый год участка — его
`from_year`), `point_path` — при `checks.point_path: true`, путь фондирования (`funding_path`: кредиты к
средствам клиентов и доля оптового фондирования на конец года) — при коридоре гейта `checks.wholesale_share`,
стационарная маржа гейта `nim_stationary` — при
`checks.nim_stationary`, суждение об уровне маржи (`level_nim`) — при `nii.transmission.level_world`, стоимость
средств клиентов к ключевой ставке — при `checks.funds_cost_to_key`. Нет ключа — узла нет. Все числа считаются на
готовой сетке: новых сеток узлы не требуют.
"""

from __future__ import annotations

from typing import Any, Mapping

from model.book_schema import BookError
from model.grid import LAYER_TITLES, GridRun, modal_cell, point_probabilities, year_mgmt
from model.nii import LEVEL_WORLD, NIM_KEY, level_world

__all__ = ["expect", "year_flow", "quarter_end", "year_mean_end", "mix_year", "mix_dps", "level_rows", "levels",
           "window_facts", "point_path", "funding_path", "cir_lt_value", "stationary_nim", "level_nim",
           "judged_nim", "funds_cost_to_key", "CIR_LT", "WINDOW_BACKTEST", "POINT_PATH", "WHOLESALE_SHARE",
           "FUNDING_METRICS", "NIM_STATIONARY", "FUNDS_COST",
           "MARKET_LAYER", "MODAL_CELL", "LEVEL_ROWS", "LEVEL_METRICS", "MIX_FLOWS", "LEVEL_WORLD", "WINDOW_FIELDS"]

CIR_LT = "checks.cir_lt"                     # цель долгосрочного C/I: {target, tolerance, from_year, scope?}
WINDOW_BACKTEST = "checks.window_backtest"   # {from_year, cor: [низ, верх], cir: [низ, верх]} — включает `levels`
POINT_PATH = "checks.point_path"             # true — узел таблиц книги «годовой путь смеси точки»
WHOLESALE_SHARE = "checks.wholesale_share"   # [низ, верх] — коридор гейта; включает путь фондирования
FUNDING_METRICS = ("loans_to_funds", "wholesale_share")
NIM_STATIONARY = "checks.nim_stationary"     # {world, target, tolerance} — стационарная маржа мира, упр. базис
FUNDS_COST = "checks.funds_cost_to_key"      # {max, from_year} — стоимость средств клиентов к ключевой ставке
MODAL_CELL, MARKET_LAYER = "modal_cell", "market_layer"     # области гейта долгосрочного C/I (`checks.cir_lt.scope`)
POINT = "point"
# Строки узла уровней по порядку печати: модальная клетка, слой «свой взгляд», смесь точки, слой «рыночные
# ставки как есть».
LEVEL_ROWS = (MODAL_CELL, "analytical", POINT, "macro_neutral")
LEVEL_TITLES = {MODAL_CELL: "Модальная клетка", POINT: "Смесь заголовка"}
LEVEL_METRICS = ("nim", "cor", "cir", "loans_share")
MIX_FLOWS = ("nii", "fees", "ins", "misc", "noncore", "opex", "llp", "pbt", "tax", "ni", "ni_sh")
MGMT = ("nim", "cor", "cir")                 # отношения года, которые мост переводит в упр. базис
# Необязательные поля ключа окна фактов (`checks.window_backtest`): наименьший и наибольший квартал окна по марже,
# средние окна и доля кредитов в процентных активах окна — подузел `window` узла уровней.
WINDOW_FIELDS = ("nim", "means", "loans_share")


# ------------------------------------------------------------------ ожидания и годовой путь


class _Mix:
    """Смесь клеток прогона под вероятностями `prob`: веса и ряды клеток читаются один раз, порядок клеток и
    порядок сложения — как у сетки. Счёт годового пути (`mix_year`) и четырёх функций ниже — один."""

    __slots__ = ("run", "weights", "rows")

    def __init__(self, run: GridRun, prob: Mapping):
        self.run = run
        self.weights = [prob[c.key] for c in run.cells]
        self.rows = [c.quarters for c in run.cells]

    def expect(self, name: str, q: int) -> float | None:
        total = 0.0
        for w, row in zip(self.weights, self.rows):
            x = row[name][q]
            if x is None:
                return None
            total += w * float(x)
        return total

    def year_flow(self, name: str, year: int) -> float | None:
        tl, hist = self.run.ctx.timeline, self.run.ctx.prep.hist
        total = 0.0
        for q in tl.quarters_of_year(year):
            if q <= 0:
                x = hist.get(name, {}).get(q)
            elif q <= tl.Q:
                x = self.expect(name, q)
            else:
                x = None
            if x is None:
                return None
            total += x
        return total

    def quarter_end(self, name: str, q: int) -> float | None:
        if q >= 0:
            return self.expect(name, q) if q <= self.run.ctx.timeline.Q else None
        return self.run.ctx.prep.hist_bal.get(q, {}).get(name)

    def year_mean_end(self, name: str, year: int) -> float | None:
        qs = self.run.ctx.timeline.quarters_of_year(year)
        vals = [self.quarter_end(name, q) for q in [qs[0] - 1] + qs]
        vals = [x for x in vals if x is not None]
        return sum(vals) / len(vals) if vals else None


def expect(run: GridRun, prob: Mapping, name: str, q: int) -> float | None:
    """Ожидание ряда клеток в квартале q под вероятностями `prob`; нет числа хотя бы у одной клетки — None."""
    total = 0.0
    for c in run.cells:
        x = c.quarters[name][q]
        if x is None:
            return None
        total += prob[c.key] * float(x)
    return total


def year_flow(run: GridRun, prob: Mapping, name: str, year: int) -> float | None:
    """Сумма строки за год: факт отчётных кварталов (q ≤ 0) + ожидание по вероятностям; год за сеткой или без
    факта — None."""
    return _Mix(run, prob).year_flow(name, year)


def quarter_end(run: GridRun, prob: Mapping, name: str, q: int) -> float | None:
    """Остаток на конец квартала: ожидание клеток (q ≥ 0) или факт конца квартала до якоря."""
    if q >= 0:
        return expect(run, prob, name, q) if q <= run.ctx.timeline.Q else None
    return run.ctx.prep.hist_bal.get(q, {}).get(name)


def year_mean_end(run: GridRun, prob: Mapping, name: str, year: int) -> float | None:
    """Среднее пяти концов кварталов года (конец прошлого года и четыре конца года; нет конца — среднее
    доступных, М§0.3)."""
    return _Mix(run, prob).year_mean_end(name, year)


def mix_year(run: GridRun, prob: Mapping, year: int) -> dict[str, Any]:
    """Строка года смеси клеток под вероятностями `prob` (без округления): потоки `MIX_FLOWS`, переоценка
    облигаций `fvr` кварталов сетки, средние остатки, отношения движка `nim`, `cor`, `cir`, они же в упр.
    базисе (`mgmt`), ROE и доля кредитов в процентных активах (`loans_share` — средние пяти концов кварталов).
    Отношения — отношение ожидаемых агрегатов."""
    tl = run.ctx.timeline
    mix = _Mix(run, prob)
    f = {k: mix.year_flow(k, year) for k in MIX_FLOWS}
    model_qs = [q for q in tl.quarters_of_year(year) if 1 <= q <= tl.Q]
    fvr = sum(mix.expect("fvr", q) for q in model_qs) if model_qs else 0.0
    avg_iea, avg_ac, avg_bv = (mix.year_mean_end(k, year) for k in ("iea", "loans_ac", "bv"))
    nim = None if f["nii"] is None or not avg_iea else f["nii"] / avg_iea
    cor = None if f["llp"] is None or not avg_ac else f["llp"] / avg_ac
    inc = (None if None in (f["nii"], f["fees"], f["ins"], f["misc"])
           else f["nii"] + f["fees"] + f["ins"] + f["misc"] + fvr)
    cir = None if inc in (None, 0) or f["opex"] is None else f["opex"] / inc
    # упр. метрики года: отчётные кварталы — раскрытым упр. фактом, прогнозные — мостом (М§4.6)
    mgmt = {k: (None if v is None else year_mgmt(run.ctx, k, year, v, mix.expect))
            for k, v in (("nim", nim), ("cor", cor), ("cir", cir))}
    return {"year": year, "flows": f, "fvr": fvr, "income": inc, "avg_iea": avg_iea, "avg_ac": avg_ac,
            "avg_bv": avg_bv, "nim": nim, "cor": cor, "cir": cir, "mgmt": mgmt,
            "roe": None if f["ni_sh"] is None or not avg_bv else f["ni_sh"] / avg_bv,
            "loans_share": _loans_share(mix, year)}


def _loans_share(mix: _Mix, year: int) -> float | None:
    """Доля кредитов в процентных активах года: среднее концов кварталов кредитных книг к среднему тех же
    концов процентных активов (берутся концы, на которых есть оба числа)."""
    qs = mix.run.ctx.timeline.quarters_of_year(year)
    pairs = [(mix.quarter_end("loans", q), mix.quarter_end("iea", q)) for q in [qs[0] - 1] + qs]
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    total = sum(b for _, b in pairs)
    return sum(a for a, _ in pairs) / total if pairs and total else None


def mix_dps(run: GridRun, prob: Mapping, year: int) -> float | None:
    """DPS года смеси — ожидание DPS клеток (год прибыли); нет решения хотя бы у одной клетки — None."""
    vals = [(prob[c.key], c.dps.get(year)) for c in run.cells]
    if any(v is None for _, v in vals):
        return None
    return sum(w * v for w, v in vals)


# ------------------------------------------------------------------ уровни после фазы роста


def _years(run: GridRun, from_year: int) -> list[int]:
    """Полные годы сетки от `from_year` до последнего года сетки."""
    tl = run.ctx.timeline
    return [y for y in range(max(int(from_year), tl.anchor_year), tl.last_year + 1)
            if all(1 <= q <= tl.Q for q in tl.quarters_of_year(y))]


def _row_probabilities(run: GridRun) -> dict[str, tuple[str, dict]]:
    """Строка узла уровней → (подпись, вероятности клеток): модальная клетка — вероятность 1 у одной клетки."""
    modal = modal_cell(run.ctx.book, run.ctx.posterior)
    one = {c.key: (1.0 if c.key == modal else 0.0) for c in run.cells}
    return {MODAL_CELL: (LEVEL_TITLES[MODAL_CELL], one),
            "analytical": (LAYER_TITLES["analytical"], dict(run.layers["analytical"].prob)),
            POINT: (LEVEL_TITLES[POINT], point_probabilities(run)),
            "macro_neutral": (LAYER_TITLES["macro_neutral"], dict(run.layers["macro_neutral"].prob))}


def level_rows(run: GridRun, prob: Mapping, years: list[int]) -> dict[str, Any]:
    """Уровни смеси клеток за годы `years`: по годам — упр. ЧПМ, CoR и C/I года смеси и доля кредитов в
    процентных активах; уровень — простое среднее лет (как у гейтов долгосрочного участка)."""
    rows = [mix_year(run, prob, y) for y in years]
    by_year = {"nim": [r["mgmt"]["nim"] for r in rows], "cor": [r["mgmt"]["cor"] for r in rows],
               "cir": [r["mgmt"]["cir"] for r in rows], "loans_share": [r["loans_share"] for r in rows]}

    def mean(values: list) -> float | None:
        return None if not values or any(v is None for v in values) else sum(values) / len(values)

    return {**{k: mean(by_year[k]) for k in LEVEL_METRICS}, "by_year": by_year}


def levels(run: GridRun, from_year: int | None = None) -> dict[str, Any] | None:
    """Узел уровней после фазы роста (М§14.5): средние за годы `from_year` … последний год сетки в упр. базисе —
    ЧПМ, CoR, C/I — и доля кредитов в процентных активах для модальной клетки, слоя «свой взгляд», смеси точки
    и слоя «рыночные ставки как есть». `from_year` — ключ книги `checks.window_backtest.from_year`; нет ни
    ключа, ни аргумента — None. → {`from_year`, `to_year`, `years`, `order`, `cell`, `rows`: {строка: {`title`,
    `nim`, `cor`, `cir`, `loans_share`, `by_year`}}} и, при полях окна фактов в ключе книги, `window`
    (`window_facts`)."""
    if from_year is None:
        cfg = run.ctx.book.opt(WINDOW_BACKTEST)
        if cfg is None:
            return None
        from_year = int(cfg["from_year"])
    years = _years(run, from_year)
    if not years:
        raise BookError(f"{WINDOW_BACKTEST}.from_year = {from_year}: на сетке нет полного года не раньше него")
    rows = {key: {"title": title, **level_rows(run, prob, years)} for key, (title, prob) in
            _row_probabilities(run).items()}
    out = {"from_year": int(from_year), "to_year": years[-1], "years": years, "order": list(LEVEL_ROWS),
           "cell": "/".join(modal_cell(run.ctx.book, run.ctx.posterior)), "rows": rows}
    window = window_facts(run)
    if window is not None:                      # окно фактов — рядом со строками, не строкой `rows`
        out["window"] = window
    return out


def window_facts(run: GridRun) -> dict[str, Any] | None:
    """Подузел `window` узла уровней (М§14.5): окно фактов, из которого взяты уровни, — мерка для печатаемых
    уровней клеток и слоёв. По марже, стоимости риска и расходам к доходам (упр. базис) — наименьший и
    наибольший квартал окна и среднее окна; доля кредитов в процентных активах — окна и якоря, в определении
    движка. Числа окна — поля книги `checks.window_backtest`: `nim` [мин, макс], коридоры гейта `cor` и `cir`,
    `means` {`nim`, `cor`, `cir`}, `loans_share`; доля якоря — состояние якоря сетки (кредитные книги к
    процентным активам на дату якоря). Поля книги нет — на его месте None; нет ни одного из полей
    `WINDOW_FIELDS` — None: узла нет."""
    cfg = run.ctx.book.opt(WINDOW_BACKTEST)
    if cfg is None or not any(k in cfg for k in WINDOW_FIELDS):
        return None
    means = cfg.get("means") or {}

    def metric(name: str) -> dict[str, float | None]:
        span = cfg.get(name)
        return {"min": None if span is None else float(span[0]), "max": None if span is None else float(span[1]),
                "mean": None if means.get(name) is None else float(means[name])}

    anchor = run.cells[0].quarters                # состояние якоря у всех клеток одно
    share = cfg.get("loans_share")
    return {**{name: metric(name) for name in MGMT},
            "loans_share": {"window": None if share is None else float(share),
                            "anchor": float(anchor["loans"][0]) / float(anchor["iea"][0])}}


def cir_lt_value(run: GridRun) -> dict[str, Any] | None:
    """Число гейта долгосрочного C/I (М§14.2) — одно у гейта и у листа книги, который выводит под цель корни
    расходов: среднее упр. C/I лет `from_year` … последний год сетки. Область — ключ книги
    `checks.cir_lt.scope`: `market_layer` — слой «рыночные ставки как есть» (отношение ожидаемых агрегатов);
    без ключа и при `modal_cell` — модальная клетка (годовые ряды клетки). → {`scope`, `subject`, `from_year`,
    `to_year`, `years`, `values`, `value`, `target`, `tolerance`}; нет ключа гейта — None."""
    ctx = run.ctx
    cfg = ctx.book.opt(CIR_LT)
    if cfg is None:
        return None
    first = int(cfg["from_year"])
    scope = str(cfg.get("scope", MODAL_CELL))
    if scope not in (MODAL_CELL, MARKET_LAYER):
        raise BookError(f"{CIR_LT}.scope = {scope!r}: известны {MODAL_CELL}, {MARKET_LAYER}")
    key = modal_cell(ctx.book, ctx.posterior)
    c = run.cell(*key)
    row = lambda name, q: c.quarters[name][q]  # noqa: E731
    years = [y for y in c.years if y >= first]
    of_cell = [year_mgmt(ctx, "cir", y, c.annual["cir"][i], row) for i, y in enumerate(c.years) if y >= first]
    modal = [v for v in of_cell if v is not None]
    values, subject = of_cell, c.label
    if scope == MARKET_LAYER:
        prob = run.layers["macro_neutral"].prob
        values = [mix_year(run, prob, y)["mgmt"]["cir"] for y in years]
        subject = LAYER_TITLES["macro_neutral"]
    pairs = [(y, v) for y, v in zip(years, values) if v is not None]
    values = [v for _, v in pairs]
    return {"scope": scope, "subject": subject, "cell": c.label, "from_year": first, "to_year": int(c.years[-1]),
            "years": [y for y, _ in pairs], "values": values,
            "value": sum(values) / len(values) if values else None,
            "modal": sum(modal) / len(modal) if modal else None,
            "target": float(cfg["target"]), "tolerance": float(cfg["tolerance"])}


# ------------------------------------------------------------------ путь смеси точки


def point_path(run: GridRun) -> dict[str, Any] | None:
    """Узел таблиц книги «годовой путь смеси точки» (М§14.5; ключ `checks.point_path: true`): по годам сетки —
    прибыль акционеров, ЧПМ, CoR и C/I в упр. базисе, ROE и DPS смеси точки (та же функция, что у `paths.annual`
    выпуска) — и рядом: модальная клетка, её вес в слое «свой взгляд» и в смеси точки, её цена на акцию и её
    прибыль акционеров по тем же годам. Нет ключа — None."""
    ctx = run.ctx
    if ctx.book.opt(POINT_PATH) is not True:
        return None
    prob = point_probabilities(run)
    tl = ctx.timeline
    years = list(range(tl.anchor_year, tl.last_year + 1))
    rows = [mix_year(run, prob, y) for y in years]
    key = modal_cell(ctx.book, ctx.posterior)
    c = run.cell(*key)
    return {"years": years, "ni_sh": [r["flows"]["ni_sh"] for r in rows], "nim_mgmt": [r["mgmt"]["nim"] for r in rows],
            "cor_mgmt": [r["mgmt"]["cor"] for r in rows], "cir_mgmt": [r["mgmt"]["cir"] for r in rows],
            "roe": [r["roe"] for r in rows], "dps": [mix_dps(run, prob, y) for y in years],
            "modal_cell": {"cell": c.label, "p_analytical": run.layers["analytical"].prob[key], "p_point": prob[key],
                           "price": run.cell_price(c), "v": c.v_ri,
                           "ni_sh": [c.annual["ni_sh"][c.years.index(y)] if y in c.years else None for y in years]}}


# ------------------------------------------------------------------ путь фондирования


def _funding(loans: float | None, funds: float | None, wholesale: float | None) -> dict[str, float | None]:
    """Два отношения конца периода: кредиты к средствам клиентов и доля оптового фондирования в сумме средств
    клиентов и оптового фондирования — то же определение, что у гейта `wholesale_share` (М§14.2)."""
    ok = None not in (loans, funds, wholesale)
    return {"loans_to_funds": loans / funds if ok and funds else None,
            "wholesale_share": wholesale / (funds + wholesale) if ok and funds + wholesale else None}


def funding_path(run: GridRun) -> dict[str, Any] | None:
    """Путь фондирования (М§14.5; ключ `checks.wholesale_share` — коридор гейта доли оптового фондирования): на
    дату якоря и на конец каждого года сетки — кредиты к средствам клиентов и доля оптового фондирования у смеси
    точки (отношение ожидаемых остатков клеток, а не ожидание отношений) и у модальной клетки. На этом стоит
    суждение о премии роста средств клиентов (М§4.3): разрыв между кредитами и средствами клиентов клетка
    закрывает оптовым фондированием. Нет ключа — None."""
    ctx = run.ctx
    if ctx.book.opt(WHOLESALE_SHARE) is None:
        return None
    tl = ctx.timeline
    mix = _Mix(run, point_probabilities(run))
    c = run.cell(*modal_cell(ctx.book, ctx.posterior))
    years = list(range(tl.anchor_year, tl.last_year + 1))
    ends = [tl.quarters_of_year(y)[-1] for y in years]
    names = ("loans", "funds", "wholesale")

    def of_mix(q: int) -> dict[str, float | None]:
        return _funding(*(mix.expect(name, q) for name in names))

    def of_cell(q: int) -> dict[str, float | None]:
        return _funding(*(None if c.quarters[name][q] is None else float(c.quarters[name][q]) for name in names))

    def series(at) -> dict[str, list[float | None]]:
        rows = [at(q) if 0 <= q <= tl.Q else dict.fromkeys(FUNDING_METRICS) for q in ends]
        return {k: [r[k] for r in rows] for k in FUNDING_METRICS}

    return {"years": years, "cell": c.label, "anchor": of_cell(0), "mix": series(of_mix),
            "modal_cell": series(of_cell)}


# ------------------------------------------------------------------ стационарная маржа и стоимость средств


def stationary_nim(ctx: Any) -> dict[str, Any] | None:
    """Число гейта `nim_stationary` (М§14.2): стационарная маржа решателя передачи на составе баланса якоря в
    мире `world` ключа книги (`derived.nii.nss`), переведённая мостом в упр. базис. `ctx` — контекст прогона
    (книга, мост, решение передачи). → {`world`, `value`, `target`, `tolerance`, `key`}; нет ключа — None."""
    cfg = ctx.book.opt(NIM_STATIONARY)
    if cfg is None:
        return None
    world = str(cfg["world"])
    if world not in ctx.transmission.nss:
        raise BookError(f"{NIM_STATIONARY}.world = {world!r}: нет среди worlds.ids (М§14.2)")
    return {"world": world, "value": ctx.bridge.to_mgmt_nim(ctx.transmission.nss[world]),
            "target": float(cfg["target"]), "tolerance": float(cfg["tolerance"]),
            "key": float(ctx.book.get("nii.nim_lt_target_mgmt"))}


def level_nim(ctx: Any) -> dict[str, Any] | None:
    """Суждение книги об уровне маржи при ключе `nii.transmission.level_world` (М§4.5): ключ цели ЧПМ — стационарная
    маржа названного мира на составе баланса якоря. → {`world`, `value` — стационарная маржа этого мира при
    решённых σ0 и φ, упр. базис (равна ключу — тождество решателя), `key` — ключ цели, `reference_world`,
    `reference_value` — выведенный решателем уровень мира-опоры, упр. базис}; нет ключа — None."""
    world = level_world(ctx.book)
    if world is None:
        return None
    tr, br = ctx.transmission, ctx.bridge
    return {"world": world, "value": br.to_mgmt_nim(tr.nss[world]), "key": float(ctx.book.get(NIM_KEY)),
            "reference_world": tr.reference_world, "reference_value": br.to_mgmt_nim(tr.reference_level)}


def judged_nim(ctx: Any) -> dict[str, Any] | None:
    """Стационарная маржа мира, о которой говорит суждение книги (упр. базис): мира гейта `nim_stationary`, а без
    его ключа — мира уровня `nii.transmission.level_world`. → {`world`, `value`}; нет ни того, ни другого —
    None. Её печатают строка обратного расчёта по ключу цели ЧПМ и подпись строки чувствительности."""
    node = stationary_nim(ctx) or level_nim(ctx)
    return None if node is None else {"world": node["world"], "value": node["value"]}


def funds_cost_to_key(run: GridRun) -> dict[str, Any] | None:
    """Число гейта `funds_cost_to_key` (М§14.2): в клетке «мир × модальный режим × модальный сценарий» каждого
    мира — средняя стоимость средств клиентов к средней ключевой ставке за кварталы лет `from_year` … последний
    год сетки. Стоимость — проценты по книгам средств клиентов (ставка книги × средний остаток × дни) к их
    средним остаткам × дни, без взносов в фонд страхования вкладов; ключевая — среднее по дням. →
    {`from_year`, `to_year`, `max`, `regime`, `scenario`, `by_world`: {мир: {`cell`, `cost`, `key`, `ratio`}},
    `ok`}; нет ключа — None."""
    ctx = run.ctx
    cfg = ctx.book.opt(FUNDS_COST)
    if cfg is None:
        return None
    tl, funds = ctx.timeline, ctx.prep.roles.funds
    limit, first = float(cfg["max"]), int(cfg["from_year"])
    years = _years(run, first)
    if not years:
        raise BookError(f"{FUNDS_COST}.from_year = {first}: на сетке нет полного года не раньше него")
    qs = [q for y in years for q in tl.quarters_of_year(y)]
    _, regime, scenario = modal_cell(ctx.book, ctx.posterior)
    by_world = {}
    for w in ctx.book.get("worlds.ids"):
        c = run.cell(w, regime, scenario)
        interest = sum(c.books[b]["rate"][q] * c.books[b]["avg"][q] * tl.d(q) for q in qs for b in funds)
        balance = sum(c.books[b]["avg"][q] * tl.d(q) for q in qs for b in funds)
        key = sum(ctx.worlds[w].key[q] * tl.d(q) for q in qs) / sum(tl.d(q) for q in qs)
        cost = interest / balance
        by_world[str(w)] = {"cell": c.label, "cost": cost, "key": key, "ratio": cost / key}
    return {"from_year": first, "to_year": years[-1], "max": limit, "regime": regime, "scenario": scenario,
            "by_world": by_world, "ok": all(row["ratio"] <= limit for row in by_world.values())}
