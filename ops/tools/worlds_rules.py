# -*- coding: utf-8 -*-
"""Правила книги Т-Технологий для чисел, зависящих от миров ставок, — шаги `rule` манифеста приёма миров.

Каждая функция `f(ctx) -> [{"file", "values", "decimals", "replace"}]` (`ctx` — RuleContext команды
`ops/tools/adopt_worlds.py`: `ctx.root`, `ctx.record`, `ctx.overlay`, `ctx.yaml(rel)`, `ctx.version`,
`ctx.from_version`) считает числа книги по правилу из записи миров, надстройки, фактов и выходов листов и не пишет
сама: пишет команда, точечно (`values` — адрес → число; адрес — кортеж: элементы списков номером, ключ с точкой — одной
частью), а числа правил в комментариях шаблона — заменой текста (`replace`: [было, стало] или [было, стало, сколько]).
Сторож (`adopt_worlds.py --check`, `tests/test_worlds_rules.py`): на записи книги каждое правило даёт шаблон.

  book_version   номер версии книги: младший разряд + 1, если версия с этим номером уже выпущена на другой записи миров
                 (тег `book-<версия>`); строка 1 и тег версии в тексте книги;
  spreads        ключи спредов книг ЧПД: "2026" — A-N1n (ставка якоря − β × опора мира H 1-го прогнозного квартала);
                 с 2028 года и LT у книг активов — правило листа калибровки этапа 1 (s + (a − 1) × опора мира H, среднее
                 кварталов года; LT — LT-опора); "2027" — середина между "2026" и 2028 (у оптового — LT); LT оптового —
                 LT ликвидности + разность срочных вкладов и ликвидных активов окна (лист evidence/nii); 5 знаков;
  funds_q3       фактический ключ премии средств клиентов 1-го прогнозного квартала (A-G2): остаток последнего месяца
                 года в посеве месячных релизов к остатку якоря, остаток квартала — темпом сектора надстройки; 6 знаков;
  noncore        путь пакета Яндекса (A-O2) — траектория листа pnl (`out/noncore_center.json`, `traj_A`);
  derived        числа, выведенные на ядре (`evidence/path/out/derive_out.json`): ключи, концы осей, коридор доли
                 оптового фондирования, окно фактов, справочные варианты от вывода, числа вывода в комментариях и пометки
                 «ВЫВЕДЕНО НА ЯДРЕ <дата> (книга <версия>)» (дата и версия — `derive_start.json`);
  gate_masses    ожидаемые массы объяснений сработавших гейтов — массы таблиц книги (`results.json`).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

TEMPLATE = "data/assumptions/assumptions_template.yaml"
BOOK_TEXT = "data/assumptions/ASSUMPTIONS-BOOK.md"
EVIDENCE = "data/assumptions/evidence"
GATES = "data/assumptions/gate_explanations.yaml"
RESULTS = "data/assumptions/results.json"
DERIVE_OUT = f"{EVIDENCE}/path/out/derive_out.json"
DERIVE_START = f"{EVIDENCE}/path/out/derive_start.json"
REF_FIELD = {"key": "key_avg", "ofz_1y": "ofz_1y", "ofz_3y": "ofz_3y", "ofz_5y": "ofz_5y", "ofz_10y": "ofz_10y"}
PATH_FIELDS = ["key_avg", "cpi_yoy_avg", "cpi_yoy_eop_half", "nominal_wage_yoy", "ofz_1y", "ofz_3y", "ofz_5y", "ofz_10y"]
CURVE_LT_TABLE = {"N": 9.0, "H": 12.7, "M": 16.7}   # запись без блока curve_lt: таблица LT сборщика 850oa (N, H)
MARK = re.compile(r"ВЫВЕДЕНО НА ЯДРЕ \d\d\.\d\d\.\d{4}(?: \(книга [^)]+\))?")
SPREAD_DECIMALS = 5
FUNDS_DECIMALS = 6


class RuleError(Exception):
    """Шаблон не в том виде, который правило знает (строка комментария переписана руками и т. п.)."""


# ----------------------------------------------------------------------------------------------- общее
def r5(x: float) -> float:
    return round(x + 0.0, SPREAD_DECIMALS)


def ru(x: float, nd: int, *, sign: bool = False) -> str:
    """Число для текста: запятая, минус «−», группы тысяч пробелом."""
    s = f"{abs(x):,.{nd}f}".replace(",", " ").replace(".", ",")
    if round(x, nd) < 0:
        return "−" + s
    return ("+" + s) if sign and round(x, nd) > 0 else s


def ru_date(iso: str) -> str:
    return dt.date.fromisoformat(str(iso)).strftime("%d.%m.%Y")


def template(ctx) -> dict:
    return ctx.yaml(TEMPLATE)


def template_text(ctx) -> str:
    return (Path(ctx.root) / TEMPLATE).read_text(encoding="utf-8")


def json_file(ctx, rel: str) -> Any:
    return json.loads((Path(ctx.root) / rel).read_text(encoding="utf-8"))


def one(text: str, pattern: str, flags: int = 0) -> re.Match:
    ms = list(re.finditer(pattern, text, flags))
    if len(ms) != 1:
        raise RuleError(f"в шаблоне {len(ms)} мест под правило (нужно одно): {pattern[:90]}")
    return ms[0]


def sub_groups(m: re.Match, values: list[str]) -> list[str]:
    """[было, стало]: совпадение `m` с группами, заменёнными на `values`."""
    s, base = m.group(0), m.start(0)
    out, at = [], 0
    for i, v in enumerate(values, 1):
        out.append(s[at:m.start(i) - base])
        out.append(v)
        at = m.end(i) - base
    out.append(s[at:])
    return [s, "".join(out)]


def axis_index(book: dict, pred) -> int:
    axes = book["valuation"]["uncertainty"]["axes"]
    hits = [i for i, a in enumerate(axes) if pred(a)]
    if len(hits) != 1:
        raise RuleError(f"осей под правило {len(hits)}, нужна одна")
    return hits[0]


def variant_index(book: dict, vid: str) -> int:
    hits = [i for i, v in enumerate(book["valuation"]["reference_variants"]) if v["id"] == vid]
    if len(hits) != 1:
        raise RuleError(f"справочный вариант {vid}: {len(hits)}")
    return hits[0]


# ----------------------------------------------------------------------------------------------- пути миров
def world_paths(record: dict) -> list[dict]:
    """Квартальные пути миров N/H/M из записи (лист этапа 1 `world_paths_quarterly.py`, семейный): значение квартала —
    значение его полугодия; строки LT — установившиеся уровни (последнее полугодие записи; ИПЦ — `lt_inflation`; уровень
    кривой в терминале — блок `curve_lt` записи, у записи без блока — таблица LT сборщика и правило мира M)."""
    rows = record["rows"]
    out = []
    for w in ("N", "H", "M"):
        wr = [r for r in rows if r["world"] == w]
        for r in wr:
            y, h = int(r["period"][:4]), int(r["period"][5])
            for q in ((1, 2) if h == 1 else (3, 4)):
                out.append(dict(world=w, period=f"{y}Q{q}", half=r["period"], key_avg=r["key_avg"],
                                cpi_yoy_avg=r["cpi_yoy_avg"], cpi_yoy_eop_half=r["cpi_yoy_eop"],
                                nominal_wage_yoy=r["nominal_wage_yoy"], ofz_1y=r["ofz_1y"], ofz_3y=r["ofz_3y"],
                                ofz_5y=r["ofz_5y"], ofz_10y=r["ofz_10y"], zero_curve_lt=""))
        last = wr[-1]
        curve_lt = CURVE_LT_TABLE[w]
        if record.get("curve_lt") is not None:
            curve_lt = record["curve_lt"][w]
        elif w == "M" and (record.get("m_inflation") or {}).get("source") == "forward_bei":
            curve_lt = round(last["ofz_10y"], 1)
        pi = (record.get("lt_inflation") or {}).get(w)
        out.append(dict(world=w, period="LT", half="LT", key_avg=last["key_avg"], cpi_yoy_avg=pi, cpi_yoy_eop_half=pi,
                        nominal_wage_yoy=last["nominal_wage_yoy"], ofz_1y=last["ofz_1y"], ofz_3y=last["ofz_3y"],
                        ofz_5y=last["ofz_5y"], ofz_10y=last["ofz_10y"], zero_curve_lt=curve_lt))
    return out


def world_paths_csv(record: dict) -> bytes:
    buf = io.StringIO(newline="")
    wtr = csv.DictWriter(buf, fieldnames=["world", "period", "half"] + PATH_FIELDS + ["zero_curve_lt"], lineterminator="\n")
    wtr.writeheader()
    wtr.writerows(world_paths(record))
    return buf.getvalue().encode("utf-8")


def ref_paths(record: dict, world: str) -> dict[str, dict[str, float]]:
    """Квартал → опоры мира (доли), как их читает лист nii из CSV путей."""
    out: dict[str, dict[str, float]] = {}
    for r in csv.DictReader(io.StringIO(world_paths_csv(record).decode("utf-8"))):
        if r["world"] == world:
            out[r["period"]] = {k: float(r[f]) / 100 for k, f in REF_FIELD.items()}
    return out


# ----------------------------------------------------------------------------------------------- версия книги
def released_record(root: Path, version: str) -> str | None:
    """sha256 записи миров книги выпуска `book-<версия>` (тег); тега нет — None."""
    p = subprocess.run(["git", "-C", str(root), "show", f"book-{version}:{TEMPLATE}"], capture_output=True)
    if p.returncode != 0:
        return None
    return str(((yaml.safe_load(p.stdout.decode("utf-8")) or {}).get("worlds") or {}).get("source", {}).get("sha256"))


def book_version(ctx) -> list[dict]:
    """Приём миров — новая версия книги: младший разряд + 1, если версия с номером шаблона уже выпущена на другой записи
    миров (тег `book-<версия>`). Иначе — номер шаблона (приём той же записи, повтор команды, книга до выпуска)."""
    book = template(ctx)
    cur = str(book["meta"]["version"])
    sha = book["worlds"]["source"]["sha256"]
    rel = released_record(Path(ctx.root), cur)
    new = cur
    if rel is not None and rel != sha:
        head, _, minor = cur.rpartition(".")
        new = f"{head}.{int(minor) + 1}"
    out = [{"file": TEMPLATE, "values": {("meta", "version"): new}}]
    text = (Path(ctx.root) / BOOK_TEXT).read_text(encoding="utf-8")
    first = text.splitlines()[0]
    m = re.fullmatch(r"(.*версия )(\S+)", first)
    if not m:
        raise RuleError("строка 1 текста книги не кончается «версия <номер>»")
    pairs = [[first + "\n", f"{m.group(1)}{new}\n"]]
    tag = one(text, r"\*\*тег версии:\*\* `book-([\d.]+)`")
    pairs.append(sub_groups(tag, [new]))
    out.append({"file": BOOK_TEXT, "replace": pairs})
    return out


# ----------------------------------------------------------------------------------------------- спреды ЧПД
def spreads(ctx) -> list[dict]:
    book = template(ctx)
    nii = book["nii"]
    first = str(book["meta"]["first_period"])
    y0 = int(first[:4])
    half = f"{y0}H{1 if int(first[5]) <= 2 else 2}"
    ref_world = str(nii["transmission"]["reference_world"])
    row = next(r for r in ctx.record["rows"] if r["world"] == ref_world and r["period"] == half)
    rates = {b: float(v["rate_anchor"]["v"]) for b, v in
             json_file(ctx, "data/facts/nii_books.json")["books"].items() if "rate_anchor" in v}
    calib = json_file(ctx, f"{EVIDENCE}/nii/inputs/stage1/calib/nii/out/results.json")["books"]
    wp = ref_paths(ctx.record, ref_world)
    values: dict[tuple, float] = {}
    near: dict[str, float] = {}
    later: dict[str, float] = {}                 # значение года y0 + 2 без округления (для середины "2027")
    for b, spec in nii["books"].items():         # 1) "2026" — A-N1n
        sp = spec["spread"]
        if not isinstance(sp, dict) or str(y0) not in sp:
            continue
        beta = float(spec.get("beta", 1.0)) if spec["side"] == "liability" else 1.0
        near[b] = r5(rates[b] - beta * round(float(row[REF_FIELD[spec["ref"]]]) / 100, 6))
        values[("nii", "books", b, "spread", str(y0))] = near[b]
    for b in near:                               # 2) с 2028 года и LT — правило листа калибровки (книги активов)
        spec, sp = nii["books"][b], nii["books"][b]["spread"]
        if spec["side"] != "asset" or b not in calib:
            continue
        a, s, ref = calib[b]["slope"], calib[b]["s_level"], spec["ref"]
        for y in range(y0 + 2, int(sp["LT_from"])):
            qs = [q for q in wp if q != "LT" and q.startswith(str(y))]
            cal = s + (a - 1) * (sum(wp[q][ref] for q in qs) / len(qs))
            if y == y0 + 2:
                later[b] = cal
            values[("nii", "books", b, "spread", str(y))] = r5(cal)
        values[("nii", "books", b, "spread", "LT")] = r5(s + (a - 1) * wp["LT"][ref])
    nb = ctx.module(f"{EVIDENCE}/nii/nii_book.py", "worlds_rules_nii_book")
    replace = []
    whs_book, liq_book = nb.WHOLESALE_BOOK, nb.LIQUIDITY_BOOK
    if whs_book in near:                         # 3) LT оптового — от LT ликвидности (после дальних ключей)
        liq_lt = values[("nii", "books", liq_book, "spread", "LT")]
        rule = nb.wholesale_rule(liq_lt)
        values[("nii", "books", whs_book, "spread", "LT")] = rule["rule"]
        text = template_text(ctx)
        m = one(text, r"LT-спред книги ликвидности \(([−-]?\d+,\d+) п\.п\. к ключевой\) плюс (\d+,\d+) п\.п\.")
        replace.append(sub_groups(m, [ru(liq_lt * 100, 3), ru(rule["premium"] * 100, 2)]))
        m = one(text, r"#   ([−-]?\d+,\d+) п\.п\. к ключевой; занять на рынке")
        replace.append(sub_groups(m, [ru(rule["rule"] * 100, 3)]))
    for b, k26 in near.items():                  # 4) "2027" — середина до значения 2028 года (у оптового — LT)
        sp = nii["books"][b]["spread"]
        if str(y0 + 1) not in sp:
            continue
        if b in later:
            nxt = later[b]
        elif str(y0 + 2) in sp:
            nxt = values.get(("nii", "books", b, "spread", str(y0 + 2)), float(sp[str(y0 + 2)]))
        else:                                    # LT_from ≤ y0 + 2
            nxt = values.get(("nii", "books", b, "spread", "LT"), float(sp["LT"]))
        values[("nii", "books", b, "spread", str(y0 + 1))] = r5((k26 + nxt) / 2)
    return [{"file": TEMPLATE, "values": values, "decimals": {k: SPREAD_DECIMALS for k in values}, "replace": replace}]


# ----------------------------------------------------------------------------------------------- отток средств 3К
def funds_q3(ctx) -> list[dict]:
    book = template(ctx)
    seed = json_file(ctx, "data/indicators/seed/monthly_release.json")["months"]
    first = str(book["meta"]["first_period"])
    year = int(first[:4])
    last = max(m for m in seed if m.startswith(str(year)))
    anchor_month, last_month = int(str(book["meta"]["facts_date"])[5:7]), int(last[5:7])
    quarter_end = 3 * int(first[5])
    values, ru_vals, growth = {}, {}, None
    for seg, node in (("retail", "funds_retail"), ("corporate", "funds_business")):
        g = {ctx.overlay["worlds"][w]["funds_growth"][seg][str(year)] for w in ctx.overlay["worlds"]}
        if len(g) != 1:
            raise RuleError(f"рост средств сектора {year} ({seg}) не один во всех мирах надстройки")
        growth = g.pop()
        r = seed[last]["values"][node]["v"] / seed[f"{year}M{anchor_month:02d}"]["values"][node]["v"]
        v = round(r ** 4 * (1 + growth) ** (4 * (quarter_end - last_month) / 12 - 1) - 1, FUNDS_DECIMALS)
        values[("volumes", "funds_share_drift", seg, first)] = v
        ru_vals[seg] = ru(v * 100, 1)
    text = template_text(ctx)
    m = one(text, r"ключ квартала ([−-]?\d+,\d) п\.п\. в годовом выражении у физлиц и ([−-]?\d+,\d) п\.п\. у")
    replace = [sub_groups(m, [ru_vals["retail"], ru_vals["corporate"]])]
    m = one(text, r"рост сектора \d{4} года — надстройка миров книги, (\d+,\d) %")
    replace.append(sub_groups(m, [ru(growth * 100, 1)]))
    return [{"file": TEMPLATE, "values": values, "decimals": {k: FUNDS_DECIMALS for k in values}, "replace": replace}]


# ----------------------------------------------------------------------------------------------- пакет Яндекса
def noncore(ctx) -> list[dict]:
    traj = json_file(ctx, f"{EVIDENCE}/pnl/out/noncore_center.json")["traj_A"]
    book = template(ctx)
    if set(traj) != set(book["noncore"]["result_real"]):
        raise RuleError("ключи пути пакета листа pnl ≠ ключи шаблона")
    values = {("noncore", "result_real", k): float(v) for k, v in traj.items()}
    m = one(template_text(ctx), r"сходит с (\d+,\d) до (\d+,\d) \(ключевая и ИПЦ мира H записи\)")
    second = str(int(str(book["meta"]["first_period"])[:4]) + 1)
    return [{"file": TEMPLATE, "values": values, "replace": [sub_groups(m, [ru(traj[second], 1), ru(traj["LT"], 1)])]}]


# ----------------------------------------------------------------------------------------------- вывод на ядре
def _flat_key(dotted: str, value: Any) -> dict[tuple, Any]:
    base = tuple(dotted.split("."))
    if isinstance(value, dict):
        return {base + (k,): v for k, v in value.items()}
    return {base: value}


def derived(ctx) -> list[dict]:
    rec = json_file(ctx, DERIVE_OUT)
    start = json_file(ctx, DERIVE_START)
    book = template(ctx)
    text = template_text(ctx)
    values: dict[tuple, Any] = {}
    for dotted, v in rec["keys"].items():                    # ключи вывода
        values.update(_flat_key(dotted, v))
    ends = rec["ends"]
    axes = book["valuation"]["uncertainty"]["axes"]
    i = axis_index(book, lambda a: a["paths"][0] == "opex.volume_link" and a["kind"] == "bundle")
    for end in ("low", "high"):                              # концы оси-связки гибкости
        if set(axes[i][end]) != set(ends["bundle"][end]):
            raise RuleError("пути концов оси-связки ≠ записи вывода")
        values.update({("valuation", "uncertainty", "axes", i, end, k): v for k, v in ends["bundle"][end].items()})
    i = axis_index(book, lambda a: a["paths"] == ["nii.phi_split"])
    values.update({("valuation", "uncertainty", "axes", i, e): v for e, v in zip(("low", "high"), rec["splits"]["axis_phi"])})
    i = axis_index(book, lambda a: a["paths"][0] == "opex.real_growth.2027")
    values.update({("valuation", "uncertainty", "axes", i, e): ends["opex_axis"][e] for e in ("low", "high")})
    values.update({("checks", "wholesale_share", j): v for j, v in enumerate(ends["wholesale_share"]["corridor"])})
    win = ends["window"]                                     # окно фактов
    for k in ("nim", "cor", "cir"):
        values[("checks", "window_backtest", k, 0)] = win[k]["min"]
        values[("checks", "window_backtest", k, 1)] = win[k]["max"]
        values[("checks", "window_backtest", "means", k)] = win[k]["mean"]
    values[("checks", "window_backtest", "loans_share")] = win["loans_share"]["window"]
    need = rec["need"]                                       # вариант «премия на уровне нужды баланса»
    j = variant_index(book, "funds_premium_need")
    old_title = book["valuation"]["reference_variants"][j]["title"]
    tm = re.fullmatch(r"(.*: )([+−-]?\d+,\d)( п\.п\. .*)", old_title)
    if not tm:
        raise RuleError("подпись варианта funds_premium_need не в известном виде")
    values[("valuation", "reference_variants", j, "title")] = tm.group(1) + ru(need["level"] * 100, 1, sign=True) + tm.group(3)
    ov = book["valuation"]["reference_variants"][j]["overrides"]
    for seg in ("retail", "corporate"):
        for y, k in need["shape"].items():
            key = f"volumes.funds_share_drift.{seg}.{y}"
            if key not in ov:
                raise RuleError(f"у варианта funds_premium_need нет подмены {key}")
            values[("valuation", "reference_variants", j, "overrides", key)] = round(need["level"] * k, 6)
    near = rec["keys"]["regimes.near_nim_shift"]             # вариант «расхождение не сходит»
    first = str(book["meta"]["first_period"])
    j = variant_index(book, "near_shift_stays")
    for k in book["valuation"]["reference_variants"][j]["overrides"]["regimes.near_nim_shift"]:
        if k != "LT_from":
            v = near[k] if str(k).startswith(first[:4]) else near[first]
            values[("valuation", "reference_variants", j, "overrides", "regimes.near_nim_shift", k)] = v
    # числа вывода в комментариях шаблона
    replace = []
    marks = set(MARK.findall(text))
    if len(marks) != 1:
        raise RuleError(f"пометки вывода на ядре разные: {sorted(marks)}")
    mark = f"ВЫВЕДЕНО НА ЯДРЕ {ru_date(start['date'])} (книга {start['book_version']})"
    replace.append([marks.pop(), mark, len(MARK.findall(text))])
    sp = rec["splits"]
    m = one(text, r"сжатие истории (\d,\d+) к полному сжатию φ (\d,\d+) — (\d,\d+)\)")
    replace.append(sub_groups(m, [ru(sp["history_compression"], 3), ru(sp["phi"], 3), ru(sp["phi_by_history"], 3)]))
    m = one(text, r"гейт стоимости средств клиентов ещё проходит \((\d,\d+) при пороге")
    replace.append(sub_groups(m, [ru(ends["phi_axis"]["funds_cost_to_key_at_low"], 4)]))
    m = one(text, r"равны сдвигу \d-го квартала \d{4} года \(([−-]?\d+,\d+) п\.п\.\)")
    replace.append(sub_groups(m, [ru(near[first] * 100, 2)]))
    fy = rec["modal_cell"]["funds_anchor_year"]              # остатки средств клиентов модальной клетки в году якоря
    q2, q3, q4 = (f"{first[:4]}Q{q}" for q in (2, 3, 4))
    g = ctx.overlay["worlds"]["N"]["funds_growth"]
    m = one(text, r"на конец \d-го квартала — физлица ([\d ]+,\d), бизнес ([\d ]+,\d) млрд ₽; на конец года — ([\d ]+,\d) и "
                  r"([\d ]+,\d) млрд ₽")
    replace.append(sub_groups(m, [ru(fy[q3]["retail"], 1), ru(fy[q3]["corporate"], 1), ru(fy[q4]["retail"], 1),
                                  ru(fy[q4]["corporate"], 1)]))
    half = {seg: ((fy[q4][seg] / fy[q2][seg]) ** 2 / (1 + g[seg][first[:4]]) - 1) * 100 for seg in ("retail", "corporate")}
    m = one(text, r"\(за полугодие это ([−-]?\d+,\d) и ([−-]?\d+,\d) п\.п\. к сектору")
    replace.append(sub_groups(m, [ru(half["retail"], 1), ru(half["corporate"], 1)]))
    return [{"file": TEMPLATE, "values": values, "replace": replace}]


# ----------------------------------------------------------------------------------------------- гейты
def gate_masses(ctx) -> list[dict]:
    """Ожидаемая масса объяснения гейта = масса сработавшего гейта в таблицах книги (запись с коридором массы —
    суждение о дрейфе, её правило не трогает). Тексты объяснений — суждение (числа сетки печатает лист гейтов)."""
    res = json_file(ctx, RESULTS)
    fired = {c["name"]: c["mass"] for c in res["checks"] if c.get("fired") and c.get("kind") == "gate"}
    notes = ctx.yaml(GATES) or {}
    values = {(name, "expected_mass"): float(fired[name]) for name, e in notes.items()
              if "expected_mass" in e and name in fired}
    return [{"file": GATES, "values": values}]
