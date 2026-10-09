# -*- coding: utf-8 -*-
"""Пересборка листа калибровки ОПУ: шаги 1–5 по порядку; весь вывод — в out/out.txt (и по шагам в out/sN_out.txt).
Запуск: PYTHONIOENCODING=utf-8 python run_all.py  (из любого каталога; входы — inputs/ листа)."""
import os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(HERE, 'out'), exist_ok=True)
STEPS = ['s1_op_basis.py', 's2_bridge.py', 's3_volume_cir.py', 's4_div_equity.py', 's5_proposal.py']
env = dict(os.environ, PYTHONIOENCODING='utf-8')
allout = []
for s in STEPS:
    r = subprocess.run([sys.executable, os.path.join(HERE, s)], cwd=HERE, env=env, capture_output=True)
    txt = (r.stdout.decode('utf-8', 'replace') + r.stderr.decode('utf-8', 'replace')).replace('\r\n', '\n')   # выходы листа — с LF
    open(os.path.join(HERE, 'out', s.split('_')[0] + '_out.txt'), 'w', encoding='utf-8', newline='\n').write(txt)
    allout.append(txt)
    print(s, 'код', r.returncode, 'строк', txt.count('\n'))
    if r.returncode:
        print(txt[-2000:]); sys.exit(r.returncode)
open(os.path.join(HERE, 'out', 'out.txt'), 'w', encoding='utf-8', newline='\n').write('\n'.join(allout))
