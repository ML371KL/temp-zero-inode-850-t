# -*- coding: utf-8 -*-
"""Полы и требования по капиталу из траекторий книги против регуляторного графика этапа 1 (MODEL §3.3, §4.12, §4.13).

floor20_s,Y = capital.minimum.n20_0 + conservation + sifi + ccyb;  floor11_s,Y = capital.minimum.n1_1 + те же надбавки;
требование без глиссады req_j = пол_j + capital.mgmt_buffer_j (порог политики у Т равен нулю);
требование с глиссадой req*_j,q = max по h = 0…H (req_j,q+h − h × δ): H = lookahead_quarters, δ = glide_pp_per_quarter.
Траектории книги читаются по годам правилом MODEL §0.4. Сверяется: полы и вычеты сценариев — с графиком этапа 1
(inputs/stage1/regulation/schedule.yaml: 220-И пп. 2.2, 3.2, 3.4; решения Банка России 08.11.2024 и 27.07.2026;
доклады о системно значимых банках 22.05.2025 и 20.02.2026 — источники с sha256 в самом графике) и с таблицей листа
капитала (inputs/stage1/calib/capital/out/p3_floors.csv); пример глиссады договора ключей — сценарий «по графику»,
3-й квартал 2026 — 2-й квартал 2028: 12,00; 12,25; 12,50; 12,75; 13,00; 13,25; 13,50; 13,50 %.
Запас менеджмента графика этапа 1 (2,0 п.п.) устарел и не читается: запас книги — 1,5 п.п.
Запуск из корня репозитория: python -B data/assumptions/evidence/regulation/floors.py → out/floors_out.json
"""
from __future__ import annotations

import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEDULE = os.path.join(HERE, "inputs", "stage1", "regulation", "schedule.yaml")
P3 = os.path.join(HERE, "inputs", "stage1", "calib", "capital", "out", "p3_floors.csv")
OUT = os.path.join(HERE, "out")
sys.path.insert(0, os.path.dirname(HERE))
import evlib  # noqa: E402

YEARS = list(range(2026, 2032))
GLIDE_EXAMPLE = [0.1200, 0.1225, 0.1250, 0.1275, 0.1300, 0.1325, 0.1350, 0.1350]   # договор ключей, «по графику»


def floors(book: dict, s: str, year: int) -> tuple[float, float, float]:
    """(пол Н20.0, пол Н20.1, вычет сценария) в году."""
    cap = book["capital"]
    sc = cap["reg_scenarios"][s]
    add = sum(evlib.year_value(sc[k], year) for k in ("conservation", "sifi", "ccyb"))
    return (cap["minimum"]["n20_0"] + add, cap["minimum"]["n1_1"] + add,
            evlib.year_value(sc["deduction_pp"]["n20_0"], year))


