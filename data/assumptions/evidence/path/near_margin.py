# -*- coding: utf-8 -*-
"""Маржа первого прогнозного квартала по месячным формам банка: два основания ближнего пути маржи (книга, A-C4b).

Лист не пишет ключей книги: он печатает свидетельства, между которыми стоит путь маржи первого прогнозного
квартала (`NEAR_BOOK_PATH` листа `derive_on_engine.py`), и то, насколько каждое из них ошибалось раньше.

Что считается. Чистый процентный доход банка по РСБУ в день (форма 0409102, нарастающий итог по месяцам) за
известные месяцы квартала после якоря против квартала якоря — и два знаменателя его роста:
  * кредитный портфель до резервов по месячным релизам эмитента («индекс к портфелю»);
  * процентные активы банка по форме 0409101 («индекс к процентным активам»).
Оценка управленческой маржи квартала = маржа квартала якоря × рост дохода в день / рост знаменателя. Средние за
период — средние концов соседних месяцев, взвешенные днями. Тем же счётом — кварталы истории, у которых есть и формы,
и раскрытая эмитентом маржа: ошибка каждого индекса (оценка минус факт) по полным кварталам и по первым месяцам
квартала (столько же месяцев, сколько известно сейчас), её среднее и размах; оценка квартала после якоря с поправкой
на размах ошибки истории.

Входы — только файлы репозитория: посевы `data/indicators/seed/` (формы 0409101 и 0409102, месячные релизы,
управленческая маржа кварталов, как её раскрывает эмитент, — одним знаком после запятой) и ряд эмитента фактов
`data/facts/mgmt_quarterly.json` (маржа квартала якоря с двумя знаками — от неё считается оценка). Базис — РСБУ
банка против управленческой маржи группы: это индексы направления, а не мост; поправка на прошлую ошибку —
единственная связь между базисами.

Запуск из корня репозитория:
  python -B data/assumptions/evidence/path/near_margin.py            # печать и out/near_margin_out.{json,txt}
  python -B data/assumptions/evidence/path/near_margin.py --no-write
Код выхода: 0 — посчитано; 1 — нет входов или месяцев.
"""
from __future__ import annotations

import argparse
import calendar
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NIM_DIGITS = 4              # маржа квартала якоря — как её печатает книга: сотые доли процентного пункта
HISTORY_QUARTERS = 4        # кварталов истории, на которых меряется ошибка индексов


def repo_root() -> Path:
    root = HERE
    while not (root / "model" / "book.py").exists():
        if root.parent == root:
            raise FileNotFoundError("не найден корень репозитория")
        root = root.parent
    return root


def pc(x: float, n: int = 2) -> str:
    return f"{100 * x:.{n}f}".replace(".", ",") + " %"


def pp(x: float, n: int = 2) -> str:
    return f"{100 * x:+.{n}f}".replace(".", ",").replace("-", "−") + " п.п."


def month_code(year: int, month: int) -> str:
    return f"{year}M{month:02d}"


def before(year: int, month: int) -> tuple[int, int]:
    return (year, month - 1) if month > 1 else (year - 1, 12)


def quarter_months(year: int, quarter: int) -> list[tuple[int, int]]:
    return [(year, 3 * quarter - 2), (year, 3 * quarter - 1), (year, 3 * quarter)]


def previous_quarter(year: int, quarter: int) -> tuple[int, int]:
    return (year, quarter - 1) if quarter > 1 else (year - 1, 4)


def next_quarter(year: int, quarter: int) -> tuple[int, int]:
    return (year, quarter + 1) if quarter < 4 else (year + 1, 1)


