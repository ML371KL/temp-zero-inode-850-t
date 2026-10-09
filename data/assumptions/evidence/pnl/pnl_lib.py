# -*- coding: utf-8 -*-
"""Общие функции листа калибровки ОПУ (calib-pnl, Т-Технологии 850-t).
Все пути — относительно каталога inputs/ листа (те же, что в папке передачи этапа 1); скрипты читают только
малые входы: листы этапа 1 и исследования, сокращённые до нужных строк."""
import csv, os, json, collections, datetime, hashlib, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, 'inputs')                                    # малые входы: те же относительные пути, что в папке передачи
OUT = os.path.join(HERE, 'out')
os.makedirs(OUT, exist_ok=True)

QS = ['1Q2024', '2Q2024', '3Q2024', '4Q2024', '1Q2025', '2Q2025', '3Q2025', '4Q2025', '1Q2026', '2Q2026']
B9 = ['4Q2024', '1Q2025', '2Q2025', '3Q2025', '4Q2025', '1Q2026', '2Q2026']        # окно правила B9 (семь кварталов после Росбанка)


def rel(*p):
    return os.path.join(ROOT, *p)


def sha16(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()[:16]


def read_csv(*p):
    with open(rel(*p), encoding='utf-8') as f:
        return list(csv.DictReader(f))


def table(rows, key='metric', per='period'):
    """{metric: {period: (value, src)}} из листа формата Сбера (9 колонок)."""
    d = collections.defaultdict(dict)
    for r in rows:
        try:
            v = float(r['value'])
        except (ValueError, TypeError):
            continue
        page = r.get('page', '')
        src = f"{r.get('doc', '')}, {'с. ' if page.replace(' ', '').replace('|', '').isdigit() else ''}{page}"
        d[r[key]][r[per]] = (v, src)
    return d


def qparts(p):                      # '2Q2026' → (2026, 2)
    return int(p[2:]), int(p[0])


def qlabel(y, q):
    return f"{q}Q{y}"


def qprev(p, k=1):
    y, q = qparts(p)
    n = y * 4 + (q - 1) - k
    return qlabel(n // 4, n % 4 + 1)


def qend(p):
    y, q = qparts(p)
    m = q * 3
    d = {3: 31, 6: 30, 9: 30, 12: 31}[m]
    return f"{y}-{m:02d}-{d:02d}"


def qdays(p):
    y, q = qparts(p)
    a = datetime.date(y, 3 * q - 2, 1)
    b = datetime.date(y + (q == 4), (3 * q) % 12 + 1, 1)
    return (b - a).days


def ru(x, nd=1):
    if x is None:
        return '—'
    s = f"{x:,.{nd}f}".replace(',', ' ').replace('.', ',')
    return s.replace('-', '−')


def pct(x, nd=2):
    return '—' if x is None else ru(x * 100, nd) + ' %'


def write_csv(name, rows, cols=None):
    cols = cols or list(rows[0].keys())
    with open(os.path.join(OUT, name) if not os.path.isabs(name) else name, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(cols)
        for r in rows:
            w.writerow(['' if r.get(c) is None else (f"{r[c]:.6g}" if isinstance(r[c], float) else r[c]) for c in cols])


def mean_sd(xs):
    xs = list(xs)
    return statistics.fmean(xs), (statistics.stdev(xs) if len(xs) > 1 else float('nan')), len(xs)


def ols(x, y):
    n = len(x); mx = sum(x) / n; my = sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x); sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    b = sxy / sxx; a = my - b * mx
    res = [yy - a - b * xx for xx, yy in zip(x, y)]
    s2 = sum(e * e for e in res) / max(n - 2, 1); se = (s2 / sxx) ** 0.5
    syy = sum((yy - my) ** 2 for yy in y)
    return dict(a=a, b=b, se=se, r2=1 - sum(e * e for e in res) / syy if syy else float('nan'), n=n)


def load_yaml(*p):
    import yaml
    with open(os.path.join(*p), encoding='utf-8') as f:
        return yaml.safe_load(f)
