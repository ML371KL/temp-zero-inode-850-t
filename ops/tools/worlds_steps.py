# -*- coding: utf-8 -*-
"""Шаги приёма миров книги Т-Технологий, которые не сводятся к числу правила: файлы, вывод на ядре, таблицы, прогулка,
быстрые числа (их зовёт манифест data/assumptions/worlds_dependents.yaml; команда — ops/tools/adopt_worlds.py).

  python -B ops/tools/worlds_steps.py paths [--check]
      квартальные пути миров (лист этапа 1 world_paths_quarterly, семейный) из записи книги → копии малых входов листов
      nii, pnl, regimes (`inputs/stage1/worlds/world_paths_quarterly.csv`) и их строки в `inputs/SOURCES.json`;
  python -B ops/tools/worlds_steps.py derive [--full]
      вывод на ядре (evidence/path/derive_on_engine.py) порядком книги: запуск 1 — с чисел книги (печать —
      out/derive_first.txt), старт out/derive_start.json (`before` — выведенные числа прежней книги, `keys` — числа
      запуска 1, дата, версия книги и миров), запуск 2 — `--start` (out/derive_out.json и .txt; числа книги — из него).
      Приём той же версии миров (WORLDS_FROM_VERSION = WORLDS_VERSION) при старте той же версии — повтор вывода с
      записанного старта: запись обязана воспроизвестись; `--full` — всё заново;
  python -B ops/tools/worlds_steps.py tables [--force]
      таблицы книги (model.book_results), если отпечаток книги (`reference_variants_book` таблиц) или её версия не
      совпадают с книгой; иначе — «пересчёт не нужен»;
  python -B ops/tools/worlds_steps.py control
      контрольная модель (`tests.test_control_model --write`); вне допуска — код 1; строки те же — файл не трогается
      (метка дня и коммита счёта остаются прежними);
  python -B ops/tools/worlds_steps.py walk
      прогулка версий от прошлой выпущенной книги (тег `book-<версия>`) к книге дерева: файл шагов — из блока `walk`
      манифеста, печать — out/walk_<было>_to_<стало>.txt; обе проверки прогулки обязаны сказать «ДА»;
  python -B ops/tools/worlds_steps.py changes
      журнал версии книги `data/assumptions/V<версия>-CHANGES.md`: ключи шаблона «было → стало» против прошлой
      выпущенной книги и строки прогулки (проза разделов — человеку);
  python -B ops/tools/worlds_steps.py quick --out ФАЙЛ [--draws 500]
      быстрые числа книги дерева (формат model-kit: point, median, low, high, print, worlds, runs, seed).

Строки вывода «ИТОГ: …» команда приёма кладёт в отчёт шага, «ФЛАГ: …» — в красные флаги.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import worlds_rules as R  # noqa: E402

BOOK = ROOT / "data" / "assumptions"
EV = BOOK / "evidence"
PATH_AREAS = ("nii", "pnl", "regimes")
PATH_REL = "stage1/worlds/world_paths_quarterly.csv"
DERIVE = EV / "path" / "derive_on_engine.py"
OUT = EV / "path" / "out"
MANIFEST = BOOK / "worlds_dependents.yaml"
PY = sys.executable


def say(line: str) -> None:
    print(line, flush=True)


def env() -> dict:
    return dict(os.environ, PYTHONIOENCODING="utf-8")


def record() -> dict:
    return json.loads((BOOK / "worlds_source.json").read_bytes().decode("utf-8"))


def template() -> dict:
    return yaml.safe_load((BOOK / "assumptions_template.yaml").read_text(encoding="utf-8"))


def same_version() -> bool:
    v, f = os.environ.get("WORLDS_VERSION"), os.environ.get("WORLDS_FROM_VERSION")
    return bool(v) and v == f


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


# ----------------------------------------------------------------------------------------------- пути миров
def cmd_paths(a) -> int:
    body = R.world_paths_csv(record())
    sha, n = hashlib.sha256(body).hexdigest(), body.count(b"\n")
    bad, wrote = [], []
    for area in PATH_AREAS:
        dst = EV / area / "inputs" / PATH_REL
        src = EV / area / "inputs" / "SOURCES.json"
        doc = json.loads(src.read_text(encoding="utf-8"))
        hits = [f for f in doc["files"] if f["path"] == PATH_REL]
        if len(hits) != 1:
            say(f"ФЛАГ: {area}: в SOURCES.json нет строки {PATH_REL}")
            return 1
        new = copy.deepcopy(doc)
        row = next(f for f in new["files"] if f["path"] == PATH_REL)
        row.update(sha256_full=sha, sha256_input=sha, rows_kept=n, rows_total=n)
        for path, data in ((dst, body), (src, dump(new).encode("utf-8"))):
            if not path.exists() or path.read_bytes() != data:
                if a.check:
                    bad.append(path.relative_to(ROOT).as_posix())
                else:
                    path.write_bytes(data)
                    wrote.append(path.relative_to(ROOT).as_posix())
    if bad:
        say("РАСХОЖДЕНИЕ путей миров с записью: " + ", ".join(bad))
        return 1
    say(f"ИТОГ: пути миров {sha[:8]}… ({n - 1} строк) — " + (f"записаны: {len(wrote)} файл(ов)" if wrote else "как в дереве"))
    return 0


# ----------------------------------------------------------------------------------------------- вывод на ядре
def run_derive(*extra: str, out: Path, printed: Path) -> dict:
    p = subprocess.run([PY, "-B", str(DERIVE), "--out", str(out), *extra], cwd=ROOT, env=env(), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    printed.write_text(p.stdout, encoding="utf-8", newline="\n")
    if p.returncode != 0:
        say("\n".join((p.stdout + p.stderr).strip().splitlines()[-12:]))
        raise SystemExit(f"вывод на ядре вернул {p.returncode}")
    res = json.loads(out.read_text(encoding="utf-8"))
    conv = res.get("convergence") or {}
    if not conv.get("converged"):
        raise SystemExit(f"вывод на ядре не сошёлся: {conv}")
    return res


def rounds(res: dict) -> str:
    return " → ".join(f"{r['max_relative_change']:.2e}" for r in res["convergence"]["rounds"])


def cmd_derive(a) -> int:
    start_path = OUT / "derive_start.json"
    start = json.loads(start_path.read_text(encoding="utf-8")) if start_path.exists() else None
    v = os.environ.get("WORLDS_VERSION")
    if not a.full and same_version() and start and start.get("worlds_version") == v:
        res = run_derive("--start", str(start_path), out=OUT / "derive_out.json", printed=OUT / "derive_out.txt")
        say(f"ИТОГ: та же версия миров — повтор вывода со старта {start.get('date')} (книга {start.get('book_version')}): "
            f"круги {rounds(res)}")
        return 0
    book = template()
    tmp = ROOT / "var" / "adopt"
    tmp.mkdir(parents=True, exist_ok=True)
    first = run_derive(out=tmp / "derive_first.json", printed=OUT / "derive_first.txt")
    keys = first["keys"]
    before = {}
    for dotted in keys:
        node = book
        for part in dotted.split("."):
            node = node[part]
        before[dotted] = node
    prev = (start or {}).get("book_version", "?")
    ver, today = str(book["meta"]["version"]), dt.date.today()
    new_start = {
        "note": (f"старт повторного вывода книги {ver} (миры {v}, {today.strftime('%d.%m.%Y')}): поле before — числа книги "
                 f"до вывода (выведенные на ядре числа книги {prev}); поле keys — записанные числа первого запуска (печать — "
                 f"derive_first.txt). Первый запуск начат с чисел книги на шаблоне {ver}: запись миров, надстройка, ключи "
                 f"спредов, путь пакета Яндекса и фактический ключ оттока средств клиентов — на мирах {v} (правила "
                 f"ops/tools/worlds_rules.py), выведенные числа — книги {prev}; команда приёма миров ops/tools/adopt_worlds.py"),
        "date": today.isoformat(), "book_version": ver, "worlds_version": v, "before": before, "keys": keys}
    start_path.write_text(dump(new_start), encoding="utf-8", newline="\n")
    res = run_derive("--start", str(start_path), out=OUT / "derive_out.json", printed=OUT / "derive_out.txt")
    say(f"ИТОГ: вывод на ядре двумя запусками: круги {rounds(first)}; {rounds(res)}")
    return 0


# ----------------------------------------------------------------------------------------------- таблицы и контроль
def cmd_tables(a) -> int:
    sys.path.insert(0, str(ROOT))
    from model.book import load_book, load_facts  # noqa: PLC0415
    book = load_book(facts=load_facts())
    res_path = BOOK / "results.json"
    res = json.loads(res_path.read_text(encoding="utf-8")) if res_path.exists() else {}
    ver = str(book.get("meta.version"))
    if not same_version():
        say("ФЛАГ: подпись справочного варианта window_level_in_modal_cell (маржа и C/I модальной клетки варианта) — числа "
            "прежней книги: правило без прогона сетки варианта не считается; сверить и при правке — таблицы заново")
    if not a.force and res.get("reference_variants_book") == book.digest and str(res.get("book_version")) == ver:
        say(f"ИТОГ: таблицы посчитаны на этой книге (отпечаток {book.digest[:12]}…, версия {ver}) — пересчёт не нужен")
        return 0
    p = subprocess.run([PY, "-B", "-m", "model.book_results"], cwd=ROOT, env=env(), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        say((p.stdout + p.stderr).strip()[-2000:])
        return 1
    res = json.loads(res_path.read_text(encoding="utf-8"))
    h = res["headline"]
    say(f"ИТОГ: таблицы книги {ver}: медиана {h['median']:.2f} (печать {h.get('printed_median')}), точка {h['point']:.2f}, "
        f"низ {h['low']:.2f}, верх {h['high']:.2f}")
    return 0


def cmd_control(a) -> int:
    path = ROOT / "data" / "checks" / "control_model.json"
    old = path.read_bytes() if path.exists() else None
    p = subprocess.run([PY, "-B", "-m", "tests.test_control_model", "--write"], cwd=ROOT, env=env(), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0 or not path.exists():
        say((p.stdout + p.stderr).strip()[-2000:])
        return 1
    new = json.loads(path.read_text(encoding="utf-8"))
    if not new.get("all_ok") or new.get("n_bad"):
        say(f"ФЛАГ: контрольная модель — вне допуска {new.get('n_bad')} строк из {new.get('n_rows')}")
        return 1
    stamp = ("as_of", "commit")
    if old is not None:
        prev = json.loads(old.decode("utf-8"))
        if {k: v for k, v in prev.items() if k not in stamp} == {k: v for k, v in new.items() if k not in stamp}:
            path.write_bytes(old)
            say(f"ИТОГ: контрольная модель — те же {new['n_rows']} строк, вне допуска 0 (файл не тронут)")
            return 0
    say(f"ИТОГ: контрольная модель — {new['n_rows']} строк, вне допуска 0 (записано)")
    return 0


# ----------------------------------------------------------------------------------------------- прогулка и журнал
def released() -> list[str]:
    p = subprocess.run(["git", "-C", str(ROOT), "tag", "--list", "book-*"], capture_output=True, text=True)
    vs = [t[5:] for t in p.stdout.split() if re.fullmatch(r"book-\d+\.\d+", t)]
    return sorted(vs, key=lambda s: tuple(int(x) for x in s.split(".")))


def previous_book(ver: str) -> str:
    key = tuple(int(x) for x in ver.split("."))
    older = [v for v in released() if tuple(int(x) for x in v.split(".")) < key]
    if not older:
        raise SystemExit(f"нет выпущенной книги раньше {ver} (теги book-*)")
    return older[-1]


def walk_ctx(book: dict, ver: str, prev: str) -> dict:
    idx = json.loads((Path(os.environ["WORLDS_SOURCE_DIR"]) / "versions.json").read_text(encoding="utf-8")) \
        if os.environ.get("WORLDS_SOURCE_DIR") else None
    state = json.loads((BOOK / "worlds_state.json").read_text(encoding="utf-8"))
    entry = (idx or {}).get("versions", {}).get(state["version"]) or {}
    label = (entry.get("labels") or {}).get("walk_step") or f"миры ставок {state['version']}"
    first = str(book["meta"]["first_period"])
    q = int(first[5])
    return {"label": label[:1].upper() + label[1:], "short": (entry.get("labels") or {}).get("short", state["version"]),
            "version": state["version"], "book": ver, "prev": prev,
            "cbr_decision_ru": R.ru_date(entry["cbr_decision"]) if entry.get("cbr_decision") else "—",
            "first_quarter_ru": f"{q}-го квартала {first[:4]} года"}


def fill(text: str, ctx: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(ctx[m.group(1)]), text)


def cmd_walk(a) -> int:
    m = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    w = m["walk"]
    book = template()
    ver = str(book["meta"]["version"])
    prev = previous_book(ver)
    ctx = walk_ctx(book, ver, prev)
    lines = [fill(w["head"], ctx)]
    for s in w["steps"]:
        lines.append(f"- name: {json.dumps(fill(s['name'], ctx), ensure_ascii=False)}")
        lines.append(f"  from_end: [{', '.join(s['from_end'])}]")
    steps = ROOT / fill(w["file"], ctx)
    steps.parent.mkdir(parents=True, exist_ok=True)
    steps.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    tmp = ROOT / "var" / "adopt"
    tmp.mkdir(parents=True, exist_ok=True)
    start = tmp / f"book-{prev}.yaml"
    start.write_bytes(subprocess.run(["git", "-C", str(ROOT), "show", f"book-{prev}:data/assumptions/assumptions.yaml"],
                                     capture_output=True, check=True).stdout)
    p = subprocess.run([PY, "-B", "ops/tools/walk_book.py", "--start", str(start), "--end", "data/assumptions/assumptions.yaml",
                        "--steps", steps.relative_to(ROOT).as_posix()], cwd=ROOT, env=env(), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    out = ROOT / fill(w["out"], ctx)
    out.write_text(p.stdout, encoding="utf-8", newline="\n")
    if p.returncode != 0:
        say((p.stdout + p.stderr).strip()[-1500:])
        return 1
    rows = [ln for ln in p.stdout.splitlines() if ln and not ln.startswith(("шаг ", "последний", "книга после"))]
    say(f"ИТОГ: прогулка {prev} → {ver}: {len(rows) - 1} шагов, обе проверки «ДА»")
    return 0


def flat(d, prefix=""):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flat(v, f"{prefix}{k}."))
    else:
        out[prefix[:-1]] = d
    return out


def cmd_changes(a) -> int:
    book = template()
    ver = str(book["meta"]["version"])
    prev = previous_book(ver)
    old = yaml.safe_load(subprocess.run(["git", "-C", str(ROOT), "show", f"book-{prev}:data/assumptions/assumptions_template.yaml"],
                                        capture_output=True, check=True).stdout.decode("utf-8"))
    fo, fn = flat(old), flat(book)
    keys = sorted(k for k in set(fo) | set(fn) if fo.get(k) != fn.get(k))
    ctx = walk_ctx(book, ver, prev)
    walk_txt = ROOT / fill(yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["walk"]["out"], ctx)

    def cell(x):
        s = json.dumps(x, ensure_ascii=False) if not isinstance(x, str) else x
        return (s if len(s) <= 80 else s[:77] + "…").replace("|", "/")
    lines = [f"# Книга {ver}: {ctx['label'].lower()} — журнал версии", "",
             f"Книга {prev} → {ver}: приём миров {ctx['version']} командой `ops/tools/adopt_worlds.py` (манифест "
             f"`worlds_dependents.yaml`, отчёт — `var/adopt/{ctx['version']}/report.json`). Дата книги, цена, оценки и "
             f"зерно полосы — прежние; меняются миры и числа, зависящие от них, по правилам книги.", "",
             "## Прогулка версий", "", "```", walk_txt.read_text(encoding="utf-8").rstrip("\n") if walk_txt.exists() else "—",
             "```", "", f"## Ключи шаблона «было → стало» ({len(keys)})", "", "| ключ | было | стало |", "|---|---|---|"]
    lines += [f"| `{k}` | {cell(fo.get(k, '—'))} | {cell(fn.get(k, '—'))} |" for k in keys]
    path = BOOK / f"V{ver}-CHANGES.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    say(f"ИТОГ: журнал версии {path.name}: {len(keys)} ключей шаблона; проза разделов — просмотреть ведущему")
    return 0


# ----------------------------------------------------------------------------------------------- быстрые числа
def cmd_quick(a) -> int:
    sys.path.insert(0, str(ROOT))
    from model.book import load_book, load_facts  # noqa: PLC0415
    from model.grid import live_from_book, run_grid, world_layer  # noqa: PLC0415
    from model.uncertainty import band  # noqa: PLC0415
    facts = load_facts()
    book = load_book(facts=facts)
    run = run_grid(book, facts)
    live = live_from_book(book, facts)
    b = band(book, facts, live, draws=a.draws)
    head = b.headline(float(book.get("joint.own_macro_confidence")), dict(live.prices), str(book.get("meta.company.main_ticker")))
    out = {"point": round(run.point, 3), "median": round(float(head["median"]), 3), "low": round(run.low, 3),
           "high": round(run.high, 3), "print": head.get("printed_median"),
           "worlds": {w: round(world_layer(run, w)["price"], 3) for w in book.get("worlds.ids")},
           "runs": b.draws, "seed": b.seed, "book_version": str(book.get("meta.version"))}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(dump(out), encoding="utf-8")
    say(f"ИТОГ: быстрые числа ({b.draws} прогонов): медиана {out['median']}, точка {out['point']}")
    return 0


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("paths")
    p.add_argument("--check", action="store_true")
    p = sub.add_parser("derive")
    p.add_argument("--full", action="store_true")
    p = sub.add_parser("tables")
    p.add_argument("--force", action="store_true")
    sub.add_parser("control")
    sub.add_parser("walk")
    sub.add_parser("changes")
    p = sub.add_parser("quick")
    p.add_argument("--out", required=True)
    p.add_argument("--draws", type=int, default=500)
    a = ap.parse_args(argv)
    return globals()[f"cmd_{a.cmd}"](a)


if __name__ == "__main__":
    sys.exit(main())