class Series:
    """Месячные ряды посевов: доход нарастающим итогом, концы месяцев процентных активов и портфеля."""

    def __init__(self, seed: Path):
        read = lambda name: json.loads((seed / name).read_text(encoding="utf-8"))["months"]  # noqa: E731
        self.nii = {k: float(v["nii_ytd"]) for k, v in read("form102.json").items() if v.get("nii_ytd") is not None}
        self.iea = {k: float(v["iea"]) for k, v in read("form101.json").items() if v.get("iea") is not None}
        self.loans = {k: float(v["values"]["loans_gross"]["v"]) for k, v in read("monthly_release.json").items()
                      if (v.get("values") or {}).get("loans_gross")}

    def has(self, year: int, month: int) -> bool:
        k, p = month_code(year, month), month_code(*before(year, month))
        return (k in self.nii and (month == 1 or p in self.nii)
                and all(k in s and p in s for s in (self.iea, self.loans)))

    def span(self, months: list[tuple[int, int]]) -> dict[str, float]:
        """Доход в день и средние знаменатели за месяцы: средние концов соседних месяцев, взвешенные днями."""
        days = income = assets = loans = 0.0
        for year, month in months:
            k, p = month_code(year, month), month_code(*before(year, month))
            d = calendar.monthrange(year, month)[1]
            income += self.nii[k] if month == 1 else self.nii[k] - self.nii[p]
            assets += d * (self.iea[k] + self.iea[p]) / 2
            loans += d * (self.loans[k] + self.loans[p]) / 2
            days += d
        return {"income_per_day": income / days, "assets": assets / days, "loans": loans / days}


