# -*- coding: utf-8 -*-
"""Лист калибровки капитала Т (этап 1б, ключ calib-capital): общий запуск.

    python capital_calib.py

Читает малые входы inputs/ (листы этапа 1 и исследования под теми же относительными путями), пишет только в out/.
Порядок: часть 1 (мост и приёмка) -> часть 2 (RWA) -> части 3, 4, 6, 7 -> out/out.txt; затем часть 5 (проба правила роста) -> out/trial_out.txt;
затем make_keys.py -> out/book_keys_capital_proposal.yaml, out/facts_capital_proposal.json, out/keys_table.csv.
"""
import cc_common
import p1_bridge, p2_rwa, p3467_misc, p5_growth_trial, make_keys

if __name__ == "__main__":
    p1_bridge.run()
    _, _, _, dn_path = p2_rwa.run()
    p3467_misc.run3()
    p3467_misc.run4()
    p3467_misc.run6()
    p3467_misc.run7()
    cc_common.flush("out.txt")
    cc_common._buf.seek(0)
    cc_common._buf.truncate(0)
    p5_growth_trial.DN_PATH = dn_path
    p5_growth_trial.run()
    cc_common.flush("trial_out.txt")
    tab = make_keys.run()
    print("ключей в таблице:", len(tab))
