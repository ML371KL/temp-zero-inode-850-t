# -*- coding: utf-8 -*-
"""Режимы: пути CoR и сдвигов ЧПМ книги, вероятности, σ и ρ наблюдений, κ — против листа режимов этапа 1 (MODEL §3.2, §12).

Малые входы — выходы листа режимов (inputs/stage1/regimes: стоимость риска по состояниям в пересчёте на состав портфеля
30.06.2026, годовая про-форма 2014–2026, регрессии κ, срезы σ и ρ, сверка путей). Лист повторяет:
  * взвешенные по вероятностям режимов пути CoR книги (2-е полугодие 2026, 2027, 2028, 2029, LT), ожидание 2027–2029
    и взвешенный LT — против чисел листа; ключ года у путей с квартальными ключами — среднее кварталов;
  * уровни режимов против пересчитанной истории: спокойное, среднее, стрессовое и кризисное состояния;
  * частоты состояний по годам истории против вероятностей книги и концы оси «вероятности режимов»;
  * взвешенные сдвиги ЧПМ режимов (LT — в пределах 0 ± 0,03 п.п.);
  * σ наблюдений CoR и ЧПМ — внутри срезов листа; κ — внутри регрессий без кварталов шока (окна с 2016 и с 2018 года, лаг 0–4); добавку κ в стационаре
    миров (реальная ставка мира сверх мира N) и ожидаемый по мирам LT-CoR;
  * кризисные ключи лежат в году шока; множитель RWA кризиса — минимум в году шока.
Запуск из корня репозитория: python -B data/assumptions/evidence/regimes/regimes_book.py → out/regimes_out.json
(код выхода 1 — расхождение с шаблоном книги).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
IN = HERE / "inputs" / "stage1"
OUT = HERE / "out"
sys.path.insert(0, str(HERE.parent))
import evlib  # noqa: E402

YEARS = (2026, 2027, 2028, 2029)
STATE_OF = {"soft": "calm", "norm": "mid", "downturn": "stress_year", "crisis": "crisis_year"}


def compute() -> dict:
    book = evlib.template()
    reg, probs = book["regimes"], book["joint"]["regime_prob"]
    ids = reg["ids"]
    cmp = evlib.Compare()
    check = json.loads((IN / "regimes/paths_check.json").read_text(encoding="utf-8"))
    sheet = check["предложение regimes"]
    # --- пути CoR: взвешенно по режимам
    expect = [sum(probs[r] * evlib.year_value(reg[r]["cor"], y) for r in ids) for y in YEARS]
    lt = sum(probs[r] * reg[r]["cor"]["LT"] for r in ids)
    avg = sum(expect[1:]) / 3
    for y, mine, theirs in zip(YEARS, expect, sheet["expect"]):
        cmp.eq(f"взвешенный CoR {y}", round(100 * mine, 3), round(theirs, 3), 1e-6)
    cmp.eq("взвешенный LT-CoR", round(100 * lt, 3), round(sheet["lt_weighted"], 3), 1e-6)
    cmp.eq("ожидание CoR 2027–2029", round(100 * avg, 3), round(sheet["avg_2027_2029"], 3), 1e-6)
    for r in ids:
        cor = reg[r]["cor"]
        qs = [cor[k] for k in sorted(cor) if "Q" in str(k)]
        if qs:
            year = sorted(k for k in cor if "Q" in str(k))[0][:4]
            cmp.eq(f"regimes.{r}.cor.{year} = среднее кварталов", cor[year], sum(qs) / len(qs), 1e-9)
    # --- уровни режимов против пересчитанной истории (итог по портфелю, % годовых)
    states = {r["book"]: r for r in evlib.read_csv(IN / "regimes/cor_by_state.csv")}["TOTAL"]
    shock = int(book["meta"]["anchor_period"][:4]) + reg["crisis"]["shock_year_offset"]
    levels = {}
    for r in ids:
        st = STATE_OF[r]
        short = st.split("_")[0]
        lo, hi = float(states[f"{short}_lo"]) / 100, float(states[f"{short}_hi"]) / 100
        peak = max(evlib.year_value(reg[r]["cor"], y) for y in YEARS)
        levels[r] = {"history_state": float(states[st]) / 100, "history_range": [lo, hi], "book_peak_year": peak,
                     "book_lt": reg[r]["cor"]["LT"]}
    cmp.true("год шока кризиса внутри истории кризисных лет на нынешнем портфеле",
             levels["crisis"]["history_range"][0] <= evlib.year_value(reg["crisis"]["cor"], shock) <= levels["crisis"]["history_range"][1])
    cmp.true("год спада внутри истории стрессовых лет на нынешнем портфеле",
             levels["downturn"]["history_range"][0] <= evlib.year_value(reg["downturn"]["cor"], shock) <= levels["downturn"]["history_range"][1])
    for name, r in (("Кризис: сдвиг CoR", "crisis"), ("Спад: сдвиг CoR", "downturn")):
        ax = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["name"].startswith(name))
        base = evlib.year_value(reg[r]["cor"], shock)
        lo, hi = levels[r]["history_range"]
        cmp.true(f"ось «{ax['name']}» накрывает историю состояния",
                 abs(base + ax["low"] - lo) <= 0.0006 and abs(base + ax["high"] - hi) <= 0.0006)
    # --- частоты состояний и вероятности
    classes = check["year_classes"]
    n = sum(len(v) for v in classes.values())
    freq = {r: len(classes[r]) / n for r in ids}
    cmp.eq("сумма вероятностей режимов", sum(probs.values()), 1.0, 1e-12)
    ax = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["paths"] == ["joint.regime_prob"])
    for end in (ax["low"], ax["high"]):
        rest = 1 - end["crisis"]
        for r in ids:
            if r != "crisis":
                cmp.eq(f"ось вероятностей: {r} пропорционально книге при кризисе {end['crisis']}",
                       end[r], round(probs[r] / (1 - probs["crisis"]) * rest, 4), 1.5e-4)
    # --- сдвиги ЧПМ режимов
    nim_lt = sum(probs[r] * reg[r]["nim_shift"]["LT"] for r in ids)
    nim_shock = sum(probs[r] * evlib.year_value(reg[r]["nim_shift"], shock) for r in ids)
    cmp.true("взвешенный LT-сдвиг ЧПМ в пределах 0 ± 0,03 п.п.", abs(nim_lt) <= 0.0003 + 1e-12)
    cmp.true("сдвиг ЧПМ режимов в 2026 году — 0", all(evlib.year_value(reg[r]["nim_shift"], 2026) == 0.0 for r in ids))
    # --- σ и ρ наблюдений, κ
    ss = json.loads((IN / "regimes/season_sigma.json").read_text(encoding="utf-8"))
    obs = book["joint"]["regime_update"]["observables"]
    sd_cor = sorted(v["sd_pp"] / 100 for v in ss["sigma_cor"].values() if v.get("sd_pp") is not None)
    sd_nim = sorted(v["sd_pp"] / 100 for v in ss["sigma_nim"].values() if v.get("sd_pp") is not None)
    cmp.true("σ наблюдения CoR внутри срезов листа", sd_cor[0] <= obs["cor"]["sigma_pp"] <= sd_cor[-1])
    cmp.true("σ наблюдения ЧПМ внутри срезов листа", sd_nim[0] <= obs["nim"]["sigma_pp"] <= sd_nim[-1])
    kp = json.loads((IN / "regimes/kappa.json").read_text(encoding="utf-8"))
    no_shock = sorted(r["kappa"] for r in kp["regressions"]         # портфель в нынешнем составе, годы без шоков,
                      if r["name"].startswith("PF") and "без шоков" in r["name"] and r["name"].endswith("| rr")
                      and ("2016К1" in r["name"] or "2018К1" in r["name"]) and r["lag"] <= 4)   # окна с 2016 и с 2018 года, лаг 0–4
    kappa = book["credit"]["kappa"]
    kax = next(a for a in book["valuation"]["uncertainty"]["axes"] if a["paths"] == ["credit.kappa"])
    cmp.true("κ внутри оценок без кварталов шока", bool(no_shock) and no_shock[0] <= kappa <= no_shock[-1])
    cmp.true("ось κ накрывает оценки без кварталов шока", kax["low"] <= no_shock[0] and no_shock[-1] <= kax["high"] + 1e-9)
    # реальная ставка мира после фазы роста — та, что читает ядро (worlds.<W>.real_key в последнем полугодии сетки):
    # поле записи миров семейства за последнее полугодие last_period
    last = book["meta"]["last_period"]
    half = f"{last[:4]}H{1 if int(last[5]) <= 2 else 2}"
    rrow = {(r["world"], r["period"]): r for r in evlib.record()["rows"]}
    real = {w: float(rrow[(w, half)]["real_key_fwd12m"]) / 100 for w in book["worlds"]["ids"]}
    ref = book["credit"].get("kappa_reference_world")          # мир, в котором стоят уровни режимов (MODEL §4.6)
    add = {w: kappa * (real[w] - real[ref]) if ref else kappa * max(0.0, real[w] - real["N"]) for w in real}
    cmp.eq("мир-опора добавки κ — мир «рыночные ставки как есть»: уровень окна стоит в мире окна", ref, book["joint"]["macro_neutral_world"])
    wp = book["joint"]["world_prob"]
    lt_expected = lt + sum(wp[w] * add[w] for w in wp)
    # --- кризисные ключи в году шока
    crisis = reg["crisis"]
    cmp.eq("разовый убыток — в году шока", crisis["one_off_loss"]["period"][:4], str(shock))
    cmp.eq("первый год переопределения роста — год шока", min(int(y) for y in crisis["loan_growth_override"]), shock)
    mult = crisis["rwa_density_mult"]
    cmp.true("множитель RWA кризиса: минимум в году шока, год якоря — 1",
             mult[str(shock)] == min(v for k, v in mult.items() if k != "LT_from") and mult[str(shock - 1)] == 1.0)
    return {
        "cor_weighted": {str(y): round(v, 5) for y, v in zip(YEARS, expect)} | {"LT": round(lt, 5), "avg_2027_2029": round(avg, 5)},
        "cor_levels": levels,
        "frequencies": {"years": n, "history": {r: round(v, 3) for r, v in freq.items()}, "book": probs},
        "nim_shift_weighted": {"LT": round(nim_lt, 6), str(shock): round(nim_shock, 6)},
        "observables": {"cor": obs["cor"], "nim": obs["nim"], "sheet_sd_cor": [round(sd_cor[0], 5), round(sd_cor[-1], 5)],
                        "sheet_sd_nim": [round(sd_nim[0], 5), round(sd_nim[-1], 5)]},
        "kappa": {"book": kappa, "no_shock_positive": [round(no_shock[0], 3), round(no_shock[-1], 3)] if no_shock else None,
                  "reference_world": ref, "real_rate_lt": {w: round(v, 4) for w, v in real.items()},
                  "stationary_addition": {w: round(v, 5) for w, v in add.items()},
                  "cor_lt_expected_over_worlds": round(lt_expected, 5)},
        "shock_year": shock,
        "book_mismatches": cmp.mismatches,
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    res = compute()
    evlib.write_json(OUT / "regimes_out.json", res)
    for k in ("cor_weighted", "frequencies", "nim_shift_weighted", "observables", "kappa"):
        print(k, res[k])
    print("расхождения с шаблоном:", res["book_mismatches"] or "нет")
    return 1 if res["book_mismatches"] else 0


if __name__ == "__main__":
    sys.exit(main())
