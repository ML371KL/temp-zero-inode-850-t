# -*- coding: utf-8 -*-
"""Предельная доходность кредита на капитал в арифметике книги против сегмента отчётности эмитента (MODEL §14.2, гейт
знака объёмных эффектов). Проверка, а не правило: ключей книги лист не пишет.

Что считается. Рубль прироста валовых кредитов (пропорционально составу книг на конец года) в клетках «режим с
наибольшей вероятностью × его модальный сценарий капитала» каждого мира:
  * процентный доход — по ставкам книг клетки; чем фондируется рубль, решает состояние клетки: пока ликвидные активы
    выше минимума, кредит замещает их (теряется их доходность); на минимуме — фондируется оптовым фондированием по
    рыночной ставке, а ликвидные активы растут вместе с активами;
  * резервы — по стоимости риска года клетки; расходы и услуги — по связям книги с портфелем;
  * капитал — под требование норматива достаточности с глиссадой за вычетом доли инструментов капитала, активы под
    риском — по плотностям книги, приведённым к активам под риском клетки.
Два базиса доходности после налога и доли неконтролирующих акционеров:
  * «без кредита за капитал» — весь рубль кредита оплачен по цене фондирования;
  * «базис сегмента» — капитал сам фондирует часть кредита, остальное оплачено по цене фондирования: так считает
    свои сегменты эмитент (потребляемый капитал сегмента, трансфертные цены).
Рядом — факт сегмента «Розничное финансирование» из примечания о сегментах отчётности МСФО (входы листа: строки с
документом, страницей и sha256) и опыт на ядре: книга против замыкания без ограничения роста капиталом — прирост
прибыли акционеров к приросту капитала.

Запуск из корня репозитория (книга и факты — те, что читает ядро):
  python -B data/assumptions/evidence/path/marginal_loan.py            # печать и out/marginal_loan_out.{json,txt}
  python -B data/assumptions/evidence/path/marginal_loan.py --no-write
Код выхода: 0 — посчитано; 2 — ядро ещё не исполняет ветви книги; 1 — отказ книги, фактов или входов.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEGMENT_FILE = HERE / "inputs" / "segment_note6.csv"
YEARS = (2026, 2027, 2030, 2036)         # год якоря, первый год после него, конец фазы роста, последний год сетки
PAIR_YEARS = (2028, 2030, 2033, 2036)    # годы опыта «книга против замыкания без ограничения роста»
RETAIL = ("cards", "cash_loans", "auto", "mortgage")   # книги сегмента розничного кредитования
SEGMENT = "retail_financing"
HALF, PRIOR_HALF = "6M2026", "6M2025"
CAPITAL_END, CAPITAL_START = "2026-06-30", "2025-12-31"


class NeedCore(RuntimeError):
    """Ядро не готово: нет ветви, ряда клетки или функции."""


def repo_root() -> Path:
    root = HERE
    while not (root / "model" / "book.py").exists():
        if root.parent == root:
            raise NeedCore("не найден каталог model/ выше листа — запуск из дерева репозитория")
        root = root.parent
    return root


def pc(x: float, n: int = 1) -> str:
    return f"{100 * float(x):.{n}f}"


def segment_rows() -> dict:
    """Строки примечания о сегментах: {(метрика, период): значение} и источники."""
    rows, src = {}, []
    with SEGMENT_FILE.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            rows[(r["metric"], r["period"])] = float(r["value"])
            src.append({k: r[k] for k in ("metric", "period", "doc", "page", "sha256")})
    return {"rows": rows, "sources": src}


def segment_fact(seg: dict, tax: float) -> dict:
    """Доходность сегмента на потребляемый капитал за полугодие, в годовом выражении."""
    r = seg["rows"]
    pbt = r[(f"{SEGMENT}_pbt", HALF)]
    cap_end, cap_start = r[(f"{SEGMENT}_capital", CAPITAL_END)], r[(f"{SEGMENT}_capital", CAPITAL_START)]
    pre_end, pre_avg = 2 * pbt / cap_end, 2 * pbt / ((cap_end + cap_start) / 2)
    return {"pbt": pbt, "capital_start": cap_start, "capital_end": cap_end,
            "pbt_prior_half": r[(f"{SEGMENT}_pbt", PRIOR_HALF)],
            "transfer_cost": r[(f"{SEGMENT}_transfer_cost", HALF)],
            "pre_tax_on_end": round(pre_end, 6), "pre_tax_on_average": round(pre_avg, 6),
            "tax": tax, "after_tax_on_end": round(pre_end * (1 - tax), 6), "after_tax_on_average": round(pre_avg * (1 - tax), 6)}


def marginal(run, book, cell, year: int, books: tuple) -> dict:
    """Рубль прироста кредита книг `books` в клетке на конец года `year`."""
    ctx = run.ctx
    tl, p = ctx.timeline, ctx.prep
    roles, dens = p.roles, book.get("capital.rwa.density")
    link_o, link_f = float(book.get("opex.volume_link")), float(book.get("fees.volume_link"))
    m_min = float(book.get("volumes.liquid_min_share"))
    liquid = [b for b in roles.assets if b not in roles.loans]
    q = cell.quarters
    qs = [k for k in tl.quarters_of_year(year) if 1 <= k <= tl.Q]
    last = qs[-1]
    bal = {b: cell.books[b]["balance"][last] for b in cell.books}
    loans = sum(bal[b] for b in books)
    yld = sum(cell.books[b]["rate"][last] * bal[b] for b in books) / loans
    liq = sum(bal[b] for b in liquid)
    yld_liq = sum(cell.books[b]["rate"][last] * bal[b] for b in liquid) / liq
    r_wh = cell.books["wholesale"]["rate"][last]
    scale = 4 / len(qs)
    loans_avg = sum(q["loans_ac_avg"][k] for k in qs) / len(qs)
    cor = sum(q["llp"][k] for k in qs) * scale / loans_avg
    opex = sum(q["opex"][k] for k in qs) * scale
    fees = sum(q["fees"][k] for k in qs) * scale
    oa, ol, al = p.oa_ratio, p.ol_ratio, p.allowance_ratio
    tau = q["tau_eff"][last]
    # оптовое фондирование выше доли якоря — клетка добирает фондирование по рынку (ликвидные активы на минимуме)
    at_floor = q["wholesale"][last] / q["funds"][last] > q["wholesale"][0] / q["funds"][0] * (1 + 1e-6)
    nonliq = (1 - al) + oa
    dens_l = sum(float(dens[b]) * bal[b] for b in books) / loans
    dens_liq = sum(float(dens[b]) * bal[b] for b in liquid) / liq
    rwa = q["rwa"][last]
    rwa_formula = (sum(float(dens[b]) * bal[b] for b in cell.books if b in dens)
                   + float(dens["other_assets"]) * (q["other_assets"][last] - (p.oa_fixed or 0)))
    kscale = rwa / rwa_formula
    d_opex, d_fees = link_o * opex / loans_avg, link_f * fees / loans_avg
    if at_floor:
        d_liq = m_min / (1 - m_min) * nonliq
        d_rwa = (dens_l + oa * float(dens["other_assets"]) + d_liq * dens_liq) * kscale
        funded = nonliq + d_liq - ol                    # оптовое фондирование на рубль кредита
        d_nii, fund_rate = yld + d_liq * yld_liq - funded * r_wh, r_wh
    else:
        funded = nonliq - ol                            # из ликвидных активов
        d_rwa = (dens_l + oa * float(dens["other_assets"]) - funded * dens_liq) * kscale
        d_nii, fund_rate = yld - funded * yld_liq, yld_liq
    cap = d_rwa * (q["req20_glide"][last] - p.t2[last] / rwa)
    pre = d_nii - cor - d_opex + d_fees
    keep = (1 - tau) * (1 - p.nci_share)
    return {"year": year, "funded_by": "wholesale" if at_floor else "liquid",
            "loan_yield": round(yld, 6), "funding_rate": round(fund_rate, 6),
            "d_nii": round(d_nii, 6), "cor": round(cor, 6), "d_opex": round(d_opex, 6), "d_fees": round(d_fees, 6),
            "pre_tax": round(pre, 6), "capital": round(cap, 6),
            "return_no_capital_credit": round(pre * keep / cap, 6),
            "return_segment_basis": round((pre + cap * fund_rate) * keep / cap, 6),
            "return_segment_basis_pre_tax": round((pre + cap * fund_rate) / cap, 6),
            "cell_roe": round(cell.annual["roe"][cell.years.index(year)], 6), "cost_of_equity": round(cell.k_t, 6)}


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="предельная доходность кредита на капитал против сегмента отчётности")
    ap.add_argument("--book", type=Path, default=None, help="машинная книга (по умолчанию — data/assumptions/assumptions.yaml)")
    ap.add_argument("--facts", type=Path, default=None, help="каталог фактов (по умолчанию — data/facts)")
    ap.add_argument("--no-write", action="store_true", help="не писать out/marginal_loan_out.json и .txt")
    ap.add_argument("--out", type=Path, default=None, help="куда писать JSON (по умолчанию — out/marginal_loan_out.json листа)")
    a = ap.parse_args(argv)
    lines: list[str] = []

    def say(text: str = "") -> None:
        lines.append(text)
        print(text)

    try:
        root = repo_root()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from model import book_schema
            from model.book import load_book, load_facts
            from model.grid import modal_cell, run_grid
            from model.live import live_from_book
        except ImportError as exc:
            raise NeedCore(f"ядро ещё не исполняет ветви книги второй формы банка: {exc}") from exc
        facts = load_facts(a.facts)
        try:
            book = load_book(a.book, facts=facts)
        except book_schema.BookError as exc:
            if "не реализовано" in str(exc):
                raise NeedCore(str(exc)) from exc
            raise
        run = run_grid(book, facts, live_from_book(book, facts))
        _, regime, _ = modal_cell(book, run.ctx.posterior)
        worlds = list(book.get("joint.world_prob"))
        cells = {w: run.cell(w, *modal_cell(book, run.ctx.posterior)[1:]) for w in worlds}
        seg = segment_rows()
        fact = segment_fact(seg, float(book.get("tax.statutory")["LT"]))
        out: dict = {"book_version": book.get("meta.version"), "book_date": str(book.get("meta.date")),
                     "regime": regime, "scenario": modal_cell(book, run.ctx.posterior)[2],
                     "links": {"opex.volume_link": float(book.get("opex.volume_link")), "fees.volume_link": float(book.get("fees.volume_link"))},
                     "liquid_min_share": float(book.get("volumes.liquid_min_share")),
                     "segment": fact, "segment_sources": seg["sources"], "marginal": {}, "pair": {}}
        say(f"книга {out['book_version']} от {out['book_date']}; клетки: режим {regime}, сценарий {out['scenario']}; связь расходов "
            f"{out['links']['opex.volume_link']}, услуг {out['links']['fees.volume_link']}; минимум ликвидных активов {out['liquid_min_share']}")
        roles = run.ctx.prep.roles
        for label, key, books in (("все кредитные книги", "all_loans", tuple(roles.loans)),
                                  ("розничные книги (карты, наличные, авто, ипотека)", "retail", RETAIL)):
            say()
            say(f"{label}: мир год | доходность кредита / ставка фондирования (чем фондируется) | ΔЧПД, CoR, Δрасходы, Δуслуги | до налога, "
                f"капитал | после налога: без кредита за капитал | базис сегмента (до налога) | ROE клетки, стоимость капитала; % кредита")
            out["marginal"][key] = {}
            for w in worlds:
                out["marginal"][key][w] = []
                for y in YEARS:
                    m = marginal(run, book, cells[w], y, books)
                    out["marginal"][key][w].append(m)
                    say(f"  {w} {y}: {pc(m['loan_yield'], 2)} / {pc(m['funding_rate'], 2)} ({'опт. фондирование' if m['funded_by'] == 'wholesale' else 'ликв. активы'}) | "
                        f"{pc(m['d_nii'], 2)} {pc(m['cor'], 2)} {pc(m['d_opex'], 2)} {pc(m['d_fees'], 2)} | {pc(m['pre_tax'], 2)} {pc(m['capital'])} | "
                        f"{pc(m['return_no_capital_credit'])} | {pc(m['return_segment_basis'])} ({pc(m['return_segment_basis_pre_tax'])}) | "
                        f"{pc(m['cell_roe'])} {pc(m['cost_of_equity'])}")
        say()
        say(f"Сегмент «Розничное финансирование», {HALF} (прим. о сегментах отчётности МСФО): прибыль до налога {fact['pbt']} млрд ₽ на "
            f"потребляемый капитал {fact['capital_start']} → {fact['capital_end']} млрд ₽: до налога {pc(fact['pre_tax_on_end'])} % на капитал конца, "
            f"{pc(fact['pre_tax_on_average'])} % на средний; после налога {pc(fact['tax'], 0)} %: {pc(fact['after_tax_on_end'])} / "
            f"{pc(fact['after_tax_on_average'])} % — базис сегмента; год назад за полугодие — {fact['pbt_prior_half']} млрд ₽ до налога; "
            f"расходы сегмента по трансфертным ценам — {fact['transfer_cost']} млрд ₽")
        anchor = out["marginal"]["retail"]
        first = [anchor[w][0]["return_segment_basis"] for w in worlds]
        out["anchor_check"] = {"model_min": min(first), "model_max": max(first),
                               "segment_low": fact["after_tax_on_end"], "segment_high": fact["after_tax_on_average"],
                               "gap_to_segment_low": round(min(first) - fact["after_tax_on_end"], 6)}
        say(f"На якоре ({YEARS[0]} год) рубль розничного кредита на базисе сегмента даёт {pc(min(first))}–{pc(max(first))} % после налога "
            f"при {pc(fact['after_tax_on_end'])}–{pc(fact['after_tax_on_average'])} % у сегмента.")
        free = run_grid(book.with_overrides({"capital.growth_constraint.enabled": False}), facts, live_from_book(book, facts))
        tl = run.ctx.timeline
        say()
        say("Опыт на ядре (книга против замыкания без ограничения роста капиталом): прирост прибыли акционеров года к приросту "
            "среднего капитала года, %")
        for w in worlds:
            a_cell, b_cell = cells[w], free.cell(w, regime, out["scenario"])
            row = {}
            for y in PAIR_YEARS:
                qs = [k for k in tl.quarters_of_year(y) if 1 <= k <= tl.Q]
                dn = sum(b_cell.quarters["ni_sh"][k] - a_cell.quarters["ni_sh"][k] for k in qs)
                db = sum(b_cell.quarters["bv"][k] - a_cell.quarters["bv"][k] for k in qs) / len(qs)
                row[str(y)] = round(dn / db, 6) if abs(db) > 1e-6 else None
            out["pair"][w] = {"d_ni_to_d_bv": row, "cost_of_equity": round(a_cell.k_t, 6),
                              "value_book": round(a_cell.v_ri, 1), "value_unconstrained": round(b_cell.v_ri, 1)}
            say(f"  {a_cell.label}: " + "; ".join(f"{y}: {'—' if v is None else pc(v)}" for y, v in row.items())
                + f" | стоимость капитала {pc(a_cell.k_t)} | стоимость клетки, млрд ₽: книга {a_cell.v_ri:.0f}, без ограничения {b_cell.v_ri:.0f}")
    except NeedCore as exc:
        print(f"нужна волна ядра: {exc}")
        return 2
    except Exception as exc:                                    # отказ книги, фактов или входов
        print(f"ОТКАЗ: {type(exc).__name__}: {exc}")
        return 1
    if not a.no_write:
        target = a.out or HERE / "out" / "marginal_loan_out.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        target.with_suffix(".txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