def growth(now: dict[str, float], base: dict[str, float]) -> dict[str, float]:
    g = {k: now[k] / base[k] for k in now}
    return {"income_per_day": g["income_per_day"] - 1, "assets": g["assets"] - 1, "loans": g["loans"] - 1,
            "index_to_assets": g["income_per_day"] / g["assets"], "index_to_loans": g["income_per_day"] / g["loans"]}


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="маржа первого прогнозного квартала по месячным формам: два основания")
    ap.add_argument("--no-write", action="store_true", help="не писать out/near_margin_out.json и .txt")
    ap.add_argument("--out", type=Path, default=None, help="куда писать JSON (по умолчанию — out/near_margin_out.json листа)")
    a = ap.parse_args(argv)
    lines: list[str] = []

    def say(text: str = "") -> None:
        lines.append(text)
        print(text)

    try:
        root = repo_root()
        s = Series(root / "data" / "indicators" / "seed")
        facts = json.loads((root / "data" / "facts" / "mgmt_quarterly.json").read_text(encoding="utf-8"))["quarters"]
        exact = {k: float(v["nim_exact"]["v"]) for k, v in facts.items() if (v.get("nim_exact") or {}).get("v") is not None}
        seed = json.loads((root / "data" / "indicators" / "seed" / "mgmt_quarters.json").read_text(encoding="utf-8"))
        nim = {k: float(v["nim"]["v"]) for k, v in seed["quarters"].items() if (v.get("nim") or {}).get("v") is not None}
        anchor = max(exact)
        ay, aq = int(anchor[:4]), int(anchor[-1])
        ny, nq = next_quarter(ay, aq)
        known = [ym for ym in quarter_months(ny, nq) if s.has(*ym)]
        if not known:
            raise ValueError(f"нет месяцев квартала {ny}Q{nq} в посевах форм и релизов")
        if not all(s.has(*ym) for ym in quarter_months(ay, aq)):
            raise ValueError(f"нет месяцев квартала якоря {anchor} в посевах")
        base_nim = round(exact[anchor], NIM_DIGITS)
        q0 = s.span(quarter_months(ay, aq))
        g = growth(s.span(known), q0)
        rsbu = lambda x: x["income_per_day"] / x["assets"] * 365  # noqa: E731
        raw = {"to_loans": base_nim * g["index_to_loans"], "to_assets": base_nim * g["index_to_assets"]}

        # история: тот же счёт на кварталах с раскрытой маржой — полный квартал и первые месяцы квартала
        history, errors = [], {"full": {"to_loans": [], "to_assets": []}, "first_months": {"to_loans": [], "to_assets": []}}
        y, q = ay, aq
        for _ in range(HISTORY_QUARTERS):
            py, pq = previous_quarter(y, q)
            months = quarter_months(y, q)
            if not {f"{py}Q{pq}", f"{y}Q{q}"} <= set(nim) or not all(s.has(*ym) for ym in months + quarter_months(py, pq)):
                break
            prev, fact = s.span(quarter_months(py, pq)), nim[f"{y}Q{q}"]
            row = {"quarter": f"{y}Q{q}", "nim_previous": nim[f"{py}Q{pq}"], "nim": fact}
            for name, part in (("full", months), ("first_months", months[:len(known)])):
                gi = growth(s.span(part), prev)
                est = {"to_loans": nim[f"{py}Q{pq}"] * gi["index_to_loans"], "to_assets": nim[f"{py}Q{pq}"] * gi["index_to_assets"]}
                row[name] = {"growth": {k: round(v, 6) for k, v in gi.items()},
                             "estimate": {k: round(v, 6) for k, v in est.items()},
                             "error": {k: round(v - fact, 6) for k, v in est.items()}}
                for k in est:
                    errors[name][k].append(est[k] - fact)
            history.insert(0, row)
            y, q = py, pq
        if not history:
            raise ValueError("нет кварталов истории с формами и раскрытой маржой")
        stats = {name: {k: {"mean": round(statistics.mean(v), 6), "min": round(min(v), 6), "max": round(max(v), 6)}
                        for k, v in part.items()} for name, part in errors.items()}
        corrected = {name: {k: {"low": round(raw[k] - stats[name][k]["max"], 6), "high": round(raw[k] - stats[name][k]["min"], 6),
                                "mean": round(raw[k] - stats[name][k]["mean"], 6)} for k in raw} for name in stats}
        out = {"anchor": anchor, "quarter": f"{ny}Q{nq}", "months_known": [month_code(*ym) for ym in known],
               "anchor_nim": base_nim, "growth": {k: round(v, 6) for k, v in g.items()},
               "ras_margin_on_assets": {"anchor": round(rsbu(q0), 6), "known_months": round(rsbu(s.span(known)), 6)},
               "estimate": {k: round(v, 6) for k, v in raw.items()}, "history": history, "errors": stats,
               "estimate_corrected": corrected}

        say(f"Квартал после якоря {out['quarter']}: известны месяцы {', '.join(out['months_known'])}; якорь {anchor}, упр. маржа якоря {pc(base_nim)}")
        say(f"  ЧПД банка по РСБУ в день: {pp(g['income_per_day']).replace(' п.п.', ' %')} к кварталу якоря")
        say(f"  кредитный портфель до резервов (месячные релизы), средний: {pp(g['loans']).replace(' п.п.', ' %')}; "
            f"процентные активы банка (форма 0409101), средние: {pp(g['assets']).replace(' п.п.', ' %')}")
        say(f"  маржа РСБУ на процентных активах: {pc(out['ras_margin_on_assets']['anchor'])} → {pc(out['ras_margin_on_assets']['known_months'])}")
        say(f"  оценка упр. маржи квартала: по индексу к портфелю {pc(raw['to_loans'])}; по индексу к процентным активам {pc(raw['to_assets'])}")
        say()
        say("История индексов (оценка минус факт упр. маржи квартала; полный квартал | первые месяцы квартала):")
        for row in history:
            say(f"  {row['quarter']}: факт {pc(row['nim_previous'])} → {pc(row['nim'])}; к портфелю {pp(row['full']['error']['to_loans'])} | "
                f"{pp(row['first_months']['error']['to_loans'])}; к процентным активам {pp(row['full']['error']['to_assets'])} | "
                f"{pp(row['first_months']['error']['to_assets'])}")
        for name, words in (("full", "полный квартал"), ("first_months", "первые месяцы квартала")):
            e, c = stats[name], corrected[name]
            say(f"  {words}: средняя ошибка к портфелю {pp(e['to_loans']['mean'])}, к процентным активам {pp(e['to_assets']['mean'])}; "
                f"оценка с поправкой — к портфелю {pc(c['to_loans']['low'])}…{pc(c['to_loans']['high'])}, "
                f"к процентным активам {pc(c['to_assets']['low'])}…{pc(c['to_assets']['high'])}")
    except (OSError, KeyError, ValueError) as exc:
        print(f"ПРОВАЛ: {exc}")
        return 1
    if not a.no_write:
        target = a.out or HERE / "out" / "near_margin_out.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        target.with_suffix(".txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
