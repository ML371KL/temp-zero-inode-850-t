# -*- coding: utf-8 -*-
"""Числа объяснений гейтов книги Т, которых нет полем в таблицах: составы клеток гейтов и их величины на сетке книги
(тот же счёт, что у гейтов ядра: `model.checks`, `model.grid.run_grid`).

    python -B ops/tools/gate_numbers.py [--out data/assumptions/gate_numbers.json]

Слова объяснений — шаблон `data/assumptions/gate_explanations.tpl` (пишет ведущий); файл объяснений из шаблона пишет
команда приёма миров (`ops/tools/adopt_worlds.py`, шаг `gate-texts`), числа — метками из этого выхода, таблиц книги
(`results.json`), машинной книги и листа предельного кредита. Ядро (`model/`) не трогается: функции ядра на книге
дерева. Вероятности клеток — слой «Свой макро-взгляд».
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "assumptions" / "gate_numbers.json"
STRESS = ("downturn", "crisis")


def span(xs) -> list[float]:
    xs = [x for x in xs if x is not None]
    return [min(xs), max(xs)] if xs else []


def numbers() -> dict:
    os.environ.setdefault("BANK_WORKERS", "2")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from model import checks as K
    from model.book import load_book, load_facts
    from model.grid import run_grid
    from model.live import live_from_book

    F = load_facts()
    B = load_book(None, facts=F)
    g = run_grid(B, F, live_from_book(B, F))
    ctx, tl, prob = g.ctx, g.ctx.timeline, g.layers["analytical"].prob
    cells = {c.label: c for c in g.cells}
    p = {c.label: prob[c.key] for c in g.cells}
    out: dict = {"book_version": str(B.get("meta.version")),
                 "gates": {f.name: sorted(f.cells) for f in K.check_gates(g) if f.kind == "gate" and f.fired}}

    def mass(labels) -> float:
        return sum(p[x] for x in labels)

    # guidance_gap: путь года гайденса против узлов фактов (функции гейта)
    items = [it for it in B.get("checks.guidance_items") if it.get("gate")]
    year = int(F.plain("guidance", "year"))
    bands = {}
    for it in items:
        node = F.node("guidance", str(it["path"]))
        if node.get("v") is not None and node.get("scope") != "sector":
            bands[str(it["key"])] = K.guidance_band(node)
    bases = K.guidance_bases(g, year, bands)
    vals = {lab: K.guidance_values(g, c, year, bases) for lab, c in cells.items()}

    def fails(key: str) -> list[str]:
        return sorted(lab for lab, v in vals.items() if v.get(key) is not None and not K.inside(bands[key], v[key]))
    fp, fd = fails("op_np_growth"), fails("dps_growth")
    ok = sorted(lab for lab in cells if lab not in fp and lab not in fd)
    i = cells[fp[0] if fp else ok[0]].years.index(year)
    threshold = bases["op_np_growth"] * (1 + bands["op_np_growth"][0])

    def group(labels, regimes=None, worlds=None):
        return [x for x in labels if (regimes is None or cells[x].regime in regimes) and (worlds is None or cells[x].world in worlds)]
    gp = lambda labs: span(vals[x]["op_np_growth"] for x in labs)    # noqa: E731
    gd = lambda labs: span(vals[x]["dps_growth"] for x in labs)      # noqa: E731
    short = lambda labs: span(threshold - cells[x].annual["ni_sh"][i] for x in labs)   # noqa: E731
    st, mn = group(fp, STRESS), group(fp, ("norm",), ("M",))
    out["guidance_gap"] = {
        "year": year, "band": {k: list(v) for k, v in bands.items()}, "base_ni": bases["op_np_growth"], "threshold": threshold,
        "profit_fail": fp, "dps_fail": fd, "pass": ok, "profit_fail_mass": mass(fp), "dps_fail_mass": mass(fd), "pass_mass": mass(ok),
        "stress": {"cells": st, "mass": mass(st), "growth": gp(st), "short": short(st)},
        "m_norm": {"cells": mn, "mass": mass(mn), "growth": gp(mn), "short": short(mn)},
        "nh_norm": {"growth": gp(group(cells, ("norm",), ("N", "H")))},
        "dps_fail_growth": gd(fd), "pass_growth": gp(ok), "pass_dps": gd(ok),
        "downturn_dps": gd(group(cells, ("downturn",))),
    }
    # nim_path_joint: первые N кварталов ЧПМ (упр.) против порога мира (функции гейта)
    br, tr = ctx.bridge, ctx.transmission
    n, tol = int(B.get("checks.nim_path_joint.quarters")), float(B.get("checks.nim_path_joint.tolerance"))
    nim0 = ctx.facts.need("nii_books", "nim_eng_q")
    over, caps = [], set()
    for c in g.cells:
        cap = max(br.to_mgmt_nim(nim0), br.to_mgmt_nim(tr.nss[c.world])) + tol
        caps.add(round(cap, 9))
        for q in range(1, min(n, tl.Q) + 1):
            v = c.quarters["nim"][q]
            if v is not None and br.to_mgmt_nim(v) > cap:
                over.append((br.to_mgmt_nim(v), tl.period(q), c.label))
    top = max(over) if over else None
    central = json.loads((ROOT / "data" / "assumptions" / "results.json").read_text(encoding="utf-8"))["central_cell"]["cell"]
    cc = cells[central]
    out["nim_path_joint"] = {
        "cells": sorted({x[2] for x in over}), "caps": sorted(caps), "tolerance": tol,
        "max": top[0] if top else None, "max_quarter": top[1] if top else None, "max_cell": top[2] if top else None,
        "quarters": sorted({x[1] for x in over}),
        "central": central, "central_at_max_quarter": br.to_mgmt_nim(cc.quarters["nim"][tl.index(top[1])]) if top else None,
    }
    # step_dividend и payout_cap: клетки «розничного спада», выплата года после ступени, прибыль года спада
    cap = float(B.get("dividends.policy.cap"))
    dn = sorted(group(cells, ("downturn",)))
    y1, y0 = 2027, 2026
    j1, j0 = cc.years.index(y1), cc.years.index(y0)
    under = {w: span(1 - cells[x].dps[y1] / cells[x].dps_policy[y1] for x in dn if cells[x].world == w) for w in ("N", "H", "M")}
    out["downturn"] = {
        "cells": dn, "mass": mass(dn), "under_policy": under,
        "profit_drop": span(1 - cells[x].annual["ni_sh"][j1] / cells[x].annual["ni_sh"][j0] for x in dn),
        "ni": {str(y0): span(cells[x].annual["ni_sh"][j0] for x in dn), str(y1): span(cells[x].annual["ni_sh"][j1] for x in dn)},
        "payout": span(cells[x].annual["payout"][j1] for x in dn),
        "over_cap": span(cells[x].annual["payout"][j1] - cap for x in dn),
    }
    return out


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    n = numbers()
    a.out.write_text(json.dumps(n, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"ИТОГ: числа объяснений гейтов книги {n['book_version']} — {a.out.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