def glide(book: dict, s: str, quarters: int = 12) -> list[dict]:
    """Требование с глиссадой по кварталам сетки от первого прогнозного квартала."""
    cap = book["capital"]
    gc = cap["growth_constraint"]
    H, delta = int(gc["lookahead_quarters"]), float(gc["glide_pp_per_quarter"])
    y0, q0 = int(book["meta"]["first_period"][:4]), int(book["meta"]["first_period"][5])
    last = int(book["meta"]["last_period"][:4])

    def req(i: int) -> tuple[float, float]:
        t = y0 * 4 + (q0 - 1) + i
        f20, f11, _ = floors(book, s, min(t // 4, last))
        return f20 + cap["mgmt_buffer"]["n20_0"], f11 + cap["mgmt_buffer"]["n1_1"]

    out = []
    for i in range(quarters):
        t = y0 * 4 + (q0 - 1) + i
        r20 = max(req(i + h)[0] - h * delta for h in range(H + 1))
        r11 = max(req(i + h)[1] - h * delta for h in range(H + 1))
        out.append({"period": f"{t // 4}Q{t % 4 + 1}", "req20_glide": round(r20, 6), "req11_glide": round(r11, 6),
                    "req20": round(req(i)[0], 6), "req11": round(req(i)[1], 6)})
    return out


def compute() -> dict:
    book = evlib.template()
    cap = book["capital"]
    sched = yaml.safe_load(open(SCHEDULE, encoding="utf-8"))["schedule"]
    p3 = {(r["сценарий"], int(r["год"])): r for r in evlib.read_csv(evlib.Path(P3))}
    out: dict = {"book": {}, "stage1": {}, "glide": {}, "mismatches": []}
    for s in cap["reg_scenarios"]["ids"]:
        rows = {}
        for y in YEARS:
            f20, f11, ded = floors(book, s, y)
            rows[str(y)] = {"floor20": round(f20, 5), "floor11": round(f11, 5), "deduction": round(ded, 5),
                            "req20": round(f20 + cap["mgmt_buffer"]["n20_0"], 5),
                            "req11": round(f11 + cap["mgmt_buffer"]["n1_1"], 5)}
            st1 = sched[s]["gradual"][y]
            out["stage1"].setdefault(s, {})[str(y)] = {"floor20": st1["floor"]["N20_0"] / 100,
                                                       "floor11": st1["floor"]["N20_1"] / 100,
                                                       "deduction": st1["deduction_pp"] / 100}
            pairs = (("floor20", st1["floor"]["N20_0"] / 100, float(p3[(s, y)]["пол Н20.0"]) / 100),
                     ("floor11", st1["floor"]["N20_1"] / 100, float(p3[(s, y)]["пол Н20.1"]) / 100),
                     ("deduction", st1["deduction_pp"] / 100, float(p3[(s, y)]["вычет, п.п."]) / 100))
            for k, graph, sheet in pairs:
                if abs(rows[str(y)][k] - graph) > 1e-9:
                    out["mismatches"].append(f"{s} {y} {k}: книга {rows[str(y)][k]} против графика {graph}")
                if abs(rows[str(y)][k] - sheet) > 1e-9:
                    out["mismatches"].append(f"{s} {y} {k}: книга {rows[str(y)][k]} против листа капитала {sheet}")
        out["book"][s] = rows
        out["glide"][s] = glide(book, s)
    example = [r["req20_glide"] for r in out["glide"]["schedule"][:8]]
    out["glide_example"] = {"book": example, "contract": GLIDE_EXAMPLE}
    if any(abs(a - b) > 1e-9 for a, b in zip(example, GLIDE_EXAMPLE)):
        out["mismatches"].append(f"глиссада «по графику»: {example} против примера договора {GLIDE_EXAMPLE}")
    for s, rows in out["glide"].items():                # прирост требования за квартал — не больше шага глиссады
        delta = float(cap["growth_constraint"]["glide_pp_per_quarter"])
        steps = [b["req20_glide"] - a["req20_glide"] for a, b in zip(rows, rows[1:])]
        if max(steps) > delta + 1e-9:
            out["mismatches"].append(f"{s}: требование с глиссадой растёт за квартал больше чем на {delta}")
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    res = compute()
    evlib.write_json(evlib.Path(OUT) / "floors_out.json", res)
    for s, rows in res["book"].items():
        print(f"{s:9s} пол Н20.0: " + "  ".join(f"{y}:{100 * r['floor20']:.2f}" for y, r in rows.items())
              + " | требование: " + " ".join(f"{100 * r['req20']:.2f}" for r in rows.values()))
        print(f"{'':9s} пол Н20.1: " + "  ".join(f"{y}:{100 * r['floor11']:.2f}" for y, r in rows.items()))
        print(f"{'':9s} требование с глиссадой, 8 кварталов: "
              + " ".join(f"{100 * r['req20_glide']:.2f}" for r in res["glide"][s][:8]))
    print("расхождения с графиком этапа 1 и листом капитала:", res["mismatches"] or "нет")
    return 1 if res["mismatches"] else 0


if __name__ == "__main__":
    sys.exit(main())
