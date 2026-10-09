"""Факты эмитента (data/facts/*.json) из листов этапа 1 папки передачи.

Запуск из корня репозитория (нужна папка передачи; в CI не запускается — JSON закоммичены):

    BANK_HANDOFF_DIR=<папка передачи> python -B ops/tools/build_facts.py            # переписать data/facts
    BANK_HANDOFF_DIR=<папка передачи> python -B ops/tools/build_facts.py --check    # сверить с data/facts, не писать
    BANK_HANDOFF_DIR=<папка передачи> python -B ops/tools/build_facts.py --out DIR  # записать в DIR
    … build_facts.py --anchor 2026Q3 --out DIR [--report ОТЧЁТ.json]                # якорь — другой квартал
    python -B ops/tools/build_facts.py --report ОТЧЁТ.json --facts DIR              # отчёт квартала из готовых фактов
    python -B ops/tools/build_facts.py --expected ОТЧЁТ.json --out DIR [--facts DIR]  # отчёт квартала → факты (без папки)

СОСТАВ — три таблицы в начале файла: «книга → строки остатка и процентов» (BOOKS), «строка ОПУ ядра →
строки отчёта, операционный базис» (PNL_LINES с блоком пакета), «прочие активы и обязательства»
(OTHER_ASSETS, OTHER_LIABILITIES). Функции сборки от состава не зависят: следующий эмитент получает
сборщик заменой таблиц и параметров под ними.

Якорь — аргумент `--anchor` (по умолчанию — период закоммиченных фактов): квартал, дата, лист якоря,
нарастающий итог, конец прошлого года, окна мостов и запись реестра выводятся из него и из листов.

Читает листы этапа 1 (stage1/ifrs, mgmt, ras, market, calib) и манифесты первички (primary/MANIFEST-*.md);
sha256 каждого документа пересчитывается по файлу и сверяется с листом. Каждое число — узел
{"v", "src"} (документ, страница или «Лист!Ячейка», sha256) или {"v", "calc"} (формула из узлов);
нераскрытое — {"v": null, "calc": причина}. Схема — data/facts/SCHEMA.md, происхождение — docs/FACTS.md.

calendar.json и peers.json ведутся вручную (календари эмитента и ЦБ, отчёты аналогов): сборщик их не пишет.

Сверки печатаются; при расхождении сборка останавливается, файлы не пишутся: состав книг против листа
книг; баланс якоря; проценты книг = ЧПД; прибыль движка = операционная прибыль эмитента (квартал якоря,
год, полугодие); «отчётная = операционная + блок пакета»; нормативы формой ядра на ключах листа капитала;
решения о дивидендах (после дробления, с исходными значениями, сверка с брокерским календарём словами);
мосты упр. ↔ движок против листа калибровки.

`--report` пишет файл отчёта квартала якоря (`quarter-report/1`) — вход `ops/tools/reanchor.py --facts`.

`--expected` — сухой прогон перезаякоривания (docs/MODEL.md §15.2, docs/REANCHOR.md): факты следующего квартала
из фактов якоря (`--facts`, по умолчанию data/facts) и отчёта квартала — того же `quarter-report/1`, что пишет
`ops/tools/reanchor.py --expected` (ожидание модели). Папка передачи не нужна; пишет только в `--out`, и это не
data/facts: ожидание — не факт. Вторая, независимая от `reanchor.py` сборка фактов нового якоря: ядро обязано
прочесть из обеих одно состояние (`reanchor.py --compare-facts`).

Код выхода: 0 — собрано (или --check: файлы совпали); 1 — расхождение, ошибка сверки или нет папки.
"""

from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import hashlib
import json
import os
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FACTS = REPO / "data" / "facts"

# ══════════════════════════════════════════════════════════════════════════════════════════════════
# ТАБЛИЦА 1. Книга → строки остатка и строки процентов.
# Строка — имя метрики листов МСФО этапа 1 (stage1/ifrs); «-» перед именем — строка вычитается.
# side — сторона баланса; segment — сегмент кредитной книги для узлов «кредиты на конец прошлого
# года» (ядро группирует книги по сегменту стоимости риска); nodes — справочные узлы balance.json,
# на которые раскладывается остаток книги (узел → строки).
# ══════════════════════════════════════════════════════════════════════════════════════════════════
BOOKS: dict[str, dict] = {
    "cards": dict(name="Кредитные карты", side="asset", segment="retail",
                  balance=("loans_ac_cards_gross",), interest=("ii_cards",)),
    "cash_loans": dict(name="Кредиты наличными", side="asset", segment="retail",
                       balance=("loans_ac_cash_gross",), interest=("ii_cash_loans",)),
    "auto": dict(name="Автокредиты", side="asset", segment="retail",
                 balance=("loans_ac_auto_gross",), interest=("ii_auto",)),
    "mortgage": dict(name="Ипотека", side="asset", segment="retail",
                     balance=("loans_ac_mortgage_gross",), interest=("ii_mortgage",)),
    "sme_loans": dict(name="Кредиты МСБ", side="asset", segment="retail",
                      balance=("loans_ac_sme_gross",), interest=("ii_sme",)),
    "corp_loans": dict(name="Корпоративные кредиты и лизинг", side="asset", segment="corporate",
                       balance=("loans_ac_corp_gross", "lease_gross", "loans_fvtpl"), interest=("ii_corp", "ii_lease"),
                       nodes={"loans_fvtpl": ("loans_fvtpl",), "lease_gross": ("lease_gross",)}),
    "securities": dict(name="Долговые бумаги", side="asset",
                       balance=("sec_fvoci", "-sec_fvoci_equity", "repo_fvoci", "sec_ac", "repo_ac", "sec_fvtpl_ofz",
                                "sec_fvtpl_corp_bonds"),
                       interest=("ii_sec_fvoci", "ii_sec_ac", "ii_fvtpl"),
                       nodes={"securities.fvoci_debt": ("sec_fvoci", "-sec_fvoci_equity"),
                              "securities.fvoci_repo": ("repo_fvoci",), "securities.ac": ("sec_ac",),
                              "securities.ac_repo": ("repo_ac",),
                              "securities.fvtpl_bonds": ("sec_fvtpl_ofz", "sec_fvtpl_corp_bonds")}),
    "liquidity": dict(name="Ликвидность", side="asset",
                      balance=("cash", "mandatory_reserves", "due_from_banks"), interest=("ii_repo_and_banks",),
                      nodes={"liquidity.cash": ("cash",), "liquidity.mandatory_reserves": ("mandatory_reserves",),
                             "liquidity.due_from_banks": ("due_from_banks",)}),
    "retail_current": dict(name="Текущие счета физлиц", side="liability",
                           balance=("dep_ind_current",), interest=("ie_ind_current",),
                           nodes={"funds.retail_current": ("dep_ind_current",)}),
    "retail_term": dict(name="Срочные вклады физлиц", side="liability",
                        balance=("dep_ind_term",), interest=("ie_ind_term",),
                        nodes={"funds.retail_term": ("dep_ind_term",)}),
    "corp_funds": dict(name="Средства бизнеса", side="liability",
                       balance=("dep_corp_current", "dep_corp_term", "dep_corp_brokerage", "dep_sme_current",
                                "dep_sme_term", "dep_sme_brokerage"),
                       interest=("ie_corp", "ie_sme"),
                       nodes={"funds.corp_business": ("dep_corp_current", "dep_corp_term", "dep_corp_brokerage"),
                              "funds.sme": ("dep_sme_current", "dep_sme_term", "dep_sme_brokerage")}),
    "wholesale": dict(name="Оптовое фондирование", side="liability",
                      balance=("due_to_banks", "other_borrowed", "other_borrowed_nonfin", "sub_debt"),
                      interest=("ie_banks", "ie_securitised", "ie_bonds", "ie_sub_debt", "ie_dfa", "ie_fvtpl_liab",
                                "ie_nonfin_bills", "ie_nonfin_bonds", "ie_nonfin_loans", "ie_nonfin_dfa"),
                      nodes={"wholesale.banks": ("due_to_banks",), "wholesale.other_borrowed": ("other_borrowed",),
                             "wholesale.nonfin_debt": ("other_borrowed_nonfin",),
                             "wholesale.perpetual_sub": ("sub_debt",)}),
}
# Роли книг в ядре: балансирующие активы, пара книг средств физлиц (доля текущих счетов).
SECURITIES, LIQUIDITY, RETAIL_CURRENT, RETAIL_TERM = "securities", "liquidity", "retail_current", "retail_term"
# Проценты вне книг (остаются в ЧПД, в ставки книг не входят), взносы на страхование вкладов и строки сверки.
INTEREST_OUTSIDE = {"брокерские операции": ("ii_brokerage",), "аренда": ("ie_lease",)}
DIA_LINE = "ie_deposit_insurance"
NII_LINE, INTEREST_REVENUE, INTEREST_EXPENSE = "nii", "interest_revenue", "interest_expense"
ALLOWANCE = ("loans_ac_total_ecl", "lease_ecl")       # резерв по кредитам и лизингу (в отчёте — со знаком минус)
BOOKS_SHEET = "stage1/ifrs/anchor_books.csv"          # лист книг этапа 1 — сверка состава таблицы

# ══════════════════════════════════════════════════════════════════════════════════════════════════
# ТАБЛИЦА 2. Строка ОПУ ядра → строки отчёта (операционный базис: прибыль движка равна операционной
# прибыли акционеров в определении эмитента). Прочие строки движка — расчётные: misc_net (остаток до
# прибыли до налога), noncore_net (возврат процентов по долгу под пакет), pbt, tax, ni, ni_nci.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
PNL_LINES: dict[str, tuple[str, ...]] = {
    "nii": ("nii",),                                   # ЧПД эмитента: процентная выручка − расходы − страхование вкладов
    "fees_net": ("fees_net",),                         # услуги нетто
    "insurance_net": ("ins_net",),                     # страхование нетто
    "llp_debt_fa": ("llp_debt_fa",),                   # резервы под кредитные убытки (числитель стоимости риска)
    "opex": ("opex_tech", "opex_marketing", "opex_servicing", "opex_admin"),   # расходы по функциям
}
PNL_REPORTED = {"pbt": "pbt", "tax": "tax", "ni": "np", "ni_shareholders": "np_shareholders", "ni_nci": "np_nci"}
PNL_OPERATING_NI = "op_np"                             # операционная прибыль акционеров, строка эмитента
PNL_REFERENCE = {"fee_income": ("fee_income",), "fee_expense": ("fee_expense",),
                 "oci_fvoci": ("oci_fvoci_fv_change_net", "oci_fvoci_recycled_net"),
                 "ci_shareholders": ("ci_shareholders",)}
# Блок пакета (исключён из строк движка): строки листа «три прибыли» и входы; reval_ytd — накопленная переоценка
# главного ряда (формула квартала, которого примечание отдельно не печатает).
BLOCK = dict(sheet="stage1/ifrs/three_profits.csv", reval="tp_yandex_reval_gross_100", reval_ytd="yandex_reval",
             adj_stake_sh="tp_adj_yandex_after_tax_sh", adj_interest_sh="tp_adj_interest_loans_sh",
             nonfin_interest="ie_nonfin_borrowings", dividends_sheet="stage1/calib/pnl/inputs/yandex_dividends.csv",
             group_share_metric=("bc_catalytic_stake_pct", "2025-05-31"),   # доля группы в компании-владельце пакета
             tax_shield=0.25,                          # законная ставка налога: щит по процентам под пакет
             name="пакет Яндекса", holder="«Каталитик Пипл»")
PNL_CHECK_SHEET = "stage1/calib/pnl/op_basis_quarterly.csv"   # лист калибровки ОПУ — сверка строк движка

# ══════════════════════════════════════════════════════════════════════════════════════════════════
# ТАБЛИЦА 3. Прочие активы и обязательства: часть → строки отчёта. fixed — постоянные прочие активы
# (не растут с кредитами); reference — узел balance.json, который несёт часть справочно.
# Дивиденды к выплате лежат внутри строки «прочие обязательства» и выделяются отдельным узлом.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
OTHER_ASSETS: dict[str, dict] = {
    "yandex_stake": dict(lines=("yandex_stake_fv",), fixed=True, reference="securities.yandex_stake",
                         title="пакет Яндекса по справедливой стоимости"),
    "associates": dict(lines=("assoc_investments",), fixed=True, title="ассоциированные компании и совместные предприятия"),
    "equity_other": dict(lines=("sec_fvtpl_equity", "-yandex_stake_fv", "sec_fvtpl_funds", "sec_fvoci_equity"),
                         reference="securities.equity_other", title="прочие акции и паи"),
    "brokerage_receivables": dict(lines=("brokerage_receivables",), title="брокерская дебиторская задолженность"),
    "ppe_rou": dict(lines=("ppe_rou",), title="основные средства и права пользования"),
    "intangibles": dict(lines=("intangibles",), title="нематериальные активы"),
    "deferred_tax": dict(lines=("dta",), title="отложенный налоговый актив"),
    "current_tax": dict(lines=("current_tax_asset",), title="текущий налог к возмещению"),
    "derivatives": dict(lines=("deriv_assets",), title="производные инструменты"),
    "insurance": dict(lines=("insurance_assets",), title="активы по страхованию"),
    "other": dict(lines=("other_assets",), title="прочие активы отчёта"),
}
OTHER_LIABILITIES: dict[str, dict] = {
    "retail_brokerage": dict(lines=("dep_ind_brokerage",), reference="funds.retail_brokerage",
                             title="брокерские счета физлиц"),
    "brokerage_payables": dict(lines=("brokerage_payables",), title="брокерская кредиторская задолженность"),
    "current_tax": dict(lines=("current_tax_liab",), title="текущий налог к уплате"),
    "derivatives": dict(lines=("deriv_liab",), title="производные инструменты"),
    "deferred_tax": dict(lines=("dtl",), title="отложенное налоговое обязательство"),
    "insurance": dict(lines=("insurance_liab",), title="обязательства по страхованию"),
    "other": dict(lines=("other_liab",), title="прочие обязательства отчёта (внутри — дивиденды к выплате)"),
}
TOTAL_ASSETS, TOTAL_LIABILITIES = "total_assets", "total_liab"
EQUITY = {"total": "eq_total", "nci": "eq_nci", "bv_common": "eq_shareholders", "share_capital": "eq_share_capital",
          "share_premium": "eq_share_premium", "treasury_cost": "eq_treasury", "sbp_reserve": "eq_sbp_reserve",
          "retained_earnings": "eq_retained", "fvoci_reserve": "orf_fvoci", "other_reserves": "eq_other_reserves"}
EQUITY_PARTS = ("share_capital", "share_premium", "treasury_cost", "sbp_reserve", "retained_earnings", "fvoci_reserve",
                "other_reserves")                      # вместе = капитал акционеров
# Дивиденды к выплате: строка на конец года раскрыта в годовом отчёте; на промежуточную дату — расчёт по движению.
DIVIDENDS_PAYABLE = dict(balance="dividends_payable", declared="eqf_dividends__shareholders", paid="cf_dividends_paid")
REVERSE_REPO = ("cash_reverse_repo_lt90", "dfb_reverse_repo_gt90")   # внутри денег и средств в банках (справка)
FV_NODE = "loans_fvtpl"                                # узлы баланса, которые файл отчёта квартала называет отдельно:
FVOCI_NODES = ("securities.fvoci_debt", "securities.fvoci_repo")   # кредиты по справедливой стоимости; долговые бумаги FVOCI с репо

# ══════════════════════════════════════════════════════════════════════════════════════════════════
# Параметры сборщика (не допущения модели): начала рядов, окна, листы. К якорю не привязаны.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
PNL_FIRST = "2024Q1"            # первый квартал ОПУ в новом формате отчёта
HISTORY_FIRST = "2024Q4"        # первый конец квартала истории баланса (после присоединения Росбанка)
DEBT_SECURITIES_FROM = "2025Q4" # с этого конца квартала долговые бумаги раскрыты отдельно от акций и паёв
SECURITIES_BROAD = "invest_portfolio_ex_yandex"   # бумаги с акциями и паями без пакета — для ранних концов кварталов
CAPITAL_HISTORY_FIRST = "2024Q4"
RATES_CARRY_FROM = "2026Q3"     # с этого якоря (первый после книги 1.0) ставки книг активов несут и проценты вне книг:
#                                 правило перезаякоривания (docs/MODEL.md §15.2 п. 4) — то же, что в ops/tools/reanchor.py
BRIDGE_FIRST = "2024Q4"         # окно мостов CoR и C/I: кварталы после присоединения Росбанка — по якорь
NIM_BRIDGE_COMPARABLE_FROM = "2024Q2"   # упр. ЧПМ первого квартала ряда посчитана на одном конце квартала
# Знаменатель CoR в мосте: "books" — сумма шести кредитных книг (знаменатель движка; мост калибруется на нём же —
# решение ведущего); "ac" — кредиты по амортизированной стоимости с лизингом, без кредитов по справедливой стоимости
# (определение листа калибровки ОПУ — справочно). История моста несёт оба варианта; value, sd и gap — по выбранному.
COR_BRIDGE_DENOMINATOR = "books"
BRIDGE_CHECK = "stage1/calib/pnl/out/bridge_mgmt_ifrs_proposal.json"
CAPITAL_KEYS = "stage1/calib/capital/book_keys_capital_proposal.yaml"   # ключи листа капитала — сверка формой ядра
CAPITAL_KEYS_ANCHOR = "2026Q2"  # квартал, на котором выведены ключи листа капитала: сверка формой ядра — только на нём
#                                 (на следующем якоре вычеты и поправки выводит перезаякоривание, ops/tools/reanchor.py)
GROUP_FORM = "stage1/ras/group_f805.csv"
RAS_SHEET = "stage1/ras/pnl_ifrs_vs_group_vs_bank_quarterly.csv"
CURVE_SHEET = "stage1/calib/capital/inputs/zcyc_quarter_ends_2024_2026.csv"
KEY_RATE_SHEET = "stage1/market/cbr_key_rate_quarterly.csv"
KEY_RATE_DAILY = "stage1/market/cbr_key_rate_daily.csv"
MGMT_SHEET, GUIDANCE_SHEET = "stage1/mgmt/mgmt_kpi.csv", "stage1/mgmt/guidance.csv"
DIVIDENDS_SHEET = "stage1/market/dividends_public.csv"
BROKER_CHECK_SHEET = "stage1/market/dividends_broker_check.csv"   # итог сверки с брокерским календарём (словами)
SHARES_SHEET, ACTIONS_SHEET = "stage1/market/shares_history.csv", "stage1/market/corporate_actions.csv"
CURVE_NODES = ("1", "3", "5", "10")
TICKER = "T"
GROUP_HEAD = "АО «ТБанк», рег. № 2673"               # головная организация банковской группы (форма 0409805)
POLICY = dict(
    doc="primary/dividend_policy_red1.pdf", approved="2025-03-20",
    name="Дивидендная политика МКПАО «Т-Технологии» (редакция 2, утверждена советом директоров 20 марта 2025 года)",
    approved_by="Совет директоров, протокол без номера от 20 марта 2025 года",
    cap=0.30, cap_page=4, cap_words="п. 4.2: «Общество стремится распределять до 30% (тридцати процентов) от чистой "
                                    "прибыли по итогам года» по консолидированной отчётности МСФО",
    threshold_page=4, threshold_words="числового порога достаточности капитала в политике нет: совет директоров "
                                      "учитывает потребность в капитале и требования к нормативам (п. 4.4)",
    term_page=3, term_words="срок действия не ограничен (п. 1.5)",
    frequency="quarterly",
    text="До 30 % чистой прибыли группы по МСФО за год; решения о выплате — каждый квартал; числового порога "
         "достаточности капитала нет: совет директоров учитывает потребность в капитале и требования к нормативам.",
    valid_until_note="Срок действия политики не ограничен. Новая редакция войдёт новым фактом и новой версией книги.",
)
PAY_DAYS = (12, 18)             # дней от даты реестра до срока выплаты номинальным держателям (10 рабочих дней)
RECORD_AFTER_DECISION = (10, 20)   # дней от решения собрания до даты реестра (закон об АО; политика п. 5.5)
# Корпоративные события: дата листа → (вид, подпись для витрины). Числа и источник — из листа событий.
ACTIONS = {
    "2019-07-02": ("issue", "Вторичное размещение расписок на Лондонской бирже в июле 2019 года: 16,7 млн новых акций"),
    "2021-01-07": ("event", "Конвертация акций класса B в класс A в январе 2021 года: одна акция — один голос"),
    "2024-01-01": ("buyback_program", "Выкуп акций с рынка в 2024 году под программу мотивации"),
    "2024-01-31": ("event", "Делистинг расписок с Лондонской биржи в январе 2024 года"),
    "2024-02-26": ("event", "Регистрация компании в России (редомициляция) в феврале 2024 года"),
    "2024-05-08": ("event", "Собрание акционеров в мае 2024 года утвердило присоединение Росбанка и допэмиссию"),
    "2024-08-15": ("issue", "Допэмиссия в августе 2024 года в оплату Росбанка"),
    "2024-11-14": ("event", "Первый дивиденд после редомициляции — за девять месяцев 2024 года; далее выплаты каждый квартал"),
    "2024-11-28": ("event", "Новое название «Т-Технологии» и новый код бумаги на бирже с ноября 2024 года"),
    "2025-03-20": ("event", "Совет директоров в марте 2025 года вернул возможность допэмиссии под программу мотивации — до 1,5 % акций в год"),
    "2025-11-20": ("buyback_program", "Программа выкупа до 5 % акций до конца 2026 года, объявлена в ноябре 2025 года"),
    "2026-03-10": ("event", "Собрание акционеров в марте 2026 года утвердило дробление акций"),
    "2026-04-15": ("split", "Дробление акций 1:10"),
    "2026-06-02": ("deal", "Покупка Авто.ру за деньги, закрыта в июне 2026 года; акции не выпускались"),
    "2026-09-18": ("event", "Собрание акционеров в сентябре 2026 года увеличило число объявленных акций и разрешило допэмиссию по закрытой подписке"),
    "2026-10-01": ("deal", "Консолидация «Точки»: параметры утверждены в октябре 2026 года, оплата — новыми акциями по 320 ₽ и деньгами; закрытие ожидается в конце 2026 года"),
}
SPLIT_FIRST_TRADE = {"2026-04-15": "2026-04-17"}   # дробление → первый торговый день с новой ценой (лист событий)
GUIDANCE_ITEMS = {   # пункт гайденса → (вид, допуск точечного значения, записка для витрины, фраза пункта в строке документа)
    "op_np_growth": ("min", None, None, r"рост операционной чистой прибыли[^,;:]*?на \d+\s?% и (?:выше|более)"),
    "dps_growth": ("min", None, "граница строгая: более {bound} ₽ на акцию за {year} год при {base} ₽ за {prev} год",
                   r"(?:увеличени\w+|рост\w*) совокупных дивидендов на акцию за год более чем на \d+\s?%"),
    "roe_target": ("point", 0.005, "цель эмитента — к операционному капиталу; цель стратегии, не прогноз года",
                   r"[Цц]елевой ROE\s*~?\s*\d+\s?%"),
}
GUIDANCE_ABSENT = ("roe", "nim", "cor_max", "cir")   # пункты гайденса семейства, которых эмитент не даёт
MONTHS_GEN = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
              "ноября", "декабря")

BUILT = ("anchor", "balance", "nii_books", "pnl_quarterly", "capital", "shares", "dividends",
         "bridge_mgmt_ifrs", "bridge_ras_ifrs", "mgmt_quarterly", "guidance")
MANUAL = ("calendar", "peers")
REPORT_SCHEMA = "quarter-report/1"


ISSUER = "Т-Технологии"
PERIOD_WORDS = {"1": "три месяца", "2": "шесть месяцев", "3": "девять месяцев"}
DOC_TITLES = (   # имя файла первички → заголовок записи реестра; иначе — заголовок манифеста
    (r"(?P<y>\d{4})Q(?P<k>[1-3])_ifrs_fs\.pdf", "{issuer}: промежуточная сокращённая консолидированная отчётность по МСФО за {months} {y} года (обзорная проверка)"),
    (r"FY(?P<y>\d{4})_ifrs_fs\.pdf", "{issuer}: консолидированная финансовая отчётность по МСФО за {y} год (аудит)"),
    (r"(?P<y>\d{4})Q(?P<k>[1-4])_ifrs_press\.pdf", "{issuer}: пресс-релиз о финансовых результатах по МСФО за {k}-й квартал {y} года"),
    (r"(?P<y>\d{4})Q(?P<k>[1-4])_ifrs_presentation\.pdf", "{issuer}: презентация финансовых результатов по МСФО за {k}-й квартал {y} года"),
    (r"t-databook-.*_pub(?P<y>\d{4})-(?P<m>\d\d)-(?P<d>\d\d)\.xlsx", "{issuer}: справочник аналитика «Ключевые финансовые показатели» (Databook, XLSX), опубликован {d}.{m}.{y}"),
    (r"dividend_policy_.*\.pdf", "Дивидендная политика МКПАО «{issuer}» (редакция 2, утверждена советом директоров 20.03.2025)"),
    (r"dividend_history\.pdf", "История дивидендных выплат МКПАО «{issuer}» (файл эмитента)"),
)


def doc_title(file: str | None, manifest_title: str | None) -> str | None:
    name = Path(file).name if file else ""
    for pattern, title in DOC_TITLES:
        m = re.fullmatch(pattern, name)
        if m:
            g = m.groupdict()
            return title.format(issuer=ISSUER, months=PERIOD_WORDS.get(g.get("k", ""), ""), **g)
    t = re.sub(r";?\s*запись — MANIFEST[^;)]*", "", manifest_title or "").strip()
    return t or None


class BuildError(RuntimeError):
    """Нет листа, строки или документа; не сошлась сверка."""


# ------------------------------------------------------------------ периоды

def q_parse(p: str) -> tuple[int, int]:
    return int(p[:4]), int(p[5])


def q_range(a: str, b: str) -> list[str]:
    y, k = q_parse(a)
    out = []
    while f"{y}Q{k}" <= b:
        out.append(f"{y}Q{k}")
        y, k = (y + 1, 1) if k == 4 else (y, k + 1)
    return out


def q_end(p: str) -> dt.date:
    y, k = q_parse(p)
    return dt.date(y, 3 * k, 31 if k in (1, 4) else 30)


def q_prev(p: str) -> str:
    y, k = q_parse(p)
    return f"{y - 1}Q4" if k == 1 else f"{y}Q{k - 1}"


def q_days(p: str) -> int:
    return (q_end(p) - q_end(q_prev(p))).days


def q_of_date(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def ifrs_q(p: str) -> str:
    """2026Q2 → 2Q2026 (обозначение листов МСФО этапа 1)."""
    y, k = q_parse(p)
    return f"{k}Q{y}"


def d_ru(iso: str) -> str:
    """2026-03-31 → 31.03.2026 (даты в текстах calc)."""
    return dt.date.fromisoformat(str(iso)[:10]).strftime("%d.%m.%Y")


def d_words(iso: str) -> str:
    """2026-10-12 → 12 октября 2026 года (даты в подписях для витрины)."""
    d = dt.date.fromisoformat(str(iso)[:10])
    return f"{d.day} {MONTHS_GEN[d.month - 1]} {d.year} года"


def q_ru(p: str) -> str:
    """2026Q2 → 2К2026."""
    y, k = q_parse(p)
    return f"{k}К{y}"


@dataclass(frozen=True)
class Anchor:
    """Якорь сборки и всё, что из него выводится (перечень — data/facts/SCHEMA.md §3)."""

    period: str                            # 2026Q2

    def __post_init__(self):
        if not re.fullmatch(r"\d{4}Q[1-4]", self.period):
            raise BuildError(f"якорь {self.period!r}: нужен квартал вида ГГГГQк (год, Q, номер квартала)")

    @property
    def year(self) -> int:
        return q_parse(self.period)[0]

    @property
    def quarter(self) -> int:
        return q_parse(self.period)[1]

    @property
    def date(self) -> str:                 # конец квартала якоря
        return q_end(self.period).isoformat()

    @property
    def open_date(self) -> str:            # конец прошлого квартала — начало квартала якоря
        return q_end(q_prev(self.period)).isoformat()

    @property
    def prev_year_end(self) -> str:
        return f"{self.year - 1}-12-31"

    @property
    def ytd(self) -> str:                  # нарастающий итог якоря в листах МСФО: 6M2026; год — FY2026
        return f"FY{self.year}" if self.quarter == 4 else f"{3 * self.quarter}M{self.year}"

    @property
    def ytd_ru(self) -> str:               # то же в текстах: 6М2026; год — «2026 год»
        return f"{self.year} год" if self.quarter == 4 else f"{3 * self.quarter}М{self.year}"

    @property
    def year_quarters(self) -> list[str]:  # отчётные кварталы года якоря
        return [f"{self.year}Q{k}" for k in range(1, self.quarter + 1)]

    @property
    def anchor_sheet(self) -> str:
        return f"stage1/ifrs/ifrs_anchor_{self.period}.csv"


def default_anchor() -> str:
    """Якорь по умолчанию — квартал закоммиченных фактов (data/facts/anchor.json)."""
    path = FACTS / "anchor.json"
    if not path.exists():
        raise BuildError("нет data/facts/anchor.json — задайте якорь аргументом --anchor")
    return str(json.loads(path.read_text(encoding="utf-8"))["period"])


def ru(x: float, n: int = 1) -> str:
    """Число для текстов calc: запятая, пробел между тысячами, минус — знаком «−»."""
    s = f"{x:,.{n}f}".replace(",", " ").replace(".", ",")
    return s.replace("-", "−")


def pct(x: float, n: int = 2) -> str:
    return ru(x * 100, n) + " %"


def ru_exact(x: float) -> str:
    """Число листа для формулы calc — со всеми своими знаками (не меньше одного после запятой)."""
    n = next((k for k in range(1, 6) if abs(round(x, k) - x) < 5e-7), 6)
    return ru(x, n)


# Квартал-разность нарастающих итогов в листах МСФО: «расчёт: 6M2026 − 2Q2026 (редакция 6M2026)», «расчёт: FY2025 − 9M2025».
DIFF_NOTE = re.compile(r"расчёт:\s*(?P<a>\S+)\s*−\s*(?P<b>\S+)(?:\s*\(редакция\s+(?P<ed>[^)]+)\))?")
DIFF_WORDS = "разность нарастающих итогов"


def label_ru(label: str) -> str:
    """Период листов МСФО в текстах calc: 6M2026 → 6М2026; 2Q2026 → 2К2026; FY2025 → 2025 год; иное — как есть."""
    m = re.fullmatch(r"(\d+)M(\d{4})", label)
    if m:
        return f"{m.group(1)}М{m.group(2)}"
    m = re.fullmatch(r"([1-4])Q(\d{4})", label)
    if m:
        return f"{m.group(1)}К{m.group(2)}"
    m = re.fullmatch(r"FY(\d{4})", label)
    return f"{m.group(1)} год" if m else label


def ytd_label(p: str) -> str:
    """Нарастающий итог по квартал p в листах МСФО: 2026Q2 → 6M2026; 2025Q4 → FY2025."""
    y, k = q_parse(p)
    return f"FY{y}" if k == 4 else f"{3 * k}M{y}"


def difference(value: float, minuend: tuple[str, float | None], subtrahend: tuple[str, float | None],
               edition: str | None = None) -> str:
    """Слова calc узла-разности: периоды уменьшаемого и вычитаемого, редакция отчёта и — когда оба числа есть в
    листах и дают значение узла — сами числа (их, а не разность, печатает страница из src)."""
    (a, va), (b, vb) = minuend, subtrahend
    words = f"{DIFF_WORDS} {label_ru(a)} − {label_ru(b)}"
    eds = [label_ru(e) for e in (edition or "").split("+") if e]
    if eds:
        words += f" ({'редакция отчёта' if len(eds) == 1 else 'редакции отчётов'} за {' и '.join(eds)})"
    if va is not None and vb is not None and abs(va - vb - value) <= 5e-7:
        words += f": {ru_exact(va)} − " + (ru_exact(vb) if vb >= 0 else f"({ru_exact(vb)})")
    return words


def r6(x: float | None) -> float | None:
    return None if x is None else round(x, 6) + 0.0   # + 0.0: минус ноль не пишется


def r9(x: float | None) -> float | None:
    return None if x is None else round(x, 9) + 0.0   # точность файла отчёта квартала


def r3(x: float | None) -> float | None:
    return None if x is None else round(x, 3)


def r1(x: float | None) -> float | None:
    return None if x is None else round(x, 1)


# ------------------------------------------------------------------ документы и узлы

class Docs:
    """Реестр документов: путь в папке передачи, sha256 по файлу, заголовок и адрес — из манифестов первички."""

    HEAD = {"file": ("файл",), "title": ("что это",), "url": ("url", "адрес / запрос", "адрес"), "sha": ("sha256", "sha-256")}
    BASES = ("primary", "stage1/ras/raw", "")           # где лежат файлы, названные в манифестах

    def __init__(self, root: Path):
        self.root = root
        self.reg: dict[str, dict] = {}                  # sha256 → запись реестра
        self.keys: dict[str, str] = {}                  # ключ → sha256
        self._sha: dict[Path, str] = {}
        self.manifest = self._manifests()

    def _manifests(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for mf in sorted((self.root / "primary").glob("MANIFEST*.md")):
            cols: dict[str, int] = {}
            for line in mf.read_text(encoding="utf-8").splitlines():
                if not line.startswith("|"):
                    cols = {}
                    continue
                cells = [c.strip().strip("`").strip() for c in line.strip().strip("|").split("|")]
                low = [c.lower() for c in cells]
                if not cols:
                    cols = {k: low.index(n) for k, names in self.HEAD.items() for n in names if n in low}
                    continue
                if set(cells[0]) <= set("-: ") or "sha" not in cols or cols["sha"] >= len(cells):
                    continue
                sha = cells[cols["sha"]].strip("`").strip()
                if not re.fullmatch(r"[0-9a-f]{64}", sha) or sha in out:
                    continue
                url = cells[cols["url"]] if "url" in cols and cols["url"] < len(cells) else ""
                m = re.search(r"https?://\S+", url)
                out[sha] = {"file": cells[cols["file"]] if "file" in cols else "",
                            "title": cells[cols["title"]] if "title" in cols and cols["title"] < len(cells) else "",
                            "url": m.group(0).rstrip(").,;") if m else None, "manifest": mf.name}
        return out

    def sha_of(self, path: Path) -> str:
        if path not in self._sha:
            self._sha[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        return self._sha[path]

    def _locate(self, name: str) -> Path | None:
        for base in self.BASES:
            p = self.root / base / name if base else self.root / name
            if name and p.is_file():
                return p
        return None

    def add(self, rel: str | None = None, sha: str | None = None, *, key: str | None = None, title: str | None = None,
            url: str | None = None) -> str:
        """Регистрирует документ и возвращает первые 16 знаков sha256. rel — путь от корня папки передачи;
        без rel документ ищется по sha256 в манифестах (формы ЦБ, названные в листах адресом и хэшем)."""
        path = self._locate(rel) if rel else None
        if rel and path is None:
            raise BuildError(f"нет документа {rel} в папке передачи")
        man = self.manifest.get(sha or "", {})
        if path is None and man.get("file"):
            path = self._locate(man["file"])
        if path is not None:
            real = self.sha_of(path)
            if sha and real != sha:
                raise BuildError(f"{path.name}: sha256 файла {real[:16]}… не совпал с листом {sha[:16]}…")
            sha = real
            man = self.manifest.get(sha, man)
        if not sha:
            raise BuildError("документ без файла и без sha256")
        if sha not in self.reg:
            file = path.relative_to(self.root).as_posix() if path is not None else None
            stem = Path(file or man.get("file") or sha[:12]).stem
            k = key or re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")
            if k in self.keys and self.keys[k] != sha:
                k = f"{k}_{sha[:6]}"
            self.keys[k] = sha
            self.reg[sha] = {"key": k, "file": file, "sha256": sha, "url": url or man.get("url"),
                             "title": title or doc_title(file, man.get("title")) or (Path(file).name if file else k)}
        return sha[:16]

    def name(self, sha16: str) -> str:
        for sha, d in self.reg.items():
            if sha.startswith(sha16):
                return Path(d["file"]).name if d["file"] else d["key"]
        raise BuildError(f"документ {sha16} не в реестре")

    def ref(self, rel: str | None, where: str = "", sha: str | None = None, **kw) -> str:
        s16 = self.add(rel, sha, **kw)
        return ", ".join(x for x in (self.name(s16), where, f"sha256 {s16}") if x)

    def documents(self) -> list[dict]:
        return sorted(self.reg.values(), key=lambda r: (r["key"], r["sha256"]))


def dedup(src: str | None) -> str | None:
    """Источник без повторов: части через «; » — каждая один раз, порядок сохранён."""
    if not src:
        return src
    seen, out = set(), []
    for part in src.split("; "):
        if part and part not in seen:
            seen.add(part)
            out.append(part)
    return "; ".join(out)


def node(v, src: str | None = None, calc: str | None = None, **extra) -> dict:
    """Узел факта. Число без источника и без формулы — ошибка сборки."""
    if v is None:
        raise BuildError(f"узел без значения: используйте na(причина) ({src or calc})")
    if not (src or calc):
        raise BuildError(f"число {v} без src и calc")
    out = {"v": v}
    if src:
        out["src"] = dedup(src)
    if calc:
        out["calc"] = calc
    out.update(extra)
    return out


def na(reason: str, **extra) -> dict:
    """Нераскрытое: null с причиной (не ноль)."""
    return {"v": None, "calc": reason, **extra}


def page_words(page: str) -> str:
    """«6» → «с. 6»; «22, 84» → «с. 22, 84»; адрес «Лист!Ячейка» и слова — как есть."""
    page = (page or "").strip()
    return f"с. {page}" if re.fullmatch(r"\d[\d\s,;–-]*", page) else page


def put(obj: dict, dotted: str, value) -> None:
    *head, last = dotted.split(".")
    for part in head:
        obj = obj.setdefault(part, {})
    obj[last] = value


def dig(obj, dotted: str):
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(dotted)
        cur = cur[part]
    return cur


# ------------------------------------------------------------------ листы этапа 1

def read_csv(path: Path, *, comment: bool = False) -> list[dict]:
    if not path.exists():
        raise BuildError(f"нет листа {path.name} ({path.parent.name}/)")
    with open(path, encoding="utf-8-sig", newline="") as f:
        lines = [ln for ln in f if not (comment and ln.startswith("#"))]
    return list(csv.DictReader(lines))


class Sheet:
    """Лист этапа 1 формата «metric, period, value, unit, basis, doc, page, sha256, note»."""

    def __init__(self, root: Path, rel: str, docs: Docs):
        self.rel, self.docs = rel, docs
        self.rows: dict[tuple[str, str], dict] = {}
        for r in read_csv(root / rel):
            self.rows.setdefault((r["metric"], r["period"]), r)

    def has(self, metric: str, period: str) -> bool:
        return self.get(metric, period) is not None

    def get(self, metric: str, period: str) -> float | None:
        r = self.rows.get((metric, period))
        try:
            return None if r is None else float(r["value"])
        except ValueError:
            return None

    def need(self, metric: str, period: str) -> float:
        v = self.get(metric, period)
        if v is None:
            raise BuildError(f"{self.rel}: нет строки {metric} за {period}")
        return v

    def note(self, metric: str, period: str) -> str:
        return (self.rows.get((metric, period)) or {}).get("note", "")

    def src(self, metric: str, period: str) -> str:
        r = self.rows.get((metric, period))
        if r is None:
            raise BuildError(f"{self.rel}: нет строки {metric} за {period}")
        names = [d.strip() for d in r["doc"].split("|")]
        shas = [s.strip() for s in r["sha256"].split("|")]
        pages = [p.strip() for p in r["page"].split("|")]
        if len(shas) != len(names):
            raise BuildError(f"{self.rel}: {metric} {period}: число документов и sha256 не совпало")
        if len(pages) != len(names):
            pages = [r["page"].strip()] + [""] * (len(names) - 1)
        return "; ".join(self.docs.ref(n, page_words(p), s) for n, p, s in zip(names, pages, shas))

    def n(self, metric: str, period: str, *, scale: float = 1.0, calc: str | None = None, digits: int = 6, **extra) -> dict:
        return node(round(self.need(metric, period) * scale, digits), self.src(metric, period), calc, **extra)


class Ctx:
    """Листы этапа 1, реестр документов и журнал сверок одной сборки."""

    def __init__(self, root: Path, anchor: Anchor):
        self.root, self.a = root, anchor
        self.docs = Docs(root)
        self.checks: list[tuple[str, bool, str]] = []
        if not (root / anchor.anchor_sheet).exists():
            raise BuildError(f"нет листа якоря {anchor.anchor_sheet}: квартал {anchor.period} в папке передачи не собран")
        self.anchor_sheet = Sheet(root, anchor.anchor_sheet, self.docs)
        self.history = Sheet(root, "stage1/ifrs/ifrs_history.csv", self.docs)
        self.quarterly = Sheet(root, "stage1/ifrs/ifrs_quarterly.csv", self.docs)
        self.notes = Sheet(root, "stage1/ifrs/ifrs_notes.csv", self.docs)
        self.block = Sheet(root, BLOCK["sheet"], self.docs)
        self.mgmt = Sheet(root, MGMT_SHEET, self.docs)
        self.titles = {r["metric"]: r["description_ru"] for r in read_csv(root / "stage1/ifrs/metrics.csv")}
        self._key: dict[str, float] | None = None

    def check(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append((name, bool(ok), detail))

    def csv(self, rel: str, **kw) -> list[dict]:
        return read_csv(self.root / rel, **kw)

    def sheet_ref(self, rel: str, what: str, *, title: str, key: str | None = None) -> str:
        """Ссылка на лист этапа 1 как на документ реестра (у листа нет своих sha256 по строкам)."""
        s16 = self.docs.add(rel, key=key or "sheet_" + Path(rel).stem, title=title)
        return f"{rel}, {what}, sha256 {s16}"

    # --- остатки: главный ряд (последняя редакция, точные числа), затем лист якоря (строки только якоря)
    def _bal_sheet(self, metric: str, date: str) -> Sheet:
        if self.history.has(metric, date):
            return self.history
        if self.anchor_sheet.has(metric, date):
            return self.anchor_sheet
        raise BuildError(f"нет остатка {metric} на {date} ни в листе якоря, ни в главном ряду МСФО")

    def bal(self, metric: str, date: str) -> float:
        return self._bal_sheet(metric, date).need(metric, date)

    def has_bal(self, metric: str, date: str) -> bool:
        return self.anchor_sheet.has(metric, date) or self.history.has(metric, date)

    def bal_src(self, metric: str, date: str) -> str:
        return self._bal_sheet(metric, date).src(metric, date)

    # --- потоки за квартал и нарастающим итогом
    def flow(self, metric: str, period: str) -> float:
        return self.quarterly.need(metric, ifrs_q(period))

    def has_flow(self, metric: str, period: str) -> bool:
        return self.quarterly.has(metric, ifrs_q(period))

    def flow_src(self, metric: str, period: str) -> str:
        return self.quarterly.src(metric, ifrs_q(period))

    def ytd(self, metric: str, label: str) -> tuple[float, str]:
        sh = self.history if self.history.has(metric, label) else self.anchor_sheet
        return sh.need(metric, label), sh.src(metric, label)

    def title(self, metric: str) -> str:
        t = (self.titles.get(metric) or metric).strip()
        return t[:1].lower() + t[1:] if len(t) > 1 and t[1].islower() else t

    def lines(self, lines: tuple[str, ...], when: str, *, flow: bool = False) -> tuple[float, str, str]:
        """Сумма строк отчёта: (значение, источник, формула словами). «-имя» — строка вычитается."""
        total, srcs, words = 0.0, [], []
        for ln in lines:
            sign, m = (-1.0, ln[1:]) if ln.startswith("-") else (1.0, ln)
            v = self.flow(m, when) if flow else self.bal(m, when)
            total += sign * v
            srcs.append(self.flow_src(m, when) if flow else self.bal_src(m, when))
            words.append(("− " if sign < 0 else "+ " if words else "") + f"{self.title(m)} {ru(v)}")
        return round(total, 6), dedup("; ".join(srcs)), " ".join(words)

    # --- кварталы-разности нарастающих итогов (1К = 6М − 2К, 4К = год − 9М): страница из src печатает слагаемые
    def operand(self, metric: str, label: str) -> float | None:
        """Значение строки за период листов МСФО: квартал — из квартального листа, нарастающий итог — из главного
        ряда или листа якоря; нет строки — None."""
        for sh in (self.quarterly, self.history, self.anchor_sheet):
            if sh.has(metric, label):
                return sh.get(metric, label)
        return None

    def flow_calc(self, metric: str, period: str, *, numbers: bool = True) -> str | None:
        """Формула квартала-разности по пометке «расчёт: …» квартального листа; прямая строка отчёта — None."""
        parts = [x.strip() for x in self.quarterly.note(metric, ifrs_q(period)).split(";")]
        if not parts[0].startswith("расчёт"):
            return None
        m = DIFF_NOTE.fullmatch(parts[0])
        if not m:
            raise BuildError(f"{self.quarterly.rel}: {metric} {period}: пометка расчёта не разобрана — «{parts[0]}»")
        a, b = m.group("a"), m.group("b")
        edition = next((x.split(None, 1)[1] for x in parts[1:] if x.startswith("редакция ")), m.group("ed"))
        va, vb = (self.operand(metric, a), self.operand(metric, b)) if numbers else (None, None)
        return difference(self.flow(metric, period), (a, va), (b, vb), edition)

    def flows_calc(self, lines: tuple[str, ...], period: str) -> str | None:
        """То же для строк потока узла: одна строка — формула с числами; сумма строк — формула слагаемых."""
        names = [ln.lstrip("-") for ln in lines]
        if len(names) == 1:
            return self.flow_calc(names[0], period)
        found = {m: f for m in names for f in [self.flow_calc(m, period, numbers=False)] if f}
        if not found:
            return None
        if len(found) == len(names) and len(set(found.values())) == 1:
            return "каждое слагаемое — " + next(iter(found.values()))
        return "слагаемые-разности: " + ", ".join(f"{self.title(m)} — {f}" for m, f in found.items())

    def lines_node(self, lines: tuple[str, ...], when: str, *, flow: bool = False, magnitude: bool = False,
                   note: str | None = None) -> dict:
        v, src, words = self.lines(lines, when, flow=flow)
        calc = words if len(lines) > 1 else None
        if flow:
            calc = "; ".join(x for x in (calc, self.flows_calc(lines, when)) if x) or None
        if magnitude:
            v, calc = abs(v), "; ".join(x for x in (calc, "величиной (в отчёте — со знаком минус)") if x)
        if note:
            calc = "; ".join(x for x in (calc, note) if x)
        return node(v, src, calc)

    # --- ключевая ставка
    def key_avg(self, period: str) -> float:
        if self._key is None:
            self._key = {r["period"]: float(r["key_avg_pct"]) / 100 for r in self.csv(KEY_RATE_SHEET) if r["key_avg_pct"]}
        if period not in self._key:
            raise BuildError(f"{KEY_RATE_SHEET}: нет средней ключевой ставки за {period}")
        return round(self._key[period], 6)

    def key_ref(self) -> str:
        return self.sheet_ref(KEY_RATE_SHEET, "средняя ключевая ставка Банка России за квартал по календарным дням",
                              title="Ключевая ставка Банка России по кварталам (средняя по календарным дням и на "
                                    "конец квартала; веб-сервис Банка России)", key="cbr_key_rate_quarterly")


def books_of(side: str | None = None, *, loans: bool = False) -> list[str]:
    """Книги таблицы 1: по стороне баланса; loans — только кредитные (актив вне балансирующих ролей)."""
    out = [b for b, s in BOOKS.items() if side is None or s["side"] == side]
    return [b for b in out if BOOKS[b]["side"] == "asset" and b not in (SECURITIES, LIQUIDITY)] if loans else out


def book_words(names: list[str]) -> str:
    return ", ".join(f"«{BOOKS[b]['name']}»" for b in names)


# ------------------------------------------------------------------ anchor.json

def build_anchor(c: Ctx) -> dict:
    return {
        "basis": "IFRS",
        "as_of": c.a.date,
        "period": c.a.period,
        "note": f"якорь — последний отчётный квартал МСФО группы (отчётность за {c.a.ytd_ru}); documents — реестр всех "
                "документов, на которые ссылаются узлы фактов (sha256 полностью; в src — первые 16 знаков); "
                "file — путь в папке передачи (BANK_HANDOFF_DIR); источник строки — страница документа или адрес "
                "«Лист!Ячейка» справочника аналитика эмитента",
        "documents": c.docs.documents(),
    }


# ------------------------------------------------------------------ balance.json

def dividends_payable(c: Ctx) -> dict:
    """Дивиденды к выплате на якоре: строка отчёта, а на промежуточную дату — расчёт по движению с начала года."""
    a, m = c.a, DIVIDENDS_PAYABLE
    if c.has_bal(m["balance"], a.date):
        return node(c.bal(m["balance"], a.date), c.bal_src(m["balance"], a.date), "строка отчёта; внутри прочих обязательств")
    opened = c.bal(m["balance"], a.prev_year_end)
    declared, s_decl = c.ytd(m["declared"], a.ytd)
    paid, s_paid = c.ytd(m["paid"], a.ytd)
    exact = opened - declared + paid                   # declared и paid в отчёте — со знаком минус
    return node(r1(exact), "; ".join((c.bal_src(m["balance"], a.prev_year_end), s_decl, s_paid)),
                f"к выплате на {d_ru(a.prev_year_end)} {ru(opened, 3)} + объявлено за {a.ytd_ru} {ru(-declared)} − выплачено "
                f"за {a.ytd_ru} {ru(-paid)} = {ru(exact, 3)}; до 0,1 — точности слагаемых; строка на {d_ru(a.date)} в отчёте "
                "не раскрыта (внутри прочих обязательств)")


def declared_unpaid(c: Ctx, payable: float, n_out: float) -> list[dict]:
    """Объявленные до якоря и не выплаченные к нему дивиденды закрытых кварталов прибыли (часть остатка
    «дивиденды к выплате»): решение не позже якоря, срок выплаты номинальным держателям — после него."""
    out = []
    for r in dividend_rows(c):
        if r["decided_date"] <= c.a.date < r["pay_deadline_nominee"]:
            amount = round(float(r["dps"]) * n_out / 1000, 3)
            out.append({"period": dividend_period(r), "amount": node(
                amount, dividends_ref(c, f"решение {d_ru(r['decided_date'])}, срок выплаты {d_ru(r['pay_deadline_nominee'])}"),
                f"{ru(float(r['dps']), 2)} ₽ × акции в обращении {ru(n_out, 3)} млн / 1000")})
    total = sum(x["amount"]["v"] for x in out)
    if total > payable + 1e-9:
        raise BuildError(f"объявленные и не выплаченные дивиденды {total} больше остатка к выплате {payable}")
    return out


def history_row(c: Ctx, p: str) -> dict:
    """Конец квартала истории: капитал акционеров, кредитные книги, средства клиентов, процентные активы, активы."""
    d = q_end(p).isoformat()
    loans = [c.lines(BOOKS[b]["balance"], d) for b in books_of(loans=True)]
    funds = [c.lines(BOOKS[b]["balance"], d) for b in (RETAIL_CURRENT, RETAIL_TERM, "corp_funds")]
    liq = c.lines(BOOKS[LIQUIDITY]["balance"], d)
    v_loans, v_funds = round(sum(x[0] for x in loans), 6), round(sum(x[0] for x in funds), 6)
    exact = p >= DEBT_SECURITIES_FROM
    sec = c.lines(BOOKS[SECURITIES]["balance"], d) if exact else c.lines((SECURITIES_BROAD,), d)
    fv = c.bal("loans_fvtpl", d)
    return {
        "date": d,
        "bv_common": node(c.bal(EQUITY["bv_common"], d), c.bal_src(EQUITY["bv_common"], d)),
        "loans": node(v_loans, dedup("; ".join(x[1] for x in loans)),
                      "сумма шести кредитных книг: " + " + ".join(f"{BOOKS[b]['name']} {ru(x[0])}"
                                                                   for b, x in zip(books_of(loans=True), loans))),
        "loans_ac_gross": node(v_loans, calc=f"= loans: отдельной книги кредитов по справедливой стоимости нет (они, {ru(fv)}, "
                                              "лежат в корпоративной книге)"),
        "loans_fvtpl": node(fv, c.bal_src("loans_fvtpl", d), "справочно: кредиты по справедливой стоимости внутри корпоративной книги"),
        "funds": node(v_funds, dedup("; ".join(x[1] for x in funds)),
                      "средства клиентов: текущие счета и срочные вклады физлиц + средства бизнеса = "
                      + " + ".join(ru(x[0]) for x in funds)),
        "iea": node(round(v_loans + sec[0] + liq[0], 6), dedup("; ".join((sec[1], liq[1]))),
                    f"кредитные книги {ru(v_loans)} + " + ("долговые бумаги " if exact else "бумаги с акциями и паями (без "
                    "пакета Яндекса) — долговые отдельно на эту дату не раскрыты — ") + f"{ru(sec[0])} + ликвидность {ru(liq[0])}"),
        "total_assets": node(c.bal(TOTAL_ASSETS, d), c.bal_src(TOTAL_ASSETS, d)),
    }


def build_balance(c: Ctx) -> dict:
    a, d = c.a, c.a.date
    out: dict = {"basis": "IFRS", "as_of": d, "unit": "млрд ₽",
                 "note": "остатки книг — прямыми узлами books (состав книги — в calc); прочие узлы раскладывают книги "
                         "на строки отчёта или несут справку; other_assets и other_liabilities — остатком до итогов баланса"}
    books, val = {}, {}
    for b, spec in BOOKS.items():
        v, src, words = c.lines(spec["balance"], d)
        books[b] = node(v, src, words if len(spec["balance"]) > 1 else None)
        val[b] = v
    out["books"] = books
    for b, spec in BOOKS.items():
        covered = 0.0
        for path, lines in (spec.get("nodes") or {}).items():
            n = c.lines_node(lines, d)
            put(out, path, n)
            covered += n["v"]
        if spec.get("nodes") and {ln for ls in spec["nodes"].values() for ln in ls} == set(spec["balance"]):
            c.check(f"книга «{spec['name']}» = сумме своих строк баланса", abs(covered - val[b]) < 1e-6,
                    f"{ru(covered)} против {ru(val[b])}")
    allowance, a_src, a_words = c.lines(ALLOWANCE, d)
    out["allowance_ac"] = node(round(-allowance, 6), a_src, f"{a_words}; величиной (в отчёте — со знаком минус)")
    rr = [m for m in REVERSE_REPO if c.has_bal(m, d)]
    out.setdefault("liquidity", {})["reverse_repo"] = na(
        "отдельной строки баланса нет: обратное репо" + (f" {ru(sum(c.bal(m, d) for m in rr))}" if rr else "")
        + " — внутри денежных средств и средств в других банках")

    assets, liabs = books_of("asset"), books_of("liability")
    total_a, total_l = c.bal(TOTAL_ASSETS, d), c.bal(TOTAL_LIABILITIES, d)
    sum_a, sum_l = sum(val[b] for b in assets), sum(val[b] for b in liabs)
    parts_a = {k: c.lines_node(s["lines"], d, note=s["title"]) for k, s in OTHER_ASSETS.items()}
    parts_l = {k: c.lines_node(s["lines"], d, note=s["title"]) for k, s in OTHER_LIABILITIES.items()}
    for spec, parts in ((OTHER_ASSETS, parts_a), (OTHER_LIABILITIES, parts_l)):
        for k, s in spec.items():
            if s.get("reference"):
                put(out, s["reference"], parts[k])
    other_a = round(total_a - sum_a - allowance, 6)
    bottom_a = sum(n["v"] for n in parts_a.values())
    c.check("баланс якоря: Σ книг активов − резерв + прочие активы = активы",
            abs(sum_a + allowance + bottom_a - total_a) <= 0.35,
            f"{ru(sum_a)} − {ru(-allowance)} + {ru(bottom_a)} (строки прочих активов) = {ru(sum_a + allowance + bottom_a)} "
            f"против {ru(total_a)}")
    fixed = {k: parts_a[k] for k, s in OTHER_ASSETS.items() if s.get("fixed")}
    out["other_assets"] = node(other_a, calc=f"активы {ru(total_a)} − книги активов {ru(sum_a)} + резерв {ru(-allowance)}; "
                                              f"по строкам отчёта — {ru(bottom_a)} (other_assets_parts)")
    out["other_assets_fixed"] = node(round(sum(n["v"] for n in fixed.values()), 6),
                                     calc="постоянные прочие активы (не растут с кредитами): "
                                          + " + ".join(f"{OTHER_ASSETS[k]['title']} {ru(n['v'])}" for k, n in fixed.items()))
    out["other_assets_fixed_parts"] = fixed
    out["other_assets_parts"] = parts_a
    out["total_assets"] = node(total_a, c.bal_src(TOTAL_ASSETS, d))
    out["total_liabilities"] = node(total_l, c.bal_src(TOTAL_LIABILITIES, d))

    payable = dividends_payable(c)
    other_l = round(total_l - sum_l - payable["v"], 6)
    bottom_l = sum(n["v"] for n in parts_l.values())
    c.check("баланс якоря: Σ книг пассивов + прочие обязательства = обязательства",
            abs(sum_l + bottom_l - total_l) <= 0.35,
            f"{ru(sum_l)} + {ru(bottom_l)} (строки прочих обязательств, с дивидендами к выплате) = {ru(sum_l + bottom_l)} "
            f"против {ru(total_l)}")
    out["other_liabilities"] = node(other_l, calc=f"обязательства {ru(total_l)} − книги пассивов {ru(sum_l)} − дивиденды к "
                                                   f"выплате {ru(payable['v'])}; по строкам отчёта — {ru(bottom_l)} с "
                                                   "дивидендами к выплате (other_liabilities_parts)")
    out["other_liabilities_parts"] = parts_l
    out["dividends_payable"] = payable

    eq = {k: node(c.bal(m, d), c.bal_src(m, d)) for k, m in EQUITY.items()}
    sub = out["wholesale"]["perpetual_sub"]["v"]
    eq["at1"] = node(0.0, calc=f"бессрочных инструментов в капитале МСФО нет: бессрочные субординированные займы {ru(sub)} — "
                               "обязательство (книга оптового фондирования), проценты по ним — в процентных расходах")
    out["equity"] = {k: eq[k] for k in ("total", "at1", "nci", "bv_common") + EQUITY_PARTS}
    bv, nci, total_e = eq["bv_common"]["v"], eq["nci"]["v"], eq["total"]["v"]
    c.check("капитал: компоненты = капитал акционеров; + неконтролирующая доля = весь капитал",
            abs(sum(eq[k]["v"] for k in EQUITY_PARTS) - bv) <= 0.25 and abs(bv + nci - total_e) <= 0.15,
            f"{ru(sum(eq[k]['v'] for k in EQUITY_PARTS))} против {ru(bv)}; {ru(bv + nci)} против {ru(total_e)}")
    c.check("баланс якоря: обязательства + капитал = активы", abs(total_l + total_e - total_a) <= 0.15,
            f"{ru(total_l)} + {ru(total_e)} = {ru(total_l + total_e)} против {ru(total_a)}")

    n_out = shares_at(c, a.date)[2]
    out["dividends_payable_declared"] = declared_unpaid(c, payable["v"], n_out)

    prev = {}
    for seg in ("corporate", "retail"):
        names = [b for b in books_of(loans=True) if BOOKS[b]["segment"] == seg]
        rows = [c.lines(BOOKS[b]["balance"], a.prev_year_end) for b in names]
        prev[f"loans_{seg}"] = node(round(sum(x[0] for x in rows), 6), dedup("; ".join(x[1] for x in rows)),
                                    f"кредитные книги сегмента на {d_ru(a.prev_year_end)}: "
                                    + " + ".join(f"{BOOKS[b]['name']} {ru(x[0])}" for b, x in zip(names, rows)))
    out["prev_year_end"] = {"as_of": a.prev_year_end, **prev}
    loans_now = sum(val[b] for b in books_of(loans=True))
    out["iea"] = node(round(sum_a, 6), calc=f"процентные активы движка: кредитные книги {ru(loans_now)} + долговые бумаги "
                                            f"{ru(val[SECURITIES])} + ликвидность {ru(val[LIQUIDITY])}")
    out["history"] = {p: history_row(c, p) for p in q_range(HISTORY_FIRST, a.period)}
    h = out["history"][a.period]
    c.check("история баланса: строка якоря = узлам якоря",
            abs(h["loans"]["v"] - loans_now) < 1e-6 and abs(h["iea"]["v"] - sum_a) < 1e-6 and h["bv_common"]["v"] == bv,
            f"кредиты {ru(h['loans']['v'])}, процентные активы {ru(h['iea']['v'])}, капитал акционеров {ru(h['bv_common']['v'])}")
    return out


# ------------------------------------------------------------------ nii_books.json

def build_nii_books(c: Ctx, bal: dict) -> dict:
    a, p = c.a, c.a.period
    days = q_days(p)
    sheet = {r["book"]: r for r in c.csv(BOOKS_SHEET)}
    books, drift = {}, []
    raw: dict[str, tuple[float, float]] = {}           # книга → (проценты квартала, средний остаток) без округления
    for b, spec in BOOKS.items():
        open_v, open_src, _ = c.lines(spec["balance"], a.open_date)
        close_v = bal["books"][b]["v"]
        avg = (open_v + close_v) / 2
        i_v, i_src, i_words = c.lines(spec["interest"], p, flow=True)
        interest = abs(i_v)
        rate = interest / avg * 365 / days
        liability = spec["side"] == "liability"
        books[b] = {
            "balance_open": node(open_v, open_src, f"остаток книги на {d_ru(a.open_date)}"),
            "balance_close": node(close_v, calc=f"остаток книги на {d_ru(a.date)} (balance.books.{b})"),
            "balance_avg": node(r6(avg), calc="(balance_open + balance_close) / 2"),
            "interest_q": node(r6(interest), i_src, "; ".join(x for x in (
                i_words if len(spec["interest"]) > 1 else None, c.flows_calc(spec["interest"], p),
                "величиной (в отчёте — со знаком минус)" if liability else None) if x) or None),
            "rate_anchor": node(r6(rate), calc=f"interest_q / balance_avg × 365/{days} (доля, act/365)"),
        }
        raw[b] = (interest, avg)
        row = sheet.get(b)
        if row is None:
            drift.append(f"{b}: книги нет в листе книг")
            continue
        for col, mine, tol in ((f"bal_{a.open_date}", open_v, 0.051), (f"bal_{a.date}", close_v, 0.051),
                               (f"interest_{ifrs_q(p)}", i_v, 0.051), (f"rate_{ifrs_q(p)}_act365_pct", rate * 100, 0.0006)):
            if row.get(col) in (None, ""):
                drift.append(f"{b}: в листе книг нет графы {col}")
            elif abs(float(row[col]) - mine) > tol:
                drift.append(f"{b}.{col}: таблица {mine:.4f}, лист {row[col]}")
    c.check("состав книг (таблица 1) = листу книг этапа 1: остатки на две даты, проценты и ставки",
            not drift, "; ".join(drift) or f"12 книг сошлись с {BOOKS_SHEET}")
    inc = sum(books[b]["interest_q"]["v"] for b in books_of("asset"))
    exp = sum(books[b]["interest_q"]["v"] for b in books_of("liability"))
    outside = {k: c.lines(ls, p, flow=True) for k, ls in INTEREST_OUTSIDE.items()}
    other = round(sum(x[0] for x in outside.values()), 6)
    dia = abs(c.flow(DIA_LINE, p))
    nii = c.flow(NII_LINE, p)
    c.check("проценты книг − страхование вкладов + проценты вне книг = ЧПД квартала якоря",
            abs(inc - exp - dia + other - nii) <= 0.15,
            f"{ru(inc)} − {ru(exp)} − {ru(dia)} + {ru(other)} = {ru(inc - exp - dia + other)} против {ru(nii)}")
    pos = sum(x[0] for x in outside.values() if x[0] > 0)
    neg = -sum(x[0] for x in outside.values() if x[0] < 0)
    c.check("проценты книг и вне книг = процентная выручка и процентные расходы отчёта",
            abs(inc + pos - c.flow(INTEREST_REVENUE, p)) <= 0.15 and abs(exp + neg + c.flow(INTEREST_EXPENSE, p)) <= 0.15,
            f"выручка {ru(inc + pos)} против {ru(c.flow(INTEREST_REVENUE, p))}; расходы {ru(exp + neg)} против "
            f"{ru(-c.flow(INTEREST_EXPENSE, p))}")
    iea_avg = sum(books[b]["balance_avg"]["v"] for b in books_of("asset"))
    rc, rt = bal["books"][RETAIL_CURRENT]["v"], bal["books"][RETAIL_TERM]["v"]
    carry = p >= RATES_CARRY_FROM
    if carry:                                          # ставки якоря несут весь ЧПД: остаток — по книгам активов
        residual, scale = carry_scale({b: x[0] for b, x in raw.items()}, nii, dia)
        for b in books_of("asset"):
            interest, avg = raw[b]
            books[b]["rate_anchor"] = node(
                r6(interest * scale / avg * 365 / days),
                calc=f"interest_q × (1 + остаток ЧПД {ru(residual, 3)} / Σ процентов книг активов {ru(inc)}) / balance_avg × "
                     f"365/{days}: ставка книги активов несёт долю процентов вне книг (правило перезаякоривания)")
    return {
        "basis": "IFRS", "as_of": a.date, "period": p,
        "days": node(days, calc=f"дней в квартале {q_ru(p)} (act/365)"),
        "unit": "остатки и проценты — млрд ₽; ставки — доли, годовые, act/365",
        "rates_carry_residual": carry,
        "books": books,
        "interest_assets_q": node(r6(inc), calc="Σ interest_q книг активов"),
        "interest_liabilities_q": node(r6(exp), calc="Σ interest_q книг пассивов (величиной)"),
        "other_interest_net_q": node(other, dedup("; ".join(x[1] for x in outside.values())),
                                     ("проценты вне книг (остаются в ЧПД; разнесены по ставкам книг активов): " if carry else
                                      "проценты вне книг (остаются в ЧПД, в ставки книг не входят): ")
                                     + "; ".join(f"{k} {ru(x[0])}" for k, x in outside.items())
                                     + "".join(f"; {k}: {f}" for k, ls in INTEREST_OUTSIDE.items()
                                               for f in [c.flows_calc(ls, p)] if f)),
        "dia_q": node(dia, c.flow_src(DIA_LINE, p), "; ".join(x for x in (
            "расходы на страхование вкладов за квартал, величиной", c.flow_calc(DIA_LINE, p)) if x)),
        "nii_q": node(nii, c.flow_src(NII_LINE, p), c.flow_calc(NII_LINE, p)),
        "iea_avg": node(r6(iea_avg), calc="Σ balance_avg книг активов (кредитные книги, долговые бумаги, ликвидность)"),
        "nim_eng_q": node(r6(nii * 365 / days / iea_avg), calc=f"nii_q × 365/{days} / iea_avg (ЧПМ базиса движка)"),
        "current_share_anchor": node(r6(rc / (rc + rt)), calc="текущие счета физлиц / (текущие счета + срочные вклады физлиц) на якоре"),
        "key_avg_anchor_q": node(c.key_avg(p), c.key_ref()),
    }


def carry_scale(interest: dict[str, float], nii: float, dia: float) -> tuple[float, float]:
    """(остаток ЧПД вне книг, множитель ставок книг активов). Ставки якоря несут весь ЧПД: остаток
    `nii − (Σ процентов книг активов − Σ процентов книг пассивов − страхование вкладов)` разнесён по книгам активов
    пропорционально их процентному доходу (docs/MODEL.md §15.2 п. 4; то же правило — в ops/tools/reanchor.py)."""
    income = sum(interest[b] for b in books_of("asset"))
    residual = nii - (income - sum(interest[b] for b in books_of("liability")) - dia)
    return residual, 1.0 + residual / income


# ------------------------------------------------------------------ pnl_quarterly.json

def block_of(adj_stake_sh: float, adj_interest_sh: float, reval: float, dividends: float, share: float,
             shield: float) -> dict[str, float]:
    """Блок пакета из двух поправок эмитента (после налога, доля акционеров) и строк примечаний (до налога, 100 %).
    Проценты по долгу под пакет целиком отнесены на акционеров: до налога = поправка / (1 − щит). Неконтролирующая
    доля несёт только эффект пакета: поправка × (1 − доля группы) / доля группы."""
    debt = adj_interest_sh / (1 - shield)
    nci = adj_stake_sh * (1 - share) / share
    ni_sh = adj_stake_sh + adj_interest_sh
    ni = ni_sh + nci
    pbt = reval + dividends + debt
    return {"debt_interest": debt, "pbt": pbt, "tax": ni - pbt, "ni": ni, "nci": nci, "ni_shareholders": ni_sh}


def block_dividends(c: Ctx) -> dict[str, tuple[float, str, str]]:
    """Дивиденды по пакету по кварталам: (значение, источник, записка) — лист входов калибровки ОПУ."""
    out = {}
    for r in c.csv(BLOCK["dividends_sheet"]):
        k = r["period"]
        out[f"{k[2:]}Q{k[0]}"] = (float(r["value"]), c.docs.ref(r["doc"], page_words(r["page"])), r.get("note", ""))
    return out


def reval_calc(c: Ctx, p: str, value: float) -> str | None:
    """Формула переоценки пакета за квартал, которого примечание отдельно не печатает, — разность накопленных
    переоценок главного ряда. Квартал — разность, когда строка листа ссылается на два отчёта («по квартал − по
    прошлый квартал») либо на отчёт следующего квартала («по следующий квартал − следующий квартал»); строка из
    отчёта своего квартала напечатана прямо — None. Слагаемых нет в листах или они не дают значение — тоже None."""
    b = BLOCK
    y, k = q_parse(p)
    nxt = f"{y}Q{k + 1}" if k < 4 else None
    doc = lambda q: (c.block.rows.get((b["reval"], ifrs_q(q))) or {}).get("doc", "")   # noqa: E731
    pairs = []
    if k > 1 and "|" in doc(p):
        pairs.append(((ytd_label(p), c.operand(b["reval_ytd"], ytd_label(p))),
                      (ytd_label(q_prev(p)), c.operand(b["reval_ytd"], ytd_label(q_prev(p))))))
    if nxt and doc(p) and doc(p) == doc(nxt):
        pairs.append(((ytd_label(nxt), c.operand(b["reval_ytd"], ytd_label(nxt))),
                      (ifrs_q(nxt), c.block.get(b["reval"], ifrs_q(nxt)))))
    for (a, va), (s, vs) in pairs:
        if va is not None and vs is not None and abs(va - vs - value) <= 5e-7:
            return difference(value, (a, va), (s, vs))
    return None


def build_pnl(c: Ctx) -> dict:
    a, b = c.a, BLOCK
    share = c.notes.need(*b["group_share_metric"]) / 100
    share_src = c.notes.src(*b["group_share_metric"])
    shield = b["tax_shield"]
    divs = block_dividends(c)
    key_ref = c.key_ref()
    quarters, gaps, over, prev_interest = {}, [], [], None
    for p in q_range(PNL_FIRST, a.period):
        k = ifrs_q(p)
        row = {name: c.lines_node(lines, p, flow=True) for name, lines in PNL_LINES.items()}
        rep = {x: c.quarterly.n(m, k, calc=c.flow_calc(m, p)) for x, m in PNL_REPORTED.items()}
        exact = c.has_flow(PNL_OPERATING_NI, p)
        est = {} if exact else {"estimated": True}
        if exact:
            op = node(c.flow(PNL_OPERATING_NI, p), c.flow_src(PNL_OPERATING_NI, p),
                      "операционная прибыль акционеров — строка эмитента (отчётная прибыль акционеров без эффекта "
                      f"пакета и процентов по займам под него)")
        elif c.has_flow(PNL_OPERATING_NI + "_press", p):
            op = node(c.flow(PNL_OPERATING_NI + "_press", p), c.flow_src(PNL_OPERATING_NI + "_press", p),
                      "; ".join(x for x in (
                          "напечатанное значение пресс-релиза: точная строка эмитента выходит со справочником аналитика "
                          "примерно через месяц после отчёта", c.flow_calc(PNL_OPERATING_NI + "_press", p)) if x),
                      estimated=True)
        else:
            raise BuildError(f"нет операционной прибыли акционеров за {p}: ни строки эмитента, ни значения пресс-релиза")
        has_block = c.block.has(b["reval"], k) or c.block.has(b["adj_stake_sh"], k)
        if has_block:
            if p not in divs:
                raise BuildError(f"{b['dividends_sheet']}: нет дивидендов по пакету за {k} (ноль — строкой)")
            reval, div = c.block.need(b["reval"], k), divs[p][0]
            if exact:
                y_sh, i_sh = c.block.need(b["adj_stake_sh"], k), c.block.need(b["adj_interest_sh"], k)
                y_node = c.block.n(b["adj_stake_sh"], k, calc=f"поправка эмитента: эффект пакета после налога, доля акционеров")
                i_node = c.block.n(b["adj_interest_sh"], k, calc="поправка эмитента: проценты по займам под пакет после налога, доля акционеров")
            else:                                      # оценка до выхода справочника аналитика
                if prev_interest is None:
                    raise BuildError(f"оценка блока пакета за {p}: нет поправки на проценты прошлого квартала")
                i_sh = prev_interest
                y_sh = rep["ni_shareholders"]["v"] - op["v"] - i_sh
                i_node = node(r6(i_sh), calc="оценка: поправка эмитента прошлого квартала", estimated=True)
                y_node = node(r6(y_sh), calc="оценка остатком: отчётная прибыль акционеров − операционная − проценты", estimated=True)
            prev_interest = i_sh
            x = block_of(y_sh, i_sh, reval, div, share, shield)
            nonfin = abs(c.flow(b["nonfin_interest"], p))
            if abs(x["debt_interest"]) > nonfin + 1e-9:
                over.append(f"{q_ru(p)}: {ru(-x['debt_interest'], 2)} при {ru(nonfin)}")
            blk = {
                "reval": c.block.n(b["reval"], k, calc="; ".join(x for x in (
                    "переоценка пакета до налога, 100 %", reval_calc(c, p, reval)) if x)),
                "dividends": node(div, divs[p][1], "дивиденды по пакету до налога, 100 %" + (f": {divs[p][2]}" if divs[p][2] else "")),
                "debt_interest": node(r6(x["debt_interest"]), calc=f"adj_interest_sh / (1 − {ru(shield, 2)}): проценты по долгу под "
                                      "пакет до налога, со знаком расхода; долг — на компаниях со стопроцентным владением, "
                                      "проценты целиком отнесены на акционеров", **est),
                "pbt": node(r6(x["pbt"]), calc="reval + dividends + debt_interest", **est),
                "tax": node(r6(x["tax"]), calc="ni − pbt", **est),
                "ni": node(r6(x["ni"]), calc="ni_shareholders + nci", **est),
                "nci": node(r6(x["nci"]), share_src, f"adj_stake_sh × (1 − {ru(share, 4)}) / {ru(share, 4)}: неконтролирующая доля "
                            f"несёт только эффект пакета ({b['holder']}, доля группы {pct(share)})", **est),
                "ni_shareholders": node(r6(x["ni_shareholders"]), calc="adj_stake_sh + adj_interest_sh = отчётная прибыль "
                                        "акционеров − операционная", **est),
                "nonfin_interest": node(nonfin, c.flow_src(b["nonfin_interest"], p), "; ".join(x for x in (
                    "все проценты по долгу нефинансовых компаний за квартал, величиной (верхняя граница процентов под "
                    "пакет)", c.flow_calc(b["nonfin_interest"], p)) if x)),
                "adj_stake_sh": y_node, "adj_interest_sh": i_node,
            }
        else:
            zero = f"блока нет: до покупки пакета отчётные и операционные строки совпадают"
            x = dict.fromkeys(("debt_interest", "pbt", "tax", "ni", "nci", "ni_shareholders"), 0.0)
            blk = {k2: node(0.0, calc=zero) for k2 in ("reval", "dividends", "debt_interest", "pbt", "tax", "ni", "nci",
                                                       "ni_shareholders", "nonfin_interest", "adj_stake_sh", "adj_interest_sh")}
        gaps.append((p, rep["ni_shareholders"]["v"] - (op["v"] + x["ni_shareholders"])))
        nci = rep["ni_nci"]["v"] - x["nci"]
        ni = op["v"] + nci
        pbt = rep["pbt"]["v"] - x["pbt"]
        noncore = -x["debt_interest"]
        base = sum(row[n]["v"] for n in PNL_LINES)
        row["misc_net"] = node(r6(pbt - base - noncore), calc="pbt − (nii + fees_net + insurance_net + llp_debt_fa + opex + "
                               f"noncore_net): прочие строки отчёта без переоценки и дивидендов {b['name'].replace('пакет', 'пакета')}", **est)
        row["noncore_net"] = node(r6(noncore), calc="−investment_block.debt_interest: возврат процентов по долгу под пакет, "
                                  "до налога (сам пакет и долг под него живут вне строк банка)", **est)
        row["pbt"] = node(r6(pbt), calc="reported.pbt − investment_block.pbt (операционная прибыль до налога)", **est)
        row["tax"] = node(r6(ni - pbt), calc="ni − pbt", **est)
        row["ni"] = node(r6(ni), calc="ni_shareholders + ni_nci", **est)
        row["ni_shareholders"] = op
        row["ni_nci"] = node(r6(nci), calc="reported.ni_nci − investment_block.nci (операционная прибыль неконтролирующей доли)", **est)
        row["fv_loans_credit"] = na("не раскрыто: кредитная переоценка кредитов по справедливой стоимости отдельной строкой "
                                    "не раскрыта (кредиты — в корпоративной книге)")
        row["dia"] = c.lines_node((DIA_LINE,), p, flow=True, magnitude=True, note="расходы на страхование вкладов")
        row["at1_coupon"] = node(0.0, calc="бессрочных инструментов в капитале МСФО нет: купона из капитала нет")
        row["key_avg"] = node(c.key_avg(p), key_ref)
        for name, lines in PNL_REFERENCE.items():
            row[name] = (c.lines_node(lines, p, flow=True) if all(c.has_flow(m, p) for m in lines)
                         else na("не собрано: строки нет в листах МСФО за этот квартал"))
        row["reported"] = rep
        row["investment_block"] = blk
        quarters[p] = row

    worst = max(gaps, key=lambda g: abs(g[1]))
    c.check("отчётная прибыль акционеров = операционная + блок пакета (все кварталы ряда)", abs(worst[1]) <= 1e-4,
            f"наибольшее расхождение {worst[1]:+.6f} ({q_ru(worst[0])}); кварталов с блоком — "
            f"{sum(1 for q in quarters.values() if q['investment_block']['ni_shareholders']['v'])}")
    c.check("проценты под пакет не больше всех процентов нефинансовых компаний", not over, "; ".join(over) or "во всех кварталах")
    ni_a = quarters[a.period]["ni_shareholders"]["v"]
    mk = "op_np_exact" if c.mgmt.has("op_np_exact", a.period) else "op_np"
    ref = c.mgmt.need(mk, a.period)
    c.check("прибыль движка квартала якоря = операционной прибыли эмитента", abs(ni_a - ref) <= (0.0005 if mk.endswith("exact") else 0.05),
            f"{ru(ni_a, 6)} против {ru(ref, 4)} (лист упр. метрик, {c.mgmt.rows[(mk, a.period)]['page']})")
    last_full = a.year if a.quarter == 4 else a.year - 1
    fy, _ = c.ytd(PNL_OPERATING_NI, f"FY{last_full}")
    s_fy = sum(quarters[f"{last_full}Q{k}"]["ni_shareholders"]["v"] for k in range(1, 5))
    c.check(f"сумма прибыли движка за {last_full} год = операционной прибыли эмитента за год", abs(s_fy - fy) <= 1e-3,
            f"{ru(s_fy, 3)} против {ru(fy, 3)}")
    if a.quarter < 4 and c.history.has(PNL_OPERATING_NI, a.ytd):
        ytd, _ = c.ytd(PNL_OPERATING_NI, a.ytd)
        s_ytd = sum(quarters[q]["ni_shareholders"]["v"] for q in a.year_quarters)
        c.check(f"сумма прибыли движка за {a.ytd_ru} = операционной прибыли эмитента нарастающим итогом",
                abs(s_ytd - ytd) <= 1e-3, f"{ru(s_ytd, 3)} против {ru(ytd, 3)}")
    drift = []
    if (c.root / PNL_CHECK_SHEET).exists():
        names = {"nii": "nii", "fees_net": "fees", "insurance_net": "ins", "opex": "opex", "llp_debt_fa": "llp_debt_fa",
                 "misc_net": "misc_net", "noncore_net": "noncore_net", "pbt": "pbt", "tax": "tax", "ni": "ni", "ni_nci": "nci",
                 "ni_shareholders": "ni_shareholders"}
        for r in c.csv(PNL_CHECK_SHEET):
            p = f"{r['period'][2:]}Q{r['period'][0]}"
            if p in quarters:
                drift += [f"{p}.{mine}: {quarters[p][mine]['v']} против {r[col]}" for mine, col in names.items()
                          if abs(quarters[p][mine]["v"] - float(r[col])) > 6e-4]
        c.check("строки движка = листу калибровки ОПУ (операционный базис)", not drift,
                "; ".join(drift[:6]) or f"{len(quarters)} кварталов сошлись с {PNL_CHECK_SHEET}")
    return {
        "basis": "IFRS", "profit_basis": "operating", "as_of": a.date,
        "unit": "млрд ₽ за квартал; key_avg — доля единицы",
        "sign": "как в отчётности: расходы, резервы, налог — со знаком минус; dia — величиной; тождество "
                "pbt = nii + llp_debt_fa + fees_net + insurance_net + noncore_net + opex + misc_net",
        "note": "строки движка — на операционном базисе: прибыль движка равна операционной прибыли акционеров в определении "
                f"эмитента; reported — строки отчётности; investment_block — исключённое из строк движка ({b['name']}: "
                "переоценка, дивиденды, проценты по долгу под него); reported = строки движка + investment_block",
        "quarters": quarters,
    }


# ------------------------------------------------------------------ capital.json

F135_SHEET = "stage1/ras/cbr_f135_wide.csv"            # нормативы банка: оценка нормативов группы до выхода её формы
GROUP_BASIS = "банковская группа по Банку России (форма 0409805)"
INSTRUMENTS = (   # бессрочные субординированные займы: метрики листа примечаний МСФО (разбивка — в годовом отчёте)
    dict(id="perp_2021", title="бессрочные субординированные облигации выпуска 2021 года", currency="USD",
         nominal="sub_perp_2021_nominal_usd_mn", rate="sub_perp_2021_coupon_pct", amount="sub_perp_2021"),
    dict(id="perp_2017", title="бессрочные субординированные облигации выпуска 2017 года", currency="USD",
         nominal="sub_perp_2017_nominal_usd_mn", rate="sub_perp_2017_coupon_pct", amount="sub_perp_2017"),
    dict(id="perp_inherited", title="бессрочный субординированный заём, перешедший с Росбанком", currency="USD",
         nominal=None, rate="sub_perp_inherited_rate_pct", amount="sub_perp_inherited"),
)


def unaudited_profit(ni: dict[str, float], period: str, cutoffs: list[int]) -> float:
    """Прибыль после последнего квартала-отсечки аудита, строго предшествующего данному, по данный включительно
    (то же правило, что у ядра)."""
    total, (y, k) = 0.0, q_parse(period)
    while True:
        total += ni[f"{y}Q{k}"]
        y, k = (y - 1, 4) if k == 1 else (y, k - 1)
        if k in cutoffs:
            return total


def core_form(*, bv: float, reserve: float, payable: float, pre_dividend: bool, t2: float, at1: float, rwa: float,
              unaudited: float, keys: dict) -> tuple[float, float]:
    """Нормативы формой ядра: K20 = BVreg − Ded20 + AT1 + T2; K11 = BVreg − max(E, 0) − Ded11; норматив = K / RWA + gap."""
    bvreg = bv + (payable if pre_dividend else 0.0) - (1 - keys["fvoci_recognition"]) * reserve
    n20 = (bvreg - keys["ded20"] + at1 + t2) / rwa + keys["gap20"]
    n11 = (bvreg - max(unaudited, 0.0) - keys["ded11"]) / rwa + keys["gap11"]
    return n20, n11


def capital_keys(c: Ctx) -> tuple[dict, str] | None:
    """Ключи листа калибровки капитала для сверки формой ядра; листа нет — сверки нет."""
    path = c.root / CAPITAL_KEYS
    if not path.exists():
        return None
    import yaml
    cap = yaml.safe_load(path.read_text(encoding="utf-8"))["capital"]
    keys = {"ded20": float(cap["n20"]["deductions_anchor"]), "gap20": float(cap["n20"]["gap_pp"]),
            "fvoci_recognition": float(cap["n20"]["fvoci_recognition"]), "ded11": float(cap["n11"]["deductions_anchor"]),
            "gap11": float(cap["n11"]["gap_pp"]), "audit_cutoffs": [int(x) for x in cap["n11"]["audit_cutoffs"]]}
    ref = c.sheet_ref(CAPITAL_KEYS, "ключи капитала: вычеты якоря, поправки, доля фонда переоценки, отсечки аудита",
                      title="Предложение ключей книги по капиталу (лист калибровки капитала)", key="calib_capital_keys")
    return keys, ref


def build_capital(c: Ctx, bal: dict, pnl: dict) -> dict:
    a = c.a
    forms = {r["period_end"]: r for r in c.csv(GROUP_FORM)}

    def form_ref(r: dict, what: str = "") -> str:
        return c.docs.ref(None, f"форма 0409805 на {d_ru(r['form_date'])}" + (f", {what}" if what else ""), r["sha256"],
                          url=r["url"])

    def bn(r: dict, col: str) -> float:
        return round(float(r[col]) / 1e6, 3)

    def ratio(r: dict, col: str) -> float:
        return round(float(r[col]) / 100, 6)

    row = forms.get(a.date)
    estimated = row is None
    if estimated:                                      # формы на якорь ещё нет: норматив банка + разность «группа − банк»
        last = max(d for d in forms if d < a.date)
        row = forms[last]
        bank = {r["form_date"]: r for r in c.csv(F135_SHEET)}
        now, then = bank.get((q_end(a.period) + dt.timedelta(days=1)).isoformat()), bank.get(row["form_date"])
        if now is None or then is None:
            raise BuildError(f"нет формы 0409805 на {a.date} и нет нормативов банка для оценки ({F135_SHEET})")
        est = {}
        for slot, g, b_col in (("n20_0", "n20_0_pct", "n1_0_pct"), ("n20_1", "n20_1_pct", "n1_1_pct")):
            spread = float(row[g]) - float(then[b_col])
            src = (c.docs.ref(None, f"форма 0409135 на {d_ru(now['form_date'])}", now["sha256"]) + "; " + form_ref(row)
                   + "; " + c.docs.ref(None, f"форма 0409135 на {d_ru(then['form_date'])}", then["sha256"]))
            est[slot] = (round((float(now[b_col]) + spread) / 100, 6), src,
                         {"bank_value": node(round(float(now[b_col]) / 100, 6), calc="норматив банка на дату якоря"),
                          "spread": node(round(spread / 100, 6), calc="норматив группы − норматив банка на последнюю общую дату"),
                          "spread_as_of": last})
    as_of = a.date
    level_note = f"значение последней формы на {d_ru(row['period_end'])}: формы на якорь ещё нет" if estimated else None
    flag = {"estimated": True} if estimated else {}

    def level(col: str, what: str) -> dict:
        return node(bn(row, col), form_ref(row, what), level_note, **flag)

    total, base = level("capital_total_th", "стр. 000"), level("cet1_th", "стр. 102")
    additional, suppl = level("at1_th", "стр. 105"), level("tier2_th", "стр. 203")
    if estimated:
        n20 = node(est["n20_0"][0], est["n20_0"][1], "оценка до выхода формы: норматив банка + разность «группа − банк»", estimated=True)
        n201 = node(est["n20_1"][0], est["n20_1"][1], "оценка до выхода формы: норматив банка + разность «группа − банк»", estimated=True)
        n202 = na("формы 0409805 на якорь ещё нет; оценка строится только для двух нормативов ядра", basis=GROUP_BASIS)
    else:
        n20, n201 = node(ratio(row, "n20_0_pct"), form_ref(row)), node(ratio(row, "n20_1_pct"), form_ref(row))
        n202 = node(ratio(row, "n20_2_pct"), form_ref(row), basis=GROUP_BASIS)
    cet1 = round(total["v"] - additional["v"], 3)
    rwa = round(float(row["capital_total_th"]) / 1e6 / ratio(row, "n20_0_pct"), 3)
    reserve = bal["equity"]["fvoci_reserve"]
    sub = bal["wholesale"]["perpetual_sub"]
    n20_block = {"basis": GROUP_BASIS + ": Н20.0", "value": n20, "as_of": as_of, "estimated": estimated, "pre_dividend": False,
                 "pre_dividend_note": "дивиденд холдинга из капитала банковской группы на дату реестра не вычитается: "
                                      "объявленных и не вычтенных из норматива дивидендов на якоре нет"}
    n11_block = {"basis": GROUP_BASIS + ": Н20.1 (имя слота ядра историческое)", "value": n201, "as_of": as_of,
                 "estimated": estimated}
    if estimated:
        n20_block["estimate"], n11_block["estimate"] = est["n20_0"][2], est["n20_1"][2]
    if c.anchor_sheet.has("n20_0_min_with_buffers_pct", a.date):
        n20_block["min_with_buffers"] = c.anchor_sheet.n("n20_0_min_with_buffers_pct", a.date, scale=0.01,
                                                         calc="минимум Н20.0 с надбавками на дату якоря (примечание об управлении капиталом)")
    curve = {r["period_y"]: r for r in c.csv(CURVE_SHEET, comment=True) if r["quarter_end"] == a.date}
    if not all(f"{float(t):.1f}" in curve for t in CURVE_NODES):
        raise BuildError(f"{CURVE_SHEET}: нет узлов кривой {', '.join(CURVE_NODES)} лет на {a.date}")
    s_curve = c.sheet_ref(CURVE_SHEET, f"кривая бескупонной доходности ОФЗ (MOEX ISS) на {d_ru(a.date)}",
                          title="Кривая бескупонной доходности ОФЗ Московской биржи на концы кварталов "
                                "(узлы 1, 2, 3, 5, 10 лет)", key="zcyc_quarter_ends")
    out = {
        "basis": "mixed", "as_of": a.date,
        "note": "у каждого блока свой basis: банковская группа по форме Банка России 0409805 (головная организация — "
                f"{GROUP_HEAD}), МСФО группы, Базель III по МСФО (примечание отчётности), рынок. Слоты ядра сохраняют "
                "имена семейства: n1_1_bank — Н20.1 банковской группы, bank_base_capital — базовый капитал группы",
        "n20_0": n20_block, "n1_1_bank": n11_block, "n20_2": n202,
        "bank_base_capital": {**base, "calc": "; ".join(x for x in (base.get("calc"), "базовый капитал банковской группы (слот ядра)") if x),
                              "basis": GROUP_BASIS},
        "group_capital": {"basis": GROUP_BASIS, "total": total, "base": base, "additional": additional, "supplementary": suppl},
        "basel": {
            "basis": GROUP_BASIS + " — слоты ядра; Базель III по МСФО — блок basel_ifrs", "as_of": as_of,
            "cet1": node(cet1, calc="капитал группы без регуляторных инструментов: group_capital.total − t2_recognized "
                                    "(базовый капитал + дополнительный); вычеты якоря = капитал акционеров МСФО − этот узел", **flag),
            "rwa": node(rwa, calc="вменённые активы, взвешенные по риску: group_capital.total / n20_0.value "
                                  "(в форме отдельной строкой не раскрыты)", **flag),
            "cet1_ratio": node(round(cet1 / rwa, 6), calc="basel.cet1 / basel.rwa", **flag),
            "total_ratio": node(round(total["v"] / rwa, 6), calc="group_capital.total / basel.rwa (= Н20.0 формы)", **flag),
        },
        "t2_recognized": {**additional, "calc": "; ".join(x for x in (additional.get("calc"), "регуляторные инструменты группы без "
                          "прибыли: добавочный капитал (слот ядра; стартовое значение траектории инструментов)") if x),
                          "basis": GROUP_BASIS},
        "at1": {"basis": "IFRS",
                "amount": node(0.0, calc=f"бессрочных инструментов в капитале МСФО нет: бессрочные займы {ru(sub['v'])} — "
                                         "обязательство; регуляторные инструменты — узел t2_recognized"),
                "coupon_annual": node(0.0, calc="проценты по бессрочным займам — в процентных расходах МСФО; купона из капитала нет"),
                "coupon_quarter": node(4, calc="формальное значение: купон равен нулю")},
        "fvoci_reserve": node(reserve["v"], reserve["src"], "фонд переоценки бумаг через прочий совокупный доход, после налога; "
                              "= balance.equity.fvoci_reserve", basis="IFRS"),
        "ofz_curve_anchor": {"basis": "market", "as_of": a.date,
                             "convention": "бескупонная доходность ОФЗ (кривая Московской биржи), годовое начисление, доли",
                             **{t: node(round(float(curve[f"{float(t):.1f}"]["yield_pct"]) / 100, 6), s_curve) for t in CURVE_NODES}},
    }
    names = {"cet1": "basel_cet1", "tier1": "basel_t1", "rwa": "basel_rwa", "cet1_ratio": "basel_cet1_ratio_pct",
             "total_ratio": "basel_total_ratio_pct"}
    out["basel_ifrs"] = {"basis": "Базель III по МСФО (примечание об управлении капиталом); справочно, ядро не читает",
                         "as_of": a.date,
                         **{k: (c.anchor_sheet.n(m, a.date, scale=0.01 if m.endswith("_pct") else 1.0)
                                if c.anchor_sheet.has(m, a.date) else na("в отчётности на якорь не раскрыто"))
                            for k, m in names.items()}}
    fy = max(d for (m, d) in c.notes.rows if m == INSTRUMENTS[0]["amount"])
    items = []
    for it in INSTRUMENTS:
        note_row = c.notes.note(it["nominal"] or it["rate"], fy)
        call = re.search(r"право погашения с (\d\d)\.(\d\d)\.(\d{4})", note_row)
        items.append({
            "id": it["id"], "title": it["title"], "currency": it["currency"],
            "amount": (c.notes.n(it["nominal"], fy, calc="номинал, млн долларов США", basis="IFRS") if it["nominal"]
                       else na("номинал займа в отчётности не раскрыт", basis="IFRS")),
            "rate": c.notes.n(it["rate"], fy, scale=0.01, calc="ставка, доля", basis="IFRS"),
            "call_from": f"{call.group(3)}-{call.group(2)}-{call.group(1)}" if call else None,
            "amount_rub": c.notes.n(it["amount"], fy, calc=f"балансовая стоимость на {d_ru(fy)}, млрд ₽: разбивка по выпускам "
                                    "раскрывается только в годовом отчёте", basis="IFRS"),
        })
    out["instruments"] = items
    out["instruments_total"] = node(sub["v"], sub["src"], f"бессрочные субординированные займы на {d_ru(a.date)}, всего "
                                    "(в МСФО — обязательство)", basis="IFRS")
    hist = []
    for p in q_range(CAPITAL_HISTORY_FIRST, a.period):
        r = forms.get(q_end(p).isoformat())
        if r is None:
            continue
        ref = form_ref(r)
        g = lambda v, calc=None: node(v, ref, calc, basis=GROUP_BASIS)   # noqa: E731
        hist.append({"period": p, "date": r["period_end"], "n20_0": g(ratio(r, "n20_0_pct")), "n20_1": g(ratio(r, "n20_1_pct")),
                     "n20_2": g(ratio(r, "n20_2_pct")), "capital_total": g(bn(r, "capital_total_th")),
                     "capital_base": g(bn(r, "cet1_th")), "capital_additional": g(bn(r, "at1_th")),
                     "capital_supplementary": g(bn(r, "tier2_th")),
                     "rwa_imputed": node(round(bn(r, "capital_total_th") / ratio(r, "n20_0_pct"), 1), ref,
                                         "капитал / Н20.0 (норматив напечатан с двумя знаками: точность ±0,04 %)", basis=GROUP_BASIS)})
    out["history"] = hist
    got = capital_keys(c)
    if got and a.period != CAPITAL_KEYS_ANCHOR:        # ключи листа выведены на другом якоре: сверять ими нечего
        c.check("нормативы формой ядра на ключах листа капитала", True,
                f"не сверяется: ключи листа выведены на якоре {CAPITAL_KEYS_ANCHOR}; на якоре {a.period} вычеты и поправки "
                "выводит перезаякоривание")
    elif got and not estimated:
        keys, ref = got
        ni = {p: q["ni_shareholders"]["v"] for p, q in pnl["quarters"].items()}
        e0 = unaudited_profit(ni, a.period, keys["audit_cutoffs"])
        n20_c, n11_c = core_form(bv=bal["equity"]["bv_common"]["v"], reserve=reserve["v"], payable=bal["dividends_payable"]["v"],
                                 pre_dividend=False, t2=additional["v"], at1=0.0, rwa=rwa, unaudited=e0, keys=keys)
        c.check("нормативы формой ядра на ключах листа капитала = форме 0409805",
                abs(n20_c - n20["v"]) <= 5e-5 and abs(n11_c - n201["v"]) <= 5e-5,
                f"Н20.0 {pct(n20_c, 3)} против {pct(n20['v'])}; Н20.1 {pct(n11_c, 3)} против {pct(n201['v'])} (прибыль после "
                f"отсечки аудита {ru(e0, 3)}; вычеты {ru(keys['ded20'], 3)} и {ru(keys['ded11'], 3)})")
        out["core_form_check"] = {
            "basis": "mixed: капитал акционеров МСФО и норматив банковской группы; сверка сборщика, ядро не читает",
            "note": "нормативы якоря формой ядра на ключах листа калибровки капитала: K20 = BVreg − вычеты + инструменты, "
                    "K11 = BVreg − прибыль после отсечки аудита − вычеты; BVreg = капитал акционеров − (1 − доля признания) × "
                    "фонд переоценки; норматив = K / basel.rwa + поправка",
            "keys": {"deductions_n20": node(keys["ded20"], ref), "deductions_n11": node(keys["ded11"], ref),
                     "fvoci_recognition": node(keys["fvoci_recognition"], ref), "gap_n20": node(keys["gap20"], ref),
                     "gap_n11": node(keys["gap11"], ref),
                     "audit_cutoffs": ", ".join(str(x) for x in keys["audit_cutoffs"])},
            "unaudited_profit": node(round(e0, 6), calc="Σ ni_shareholders после последней отсечки аудита по квартал якоря"),
            "n20_0": node(round(n20_c, 6), calc="(BVreg − deductions_n20 + t2_recognized) / basel.rwa + gap_n20"),
            "n20_1": node(round(n11_c, 6), calc="(BVreg − unaudited_profit − deductions_n11) / basel.rwa + gap_n11"),
        }
    elif estimated:
        c.check("нормативы формой ядра на ключах листа капитала", True, "не сверяется: нормативы якоря — оценка до выхода формы")
    return out


# ------------------------------------------------------------------ shares.json

def shares_at(c: Ctx, date: str) -> tuple[float, float, float, dict]:
    """(размещено, собственные, в обращении, строка листа) на дату, млн шт. после дробления — отчётность МСФО."""
    for r in c.csv(SHARES_SHEET):
        if r["date"] == date and r["basis"].startswith("МСФО") and r["treasury"]:
            return int(r["issued"]) / 1e6, int(r["treasury"]) / 1e6, int(r["outstanding"]) / 1e6, r
    raise BuildError(f"{SHARES_SHEET}: нет строки МСФО с числом акций на {date}")


def build_shares(c: Ctx) -> dict:
    a = c.a
    issued, treasury, outstanding, r = shares_at(c, a.date)
    rows = c.csv(SHARES_SHEET)
    ref = c.docs.ref(r["source_file"], page_words(r["page_pdf"]), r["sha256"])
    c.check("акции: размещённые − собственные = в обращении", abs(issued - treasury - outstanding) < 1e-9,
            f"{ru(issued, 5)} − {ru(treasury, 1)} = {ru(issued - treasury, 5)} против {ru(outstanding, 5)}")
    votes = [x for x in rows if x["voting"]]
    v = max(votes, key=lambda x: x["date"]) if votes else None
    block = None
    if v is not None:
        v_ref = c.docs.ref(v["source_file"], page_words(v["page_pdf"]), v["sha256"])
        blocked = (int(v["depositary_block"] or 0) + int(v["not_in_list"] or 0)) / 1e6
        block = node(round(blocked, 5), v_ref, f"акции без голосов и выплат на {d_ru(v['date'])}: на счёте депозитарных программ "
                     f"{ru(int(v['depositary_block'] or 0) / 1e6, 5)} + вне списка {ru(int(v['not_in_list'] or 0) / 1e6, 5)} "
                     "(= размещённые − голосующие); в делитель «на акцию» входят")
    actions, sheet_dates = [], []
    by_date = {x["date"]: x for x in rows if x["basis"].startswith("МСФО")}
    for x in c.csv(ACTIONS_SHEET):
        sheet_dates.append(x["date"])
        if x["date"] not in ACTIONS:
            raise BuildError(f"{ACTIONS_SHEET}: событие {x['date']} ({x['type']}) без подписи в таблице ACTIONS сборщика")
        kind, title = ACTIONS[x["date"]]
        s = c.docs.ref(x["source_file"], page_words(x["page_pdf"]), x["sha256"])
        ev = {"date": x["date"], "kind": kind, "title": title, "src": s}
        if kind == "split":
            before = max(d for d in by_date if d < x["date"])
            factor = int(by_date[x["date"]]["issued_as_reported"]) / int(by_date[before]["issued_as_reported"])
            first = SPLIT_FIRST_TRADE.get(x["date"])
            if first is None or d_ru(first) not in x["description"]:
                raise BuildError(f"{ACTIONS_SHEET}: первый торговый день после дробления {x['date']} не подтверждён листом событий")
            ev["factor"] = node(round(factor, 6), s, "во сколько раз выросло число акций: размещённые после / до дробления")
            ev["first_trade_date"] = first
        if kind == "issue" and x["shares_before"] and x["shares_after"]:
            ev["shares_before"] = node(round(int(x["shares_before"]) / 1e6, 5), s, "размещённые акции до события, млн шт. после дробления")
            ev["shares_after"] = node(round(int(x["shares_after"]) / 1e6, 5), s, "размещённые акции после события, млн шт. после дробления")
        actions.append(ev)
    missing = sorted(set(ACTIONS) - set(sheet_dates))
    if missing:
        raise BuildError(f"таблица ACTIONS: событий нет в листе {ACTIONS_SHEET}: {', '.join(missing)}")
    out = {
        "basis": "IFRS", "as_of": a.date, "unit": "млн шт. после дробления 1:10; номинал — ₽",
        "issued_total": node(round(issued, 5), ref, "размещённые обыкновенные акции (делитель дивиденда на акцию)"),
        "issued_ordinary": node(round(issued, 5), ref, "все размещённые акции — обыкновенные"),
        "treasury_ordinary": node(round(treasury, 5), ref, "собственные акции (у дочерних компаний; под программу мотивации)"),
        "outstanding_total": node(round(outstanding, 5), calc="issued_total − treasury_ordinary"),
        "outstanding_ordinary": node(round(outstanding, 5), calc="issued_ordinary − treasury_ordinary"),
        "economic_treasury": node(0.0, calc="до закрытия сделки с «Точкой» экономически собственных акций сверх собственных "
                                            "по МСФО нет"),
        "by_ticker": {TICKER: {"class": "ordinary"}},
        "corporate_actions": actions,
    }
    if block is not None:
        out["depositary_block"] = block
        out["voting"] = node(round(int(v["voting"]) / 1e6, 5), v_ref, f"голосующие акции на {d_ru(v['date'])} (дата фиксации списка)")
    if c.anchor_sheet.has("ltip_shares_th", a.date):
        out["motivation_program"] = c.anchor_sheet.n("ltip_shares_th", a.date, scale=0.001,
                                                     calc="акции, относящиеся к программе долгосрочной мотивации, млн шт.")
    if c.anchor_sheet.has("share_nominal_rub", a.date):
        out["par_value"] = c.anchor_sheet.n("share_nominal_rub", a.date, calc="номинал акции после дробления, ₽")
    return out


# ------------------------------------------------------------------ dividends.json

def dividend_rows(c: Ctx) -> list[dict]:
    if not hasattr(c, "_dividends"):
        c._dividends = c.csv(DIVIDENDS_SHEET)
    return c._dividends


def dividend_period(r: dict) -> str:
    """Квартал прибыли решения: «2024Q1-Q3» — решение за девять месяцев — пишется последним кварталом."""
    p = r["fiscal_period"]
    return p[:4] + p[-2:] if "-" in p else p


def dividends_ref(c: Ctx, what: str = "") -> str:
    return c.sheet_ref(DIVIDENDS_SHEET, what or "решения собраний акционеров о дивидендах",
                       title="Решения собраний акционеров о дивидендах после редомициляции — документы эмитента "
                             "(«История дивидендных выплат», рекомендации совета директоров, протоколы) и новости о решениях",
                       key="dividends_public")


def dividend_record(c: Ctx, r: dict) -> dict:
    """Строка истории: одно решение собрания. Всё «на акцию» — после дробления, исходное значение — рядом."""
    period, factor = dividend_period(r), int(r["split_factor"])
    docs = [(r["issuer_doc"], r["issuer_doc_file"], r["issuer_doc_sha256"], r["issuer_doc_url"]),
            (r["issuer_doc2"], r["issuer_doc2_file"], r["issuer_doc2_sha256"], r["issuer_doc2_url"])]
    refs = [(title, c.docs.ref(file, "", sha, url=url or None)) for title, file, sha, url in docs if file]
    sheet = dividends_ref(c, f"решение {d_ru(r['decided_date'])}: {r['legal_period']}")
    src = "; ".join([x[1] for x in refs] + [sheet])
    s16 = sheet.rsplit("sha256 ", 1)[1]
    news = [(r["news_outlet"], r["news_published"], r["news_title"], r["news_url"])]
    if r.get("news2"):
        parts = [x.strip() for x in r["news2"].split(";")]
        if len(parts) == 4:
            news.append(tuple(parts))
    sources = [f"manual: документ эмитента — {title} ({ref})" for title, ref in refs]
    sources += [f"news: {o}, {d_ru(when[:10])}: {t} — {u} (лист решений о дивидендах, sha256 {s16})"
                for o, when, t, u in news if o and u]
    dps = float(r["dps"])
    return {
        "year": int(period[:4]), "period": period, "label": r["legal_period"],
        "dps": node(dps, src, "дивиденд на акцию после дробления 1:10, ₽" if factor > 1 else "дивиденд на акцию, ₽"),
        "dps_pre_split": (node(float(r["dps_pre_split"]), src, f"как объявлено решением, до дробления: dps × {factor}") if factor > 1
                          else na("решение принято после дробления: исходное значение равно dps")),
        "split_factor": factor,
        "recommended_date": r["board_recommendation_date"], "decided_date": r["decided_date"], "decided_by": r["decided_by"],
        "record_date": r["record_date"], "last_buy_date": r["last_buy_date"], "ex_date": r["ex_date"],
        "pay_date": r["pay_deadline_nominee"], "pay_deadline_others": r["pay_deadline_others"], "settlement": "T+1",
        "pool_declared": node(round(int(r["total_rub"]) / 1e9, 6), src, "сумма на все размещённые акции (строка «Итого» эмитента): "
                              + r["total_basis"].split(";")[0]),
        "sources": sources,
    }


def build_dividends(c: Ctx, shares: dict, pnl: dict) -> dict:
    a = c.a
    rows = dividend_rows(c)
    history = [dividend_record(c, r) for r in rows]
    splits = [(x["date"], x["factor"]["v"]) for x in shares["corporate_actions"] if x["kind"] == "split"]
    bad = []
    for r, h in zip(rows, history):
        want = 1
        for when, factor in splits:
            if r["decided_date"] < when:
                want *= int(factor)
        if h["split_factor"] != want:
            bad.append(f"{h['period']}: коэффициент дробления {h['split_factor']}, по событиям — {want}")
        if want > 1 and abs(h["dps"]["v"] * want - h["dps_pre_split"]["v"]) > 1e-9:
            bad.append(f"{h['period']}: {h['dps']['v']} × {want} ≠ {h['dps_pre_split']['v']} (значение решения)")
        n_then = shares["issued_total"]["v"] * 1e6
        if abs(h["dps"]["v"] * n_then - int(r["total_rub"])) > 1.0:
            bad.append(f"{h['period']}: сумма {r['total_rub']} ≠ DPS × размещённые акции")
        gap = (dt.date.fromisoformat(h["record_date"]) - dt.date.fromisoformat(h["decided_date"])).days
        pay = (dt.date.fromisoformat(h["pay_date"]) - dt.date.fromisoformat(h["record_date"])).days
        buy = (dt.date.fromisoformat(h["record_date"]) - dt.date.fromisoformat(h["last_buy_date"])).days
        if not RECORD_AFTER_DECISION[0] <= gap <= RECORD_AFTER_DECISION[1]:
            bad.append(f"{h['period']}: реестр через {gap} дней после решения")
        if h["ex_date"] != h["record_date"] or not 0 < buy <= 5 or not PAY_DAYS[0] <= pay <= PAY_DAYS[1]:
            bad.append(f"{h['period']}: даты не по правилу (экс-дата = реестр, покупка — накануне, выплата через {pay} дней)")
        if len({s.split(":", 1)[0] for s in h["sources"]}) < 2:
            bad.append(f"{h['period']}: меньше двух видов источников")
    periods = [h["period"] for h in history]
    if periods != sorted(set(periods)):
        bad.append("периоды решений повторяются или идут не по порядку")
    c.check("дивиденды: решения после дробления с исходными значениями, суммы и даты", not bad,
            "; ".join(bad) or f"решений {len(history)}: " + ", ".join(f"{h['period']} {ru(h['dps']['v'], 2)} ₽" for h in history))
    broker = {r["record_date"]: r for r in c.csv(BROKER_CHECK_SHEET)} if (c.root / BROKER_CHECK_SHEET).exists() else None
    if broker is None:
        raise BuildError(f"нет листа сверки с брокерским календарём {BROKER_CHECK_SHEET}")
    miss = [h["period"] for h in history if broker.get(h["record_date"], {}).get("result") != "совпало"]
    checked = max(r["checked"] for r in broker.values())
    c.check("дивиденды: сверка с брокерским календарём", not miss,
            ("расхождение или нет записи: " + ", ".join(miss)) if miss
            else f"все {len(history)} решений совпали по размеру, дате реестра и последнему дню покупки (снимок {d_ru(checked)})")

    years = {}
    for y in sorted({h["year"] for h in history}):
        complete = y < a.year or a.quarter == 4
        label = f"FY{y}" if complete else a.ytd
        v, src = c.ytd(PNL_REPORTED["ni_shareholders"], label)
        years[str(y)] = {"ni_shareholders": node(v, src, "отчётная прибыль акционеров по МСФО за год" if complete else
                                                 f"отчётная прибыль акционеров по МСФО с начала года по {q_ru(a.period)}"),
                         "complete": complete, **({} if complete else {"through": a.period})}
        pool = sum(h["pool_declared"]["v"] for h in history if h["year"] == y)
        c.check(f"дивиденды {y}: объявлено против потолка политики", True,
                f"объявлено {ru(pool, 3)} при потолке {ru(POLICY['cap'] * v, 3)} ({pct(POLICY['cap'], 0)} от {ru(v, 3)})"
                + ("" if pool <= POLICY["cap"] * v + 1e-9 or not complete else " — ВЫШЕ потолка")
                + ("" if complete else " — год не завершён, справочно"))
    snapshot = max(r["accessed"] for r in rows)
    seed = []
    for h in history:
        if h["ex_date"] > a.date:
            seed.append({k: h[k] for k in ("year", "period", "label", "dps")} | {
                "status": "paid" if h["pay_date"] <= snapshot else "declared",
                **{k: h[k] for k in ("decided_date", "recommended_date", "record_date", "last_buy_date", "ex_date", "pay_date",
                                     "sources")}})
    pol_ref = c.docs.ref(POLICY["doc"])
    pol_sha = c.docs.sha_of(c.root / POLICY["doc"])
    policy = {
        "name": POLICY["name"], "doc": Path(POLICY["doc"]).name, "doc_title": doc_title(POLICY["doc"], None),
        "sha256": pol_sha, "approved": POLICY["approved"],
        "approved_by": POLICY["approved_by"], "frequency": POLICY["frequency"],
        "cap": node(POLICY["cap"], c.docs.ref(POLICY["doc"], page_words(str(POLICY["cap_page"]))), POLICY["cap_words"]),
        "threshold": na(POLICY["threshold_words"]),
        "valid_until": na(POLICY["term_words"]),
        "valid_until_note": POLICY["valid_until_note"],
        "text": POLICY["text"], "src": pol_ref,
    }
    return {
        "basis": "IFRS", "as_of": a.date, "snapshot": snapshot,
        "unit": "DPS — ₽ на акцию после дробления 1:10 (исходное значение решения — dps_pre_split); суммы — млрд ₽",
        "policy": policy,
        "history": history,
        "years": years,
        "register_seed": seed,
        "register_seed_note": "стартовый реестр: решения собраний с экс-датой позже якоря — их дивиденд ещё не вычтен из "
                              "капитала якоря; статус — на дату снимка листа решений. У каждой записи два источника разных "
                              "видов: документ эмитента и новость о решении",
        "dates_rule": "Дата реестра — дата, на которую определяются лица, имеющие право на дивиденды (решение собрания; не "
                      "раньше 10 и не позже 20 дней после решения). Экс-дата при расчётах T+1 — день реестра; последний день "
                      "покупки с дивидендом — торговый день перед ним. Срок выплаты — 10 рабочих дней после даты реестра "
                      "номинальным держателям (брокерам и депозитариям) и 25 рабочих дней прочим лицам реестра.",
        "broker_check": f"Размер дивиденда на акцию после дробления, дата реестра и последний день покупки по всем "
                        f"{len(history)} решениям сверены с брокерским календарём дивидендов (снимок {d_ru(checked)}) — "
                        "расхождений нет. Источник чисел — документы эмитента и новости о решениях; брокерский календарь — "
                        "только сверка.",
    }


# ------------------------------------------------------------------ guidance.json

def build_guidance(c: Ctx, pnl: dict, div: dict) -> dict:
    a = c.a
    rows = c.csv(GUIDANCE_SHEET)

    def ref(r: dict) -> str:
        return c.docs.ref(r["doc"], page_words(r["page"]), r["sha256"])

    def stated(r: dict) -> bool:                       # формулировка гайденса, не строка о ходе выполнения
        return "(факт" not in r["event"]

    prev = a.year - 1
    base_ni = sum(pnl["quarters"][f"{prev}Q{k}"]["ni_shareholders"]["v"] for k in range(1, 5))
    base_dps = sum(h["dps"]["v"] for h in div["history"] if h["year"] == prev)
    items, as_of = {}, ""
    for key, (kind, tol, note, phrase) in GUIDANCE_ITEMS.items():
        own = [r for r in rows if r["metric"] == key and stated(r)
               and r["target_year"] in ((str(a.year),) if key != "roe_target" else ("LT",))]
        if not own:
            items[key] = na(f"не раскрыто: эмитент не даёт числа на {a.year} год")
            continue
        results = [r for r in own if r["event"].startswith("МСФО")] or own
        r = max(results if key != "roe_target" else own, key=lambda x: x["as_of"])
        v = round(float(r["low"]) / 100, 6)
        if key == "op_np_growth":
            calc = (f"«{r['low']}%» → доли; база — операционная прибыль акционеров {prev} года {ru(base_ni, 3)} млрд ₽, "
                    f"порог {a.year} года — {ru(base_ni * (1 + v), 1)}")
        elif key == "dps_growth":
            calc = (f"«{r['low']}%» → доли; база — {ru(base_dps, 2)} ₽ на акцию за {prev} год (после дробления), "
                    f"граница — более {ru(base_dps * (1 + v), 2)} ₽ за {a.year} год")
        else:
            calc = f"«{r['low']}%» → доли; цель стратегии без года"
        said = re.search(phrase, r["text"])
        extra = {"kind": kind, "text": said.group(0) if said else r["text"], "date": r["as_of"], "event": r["event"],
                 "scope": "group"}
        if tol is not None:
            extra["tol"] = tol
        if note:
            extra["scope_note"] = note.format(bound=ru(base_dps * (1 + v), 2), year=a.year, base=ru(base_dps, 2), prev=prev)
        items[key] = node(v, ref(r), calc, **extra)
        if key != "roe_target":
            as_of = max(as_of, r["as_of"])
    for key in GUIDANCE_ABSENT:
        items[key] = na(f"не раскрыто: эмитент не даёт числа на {a.year} год")
    history = []
    for r in sorted(rows, key=lambda x: (x["as_of"], x["metric"])):
        year_item = r["metric"] in ("op_np_growth", "dps_growth") and r["target_year"] == str(a.year) and r["event"].startswith("МСФО")
        target = r["metric"] == "roe_target" and r["target_year"] == "LT"
        if not stated(r) or not (year_item or target) or not r["low"]:
            continue
        history.append({"date": r["as_of"], "key": r["metric"],
                        "value": node(round(float(r["low"]) / 100, 6), ref(r), f"«{r['low']}%» → доли"),
                        "event": r["event"], "note": r["note"] or "без записки"})
    return {
        "basis": "mgmt", "year": a.year, "as_of": as_of or a.date,
        "unit": "доли; kind: min — нижняя граница, point — точка с допуском tol",
        "note": "гайденс эмитента — рост операционной прибыли акционеров и дивидендов на акцию за год; цель по ROE — цель "
                "стратегии к операционному капиталу. Чисел по марже, стоимости риска и отношению расходов к доходам эмитент не даёт",
        "items": items,
        "history": history,
    }


# ------------------------------------------------------------------ mgmt_quarterly.json

MGMT_PAIRS = {   # узел фактов → метрика листа упр. метрик: напечатанное — без суффикса, точное — с суффиксом _exact
    "nim": "nim", "cor": "cor_total", "cir": "cir", "roe": "roe", "op_np": "op_np", "op_equity": "op_capital",
    "roe_shareholders": "roe_shareholders", "roe_reported": "roe_reported", "cost_of_funding": "cost_of_funding",
    "clients_total": "clients_total", "clients_active": "clients_active",
}
MGMT_SINGLE = {   # только точное (напечатанного по продуктам нет) и только напечатанное
    "cor_cards": "cor_cards_exact", "cor_cash": "cor_cash_exact", "cor_auto": "cor_auto_exact",
    "cor_mortgage": "cor_mortgage_exact", "cor_sme": "cor_sme_exact", "cor_corp": "cor_corp_exact",
    "cor_lease": "cor_lease_exact", "asset_yield": "asset_yield",
}
MGMT_ANNUAL = ("nim", "cor", "cir", "roe")
MGMT_HISTORY = {"nim": "ЧПМ", "cor": "стоимость риска", "cir": "расходы к доходам", "roe": "ROE эмитента"}   # метрики
#                                 отчётной истории выпуска (упр. базис) и их слова в причине частичного провала


def ru_day(d: dt.date) -> str:
    return d.strftime("%d.%m.%Y")


def history_gaps(quarters: dict) -> list[dict]:
    """Частичные провалы раскрытия отчётной истории (`history_gaps`): квартал или диапазон, базис, причина словами.

    Упр. базис — напечатанных значений части метрик истории у квартала нет (квартал без единой метрики называет
    сборка выпуска — здесь его нет). МСФО — до первого конца квартала истории баланса нет остатков: капитал, ROE и
    стоимость риска по МСФО не считаются (в первом квартале истории — ROE и стоимость риска: им нужен и
    предыдущий конец); там же — до первой формы с нормативами группы нет Н20.0. Подряд идущие кварталы с одной
    причиной — одной записью-диапазоном."""
    rows: list[tuple[str, str, str]] = []
    for p, row in quarters.items():
        missing = [title for name, title in MGMT_HISTORY.items() if row[name]["v"] is None]
        if missing and len(missing) < len(MGMT_HISTORY):
            exact = all(row[name + "_exact"]["v"] is not None for name in MGMT_HISTORY if row[name]["v"] is None)
            where = "точное значение" if len(missing) == 1 else "точные значения"
            rows.append((p, "mgmt", f"не напечатано в пресс-релизе и презентации квартала: {', '.join(missing)}"
                         + (f"; {where} — в справочнике аналитика эмитента" if exact else "")))
        no_form = p < CAPITAL_HISTORY_FIRST
        form = (f"; норматив Н20.0 банковской группы — с формы на {ru_day(q_end(CAPITAL_HISTORY_FIRST) + dt.timedelta(days=1))}"
                if no_form else "")
        if p < HISTORY_FIRST:
            rows.append((p, "ifrs", f"остатков капитала и кредитов на концы кварталов до {ru_day(q_end(HISTORY_FIRST))} в фактах нет: "
                                    f"капитал, ROE и стоимость риска по МСФО не считаются{form}"))
        elif p == HISTORY_FIRST:
            rows.append((p, "ifrs", f"ROE и стоимость риска по МСФО считаются по среднему двух концов квартала, а остатков на "
                                    f"{ru_day(q_end(q_prev(p)))} в фактах нет{form}"))
        elif no_form:
            rows.append((p, "ifrs", form[2:]))
    out: list[dict] = []
    for basis in ("mgmt", "ifrs"):
        run: list[str] = []
        why = None
        for p, b, reason in [r for r in rows if r[1] == basis] + [("", basis, None)]:
            if run and (reason != why or p != q_next(run[-1])):
                out.append({"period": run[0] if len(run) == 1 else f"{run[0]}–{run[-1]}", "basis": basis, "reason": why})
                run = []
            if reason is not None:
                run.append(p)
                why = reason
    return out


def mgmt_node(c: Ctx, metric: str, period: str, why: str) -> dict:
    r = c.mgmt.rows.get((metric, period))
    if r is None or c.mgmt.get(metric, period) is None:
        return na(why)
    share = r["unit"].strip() == "%"
    return c.mgmt.n(metric, period, scale=0.01 if share else 1.0, calc="проценты документа → доли" if share else None)


def build_mgmt(c: Ctx) -> dict:
    a = c.a
    quarters = {}
    for p in q_range(PNL_FIRST, a.period):
        row = {}
        for name, metric in MGMT_PAIRS.items():
            row[name] = mgmt_node(c, metric, p, "не напечатано: в пресс-релизе и презентации квартала значения нет")
            row[name + "_exact"] = mgmt_node(c, metric + "_exact", p, "точного значения в справочнике аналитика эмитента нет")
        for name, metric in MGMT_SINGLE.items():
            row[name] = mgmt_node(c, metric, p, "не раскрыто за этот квартал")
        quarters[p] = row
    last_full = a.year if a.quarter == 4 else a.year - 1
    annual = {}
    for y in range(q_parse(PNL_FIRST)[0], last_full + 1):
        rec = {}
        for name in MGMT_ANNUAL:
            metric = MGMT_PAIRS[name]
            printed = mgmt_node(c, metric, f"{y}FY", "")
            rec[name] = printed if printed["v"] is not None else mgmt_node(
                c, metric + "_exact", f"{y}FY", "годового значения нет ни в документах года, ни в справочнике аналитика")
            if printed["v"] is None and rec[name]["v"] is not None:
                rec[name]["calc"] = "точное значение справочника аналитика (напечатанного годового значения нет); проценты → доли"
        annual[str(y)] = rec
    return {
        "basis": "mgmt", "as_of": a.date,
        "unit": "доли (проценты документа / 100), годовые за квартал; прибыль и капитал — млрд ₽; клиенты — млн",
        "note": "управленческие метрики эмитента в новой методике отчёта: без суффикса — напечатанное в пресс-релизе или "
                "презентации (известно в день отчёта), с суффиксом _exact — точное значение справочника аналитика (выходит "
                "примерно через месяц). roe — операционный ROE эмитента, op_np — операционная прибыль акционеров, op_equity — "
                "операционный капитал на конец квартала. В движок — только через bridge_mgmt_ifrs",
        "quarters": quarters,
        "annual": annual,
        "history_gaps": history_gaps(quarters),
    }


# ------------------------------------------------------------------ bridge_mgmt_ifrs.json

def mean_sd(xs: list[float]) -> tuple[float, float]:
    return statistics.fmean(xs), (statistics.stdev(xs) if len(xs) > 1 else 0.0)


def detrended_sd(ys: list[float]) -> float:
    """Разброс ряда вокруг линейного тренда (n − 2 степени свободы)."""
    n = len(ys)
    xm, ym = (n - 1) / 2, statistics.fmean(ys)
    slope = sum((i - xm) * (y - ym) for i, y in enumerate(ys)) / sum((i - xm) ** 2 for i in range(n))
    return (sum((y - (ym + slope * (i - xm))) ** 2 for i, y in enumerate(ys)) / (n - 2)) ** 0.5


def build_bridge_mgmt(c: Ctx, pnl: dict) -> dict:
    a = c.a
    periods = q_range(PNL_FIRST, a.period)
    window = q_range(BRIDGE_FIRST, a.period)
    loan_books = books_of(loans=True)
    debt_from = q_end(DEBT_SECURITIES_FROM).isoformat()

    def loans(d: str) -> float:
        return sum(c.lines(BOOKS[b]["balance"], d)[0] for b in loan_books)

    def liq(d: str) -> float:
        return c.lines(BOOKS[LIQUIDITY]["balance"], d)[0]

    def iea(d: str, broad: bool = False) -> float:
        sec = c.bal(SECURITIES_BROAD, d) if broad or d < debt_from else c.lines(BOOKS[SECURITIES]["balance"], d)[0]
        return loans(d) + sec + liq(d)

    def mgmt(metric: str, p: str) -> dict:
        exact = mgmt_node(c, metric + "_exact", p, "")
        return exact if exact["v"] is not None else mgmt_node(c, metric, p, "упр. значение квартала не раскрыто")

    ends = lambda p: (q_end(q_prev(p)).isoformat(), q_end(p).isoformat())   # noqa: E731
    q = pnl["quarters"]
    cor, cor_b, cor_ac, cir, nim, nim_broad = [], {}, {}, [], [], {}
    raw: dict[str, dict[str, float]] = {"cor": {}, "cir": {}, "nim_x4": {}}   # разности без округления — для средних
    for p in periods:
        d0, d1 = ends(p)
        days = q_days(p)
        llp = q[p]["llp_debt_fa"]["v"]
        avg_b = (loans(d0) + loans(d1)) / 2
        avg_ac = avg_b - (c.bal("loans_fvtpl", d0) + c.bal("loans_fvtpl", d1)) / 2
        m = mgmt("cor_total", p)
        eng_b, eng_ac = -llp * 365 / days / avg_b, -llp * 365 / days / avg_ac
        by_books = COR_BRIDGE_DENOMINATOR == "books"
        eng = eng_b if by_books else eng_ac
        cor.append({"period": p, "mgmt": m,
                    "engine": node(r6(eng), calc=f"−llp_debt_fa {ru(llp)} × 365/{days} / " + (
                        f"средняя сумма кредитных книг {ru(avg_b, 2)}" if by_books else
                        f"средние кредиты по амортизированной стоимости с лизингом {ru(avg_ac, 2)} (сумма кредитных книг без "
                        "кредитов по справедливой стоимости)")),
                    "gap": node(r6(eng - m["v"]), calc="engine − mgmt"),
                    "engine_books": node(r6(eng_b), calc=f"−llp_debt_fa × 365/{days} / средняя сумма шести кредитных книг "
                                                         f"{ru(avg_b, 2)} — знаменатель движка"),
                    "gap_books": node(r6(eng_b - m["v"]), calc="engine_books − mgmt")})
        raw["cor"][p] = eng - m["v"]
        cor_b[p], cor_ac[p] = eng_b - m["v"], eng_ac - m["v"]
        income = sum(q[p][k]["v"] for k in ("nii", "fees_net", "insurance_net", "misc_net"))
        m = mgmt("cir", p)
        eng = -q[p]["opex"]["v"] / income
        cir.append({"period": p, "mgmt": m,
                    "engine": node(r6(eng), calc=f"−opex {ru(q[p]['opex']['v'])} / (nii + fees_net + insurance_net + misc_net) {ru(income, 3)}"),
                    "gap": node(r6(eng - m["v"]), calc="engine − mgmt")})
        raw["cir"][p] = eng - m["v"]
        if p < NIM_BRIDGE_COMPARABLE_FROM:
            continue
        nii = q[p]["nii"]["v"]
        avg = (iea(d0) + iea(d1)) / 2
        m = mgmt("nim", p)
        mixed = d0 < debt_from
        eng, eng4 = nii * 365 / days / avg, nii * 4 / avg
        nim.append({"period": p, "mgmt": m,
                    "engine": node(r6(eng), calc=f"nii {ru(nii)} × 365/{days} / средние процентные активы движка {ru(avg)}"
                                   + ("; бумаги на концах квартала до " + d_ru(debt_from) + " — с акциями и паями (долговые "
                                      "отдельно не раскрыты)" if mixed else "")),
                    "gap": node(r6(eng - m["v"]), calc="engine − mgmt"),
                    "engine_x4": node(r6(eng4), calc="nii × 4 / средние процентные активы движка — без ряби счёта дней"),
                    "gap_x4": node(r6(eng4 - m["v"]), calc="engine_x4 − mgmt (обе стороны на базе «× 4»)"),
                    "exact_assets": not mixed})
        raw["nim_x4"][p] = eng4 - m["v"]
        nim_broad[p] = nii * 4 / ((iea(d0, True) + iea(d1, True)) / 2) - m["v"]

    def block(key: str, hist: list[dict], definition: str) -> dict:
        gaps = [raw[key][p] for p in window]
        m, sd = mean_sd(gaps)
        return {"method": "additive", "window": [window[0], window[-1]],
                "value": node(r6(m), calc=f"среднее gap по окну {window[0]}–{window[-1]} (n = {len(gaps)})"),
                "sd": node(r6(sd), calc="выборочное стандартное отклонение gap по окну"),
                "n": node(len(gaps), calc="кварталов в окне"), "definition": definition, "history": hist}

    b_cor = block("cor", cor, "CoR в мосте = −llp_debt_fa × 365/d / " + (
        "средняя сумма шести кредитных книг" if COR_BRIDGE_DENOMINATOR == "books" else
        "средние валовые кредиты по амортизированной стоимости с лизингом, без кредитов по справедливой стоимости "
        "(определение листа калибровки ОПУ)") + "; упр. — стоимость риска эмитента: резерв по кредитам × 4 / среднее двух "
        "концов валовых кредитов. Движок считает CoR к сумме шести кредитных книг (с кредитами по справедливой стоимости): "
        "этот вариант — в engine_books, gap_books и value_books")
    m_b, sd_b = mean_sd([cor_b[p] for p in window])
    m_ac, sd_ac = mean_sd([cor_ac[p] for p in window])
    b_cor["value_books"] = node(r6(m_b), calc="то же окно на знаменателе движка — сумме шести кредитных книг (среднее gap_books)")
    b_cor["value_ac_only"] = node(r6(m_ac), calc="то же окно на знаменателе без кредитов по справедливой стоимости "
                                                 "(определение листа калибровки ОПУ)")
    b_cir = block("cir", cir, "C/I движка = −opex / (nii + fees_net + insurance_net + misc_net) на операционном базисе (без переоценки и "
                       "дивидендов пакета; noncore_net в доход не входит); упр. — отношение расходов к доходам эмитента с "
                       "затратами на привлечение")
    year_q = [h for h in nim if h["period"] in a.year_quarters]
    if len(year_q) != len(a.year_quarters) or not all(h["exact_assets"] for h in year_q):
        raise BuildError("мост ЧПМ: в отчётных кварталах года якоря нет точных процентных активов движка")
    g4 = [raw["nim_x4"][h["period"]] for h in year_q]
    series = [nim_broad[p] for p in window if p in nim_broad]
    b_nim = {
        "method": "additive", "window": [a.year_quarters[0], a.year_quarters[-1]],
        "value": node(r6(statistics.fmean(g4)), calc=f"среднее gap_x4 по отчётным кварталам года якоря {a.year_quarters[0]}–"
                      f"{a.year_quarters[-1]} (n = {len(g4)}): мост на нынешнем составе процентных активов, без ряби счёта дней"),
        "sd": node(r6(detrended_sd(series)) if len(series) > 2 else r6(mean_sd(g4)[1]),
                   calc=f"разброс ряда {window[0]}–{window[-1]} (бумаги с акциями и паями, база «× 4») вокруг линейного тренда: "
                        "мост дрейфует вместе с составом процентных активов"),
        "n": node(len(g4), calc="кварталов в окне значения"),
        "definition": "ЧПМ движка = nii × 365/d / средние процентные активы движка (шесть кредитных книг + долговые бумаги + "
                      "ликвидность); упр. — чистая процентная маржа эмитента: ЧПД × 4 / среднее двух концов процентных активов "
                      "эмитента. gap — на act/365 (его сверяет гейт дрейфа моста), gap_x4 — без ряби счёта дней (по нему value)",
        "history": [{k: v for k, v in h.items() if k != "exact_assets"} for h in nim],
    }
    ref = json.loads((c.root / BRIDGE_CHECK).read_text(encoding="utf-8")) if (c.root / BRIDGE_CHECK).exists() else None
    if ref is not None and list(ref.get("window") or [])[-1:] != [a.period]:
        c.check("мосты упр. ↔ движок = листу калибровки ОПУ", True,
                f"не сверяется: лист калибровки посчитан по {(ref.get('window') or ['?'])[-1]}, якорь — {a.period}")
    elif ref is not None:
        pairs = [("CoR на знаменателе листа", m_ac, ref["cor"]["value"]["v"]), ("σ CoR", sd_ac, ref["cor"]["sd"]["v"]),
                 ("C/I", b_cir["value"]["v"], ref["cir"]["value"]["v"]), ("σ C/I", b_cir["sd"]["v"], ref["cir"]["sd"]["v"]),
                 ("ЧПМ", b_nim["value"]["v"], ref["nim"]["value"]["v"]), ("σ ЧПМ", b_nim["sd"]["v"], ref["nim"]["sd"]["v"])]
        bad = [f"{n}: {x:.6f} против {y:.6f}" for n, x, y in pairs if abs(x - y) > 5e-6]
        c.check("мосты упр. ↔ движок = листу калибровки ОПУ", not bad,
                "; ".join(bad) or f"CoR {ru(m_ac * 100, 4)} п.п. на знаменателе листа (на сумме кредитных книг — "
                f"{ru(m_b * 100, 4)} п.п.; в фактах — {ru(b_cor['value']['v'] * 100, 4)}), C/I {ru(b_cir['value']['v'] * 100, 4)} п.п., ЧПМ {ru(b_nim['value']['v'] * 100, 4)} п.п.")
    return {
        "basis": "mgmt↔IFRS", "as_of": a.date, "unit": "доли, годовые",
        "window": [window[0], window[-1]],
        "direction": "to_engine(v) = v + value (additive); gap = engine − mgmt; окно CoR и C/I — window (кварталы после "
                     "присоединения Росбанка), окно ЧПМ — отчётные кварталы года якоря (nim.window)",
        "cor": b_cor, "nim": b_nim, "cir": b_cir,
    }


# ------------------------------------------------------------------ bridge_ras_ifrs.json

RAS_FROM = "2025Q1"             # формы банка сопоставимы с группой с квартала после присоединения Росбанка
F101_IEA = {   # процентные активы банка по форме 0409101 (определение для нау-каста; мост активов у эмитента не калибруется)
    "loans": ["45.0|45.1", "45.2", "441", "442", "443", "444", "445", "446", "447", "448", "449", "450", "451", "453", "454"],
    "interbank": ["32.1", "32.2", "319"],
    "securities": ["501", "502", "504"],
}
F101_REQUIRED = ["45.0|45.1", "45.2", "32.1", "32.2", "501", "502", "504"]
F101_NOTE = ("«45.0|45.1» — 45.0, до января 2024 года — 45.1; кода нет в форме — нулевой остаток; нет обязательного кода — "
             "квартал не считается; 501, 502, 504 — долговые бумаги по справедливой стоимости через прибыль, через прочий "
             "совокупный доход и по амортизированной стоимости")


def build_bridge_ras(c: Ctx, pnl: dict) -> dict:
    a = c.a
    ref = c.sheet_ref(RAS_SHEET, "ЧПД и прибыль банка по форме 0409102 за квартал",
                      title="ЧПД, прибыль и резервы по кварталам в трёх базисах — МСФО группы, банковская группа "
                            "(форма 0409803) и банк (форма 0409102, головная организация группы)", key="ras_pnl_quarterly")
    rows = {q_of_date(r["period_end"]): r for r in c.csv(RAS_SHEET)}
    profit, nii = [], []
    for p in q_range(PNL_FIRST, a.period):
        r = rows.get(p)
        if r is None:
            continue
        op, n = pnl["quarters"][p]["ni_shareholders"], pnl["quarters"][p]["nii"]
        if r["profit_bank_f102_bn"]:
            ras = float(r["profit_bank_f102_bn"])
            profit.append({"period": p, "ras_ni": node(ras, ref, "прибыль банка после налога за квартал, форма 0409102"),
                           "ifrs_ni_sh": node(op["v"], calc=f"pnl_quarterly.{p}.ni_shareholders (операционная прибыль акционеров)"),
                           "ratio": node(r6(op["v"] / ras), calc="ifrs_ni_sh / ras_ni"), "src": ref})
        if r["nii_bank_f102_adj_bn"]:
            ras = float(r["nii_bank_f102_adj_bn"])
            nii.append({"period": p, "ras": node(ras, ref, "ЧПД банка за квартал по форме 0409102: процентные доходы − процентные расходы"),
                        "ifrs": node(n["v"], calc=f"pnl_quarterly.{p}.nii"), "ratio": node(r6(n["v"] / ras), calc="ifrs / ras"),
                        "src": ref})
    if not nii or nii[-1]["period"] != a.period:
        raise BuildError(f"{RAS_SHEET}: нет ЧПД банка за квартал якоря")
    last = nii[-1]["ratio"]["v"]
    since = [x["ratio"]["v"] for x in nii if x["period"] >= RAS_FROM]
    lo, hi = min(x["ratio"]["v"] for x in profit if x["period"] >= RAS_FROM), max(x["ratio"]["v"] for x in profit if x["period"] >= RAS_FROM)
    no_profit = "нет данных: прибыль банка по РСБУ не предсказывает прибыль группы (отношение за кварталы после присоединения " \
                f"Росбанка — от {ru(lo, 2)} до {ru(hi, 1)}); нау-каст прибыли равен ожиданию модели"
    return {
        "basis": "RAS→IFRS", "as_of": a.date, "unit": "млрд ₽ за квартал; отношения — доли",
        "definition": "справочный ряд: ratio = операционная прибыль акционеров группы (МСФО) / прибыль банка по РСБУ за квартал "
                      "(форма 0409102). Моста прибыли нет: by_quarter — без значений",
        "quarters": profit,
        "by_quarter": {str(k): na(no_profit) for k in range(1, 5)},
        "nii": {
            "definition": "ras — ЧПД банка за квартал по форме 0409102 (процентные доходы − процентные расходы); ifrs — ЧПД группы "
                          "МСФО (pnl_quarterly.nii); ratio = ifrs / ras",
            "method": "prev_quarter",
            "method_note": "value — отношение последнего отчётного квартала; ЧПД МСФО квартала = ЧПД банка × value; оценка по мосту — "
                           "эталон журнала прогнозов с весом 0",
            "window": [a.period, a.period],
            "quarters": nii,
            "value": node(last, calc=f"ratio квартала {a.period}"),
            "n": node(1, calc="кварталов в окне"),
            "sd": node(r6(statistics.stdev(since)) if len(since) > 1 else 0.0,
                       calc=f"выборочное стандартное отклонение ratio за {RAS_FROM}–{a.period} (n = {len(since)}): отношение "
                            "снижается от квартала к кварталу"),
            "by_quarter": {str(k): node(last, calc="сезонного моста нет: все кварталы = value") for k in range(1, 5)},
        },
        "iea": {
            "basis": "RAS",
            "definition": "процентные активы банка по форме 0409101: исходящие остатки актива по кодам codes (кредиты, размещённые "
                          "межбанковские кредиты, долговые бумаги) — определение для индикаторов; мост активов не калибруется",
            "codes": F101_IEA, "codes_required": F101_REQUIRED,
            "codes_note": F101_NOTE,
            "value": na("мост процентных активов РСБУ → МСФО не калибруется: оценка маржи по формам банка в прогноз не входит"),
            "by_quarter": {str(k): na("мост процентных активов не калибруется") for k in range(1, 5)},
        },
        "cor": na("нет данных для моста: стоимость риска банка по РСБУ не сопоставима с управленческой стоимостью риска группы; "
                  "нау-каст стоимости риска равен ожиданию модели"),
    }


# ------------------------------------------------------------------ сборка, запись, сверка

def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def key_rate_check(c: Ctx) -> None:
    """Средняя ключевая ставка квартала якоря по дневному ряду — против квартального листа."""
    path = c.root / KEY_RATE_DAILY
    if not path.exists():
        return
    lo, hi = q_end(q_prev(c.a.period)).isoformat(), c.a.date
    days = [float(r["key_rate_pct"]) for r in read_csv(path) if lo < r["date"] <= hi and r["key_rate_pct"]]
    n = q_days(c.a.period)
    c.check("ключевая ставка: средняя квартала якоря по дневному ряду = квартальному листу",
            len(days) == n and abs(sum(days) / n / 100 - c.key_avg(c.a.period)) <= 1e-6,
            f"дней {len(days)} из {n}; {pct(sum(days) / max(len(days), 1) / 100, 4)} против {pct(c.key_avg(c.a.period), 4)}")


def build_ctx(root: Path, anchor: Anchor) -> tuple[dict[str, dict], Ctx]:
    c = Ctx(root, anchor)
    bal = build_balance(c)
    nb = build_nii_books(c, bal)
    pnl = build_pnl(c)
    cap = build_capital(c, bal, pnl)
    sh = build_shares(c)
    div = build_dividends(c, sh, pnl)
    key_rate_check(c)
    files = {
        "balance": bal, "nii_books": nb, "pnl_quarterly": pnl, "capital": cap, "shares": sh, "dividends": div,
        "bridge_mgmt_ifrs": build_bridge_mgmt(c, pnl), "bridge_ras_ifrs": build_bridge_ras(c, pnl),
        "mgmt_quarterly": build_mgmt(c), "guidance": build_guidance(c, pnl, div),
    }
    files["anchor"] = build_anchor(c)                  # последним: реестр документов собран всеми узлами
    return {k: files[k] for k in BUILT}, c


def build(root: Path, anchor: Anchor) -> tuple[dict[str, dict], list]:
    files, c = build_ctx(root, anchor)
    return files, c.checks


def write(files: dict[str, dict], target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        with open(target / f"{name}.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(dumps(data))


# ------------------------------------------------------------------ файл отчёта квартала (вход перезаякоривания)
#
# Формат — тот, что читает ops/tools/reanchor.py (`quarter-report/1`, docs/REANCHOR.md), с отличиями эмитента:
# период дивиденда вместо года (`dividends_payable_declared: [{period, amount}]`, без `dividends_payable_year`),
# слоты нормативов в смысле банковской группы и флаг оценки (`capital.estimated`, `capital.estimate`,
# `pnl.estimated`), раздел `shares` — размещённые, в обращении и экономически собственные акции.

REPORT_PNL = ("nii", "fees_net", "llp_debt_fa", "insurance_net", "noncore_net", "opex", "pbt", "tax", "ni", "ni_shareholders",
              "misc_net")
REPORT_TOP = ("schema", "period", "as_of", "source", "balance", "interest", "dia", "pnl", "capital", "market", "mgmt", "shares")


def report_from_facts(files: dict[str, dict], *, source: str) -> dict:
    """Файл отчёта квартала из фактов якоря: остатки и проценты книг, строки ОПУ движка, капитал, рынок, упр. метрики."""
    bal, nb, cap, sh = files["balance"], files["nii_books"], files["capital"], files["shares"]
    period = str(files["anchor"]["period"])

    def need(n: dict, where: str) -> float:
        if not isinstance(n, dict) or n.get("v") is None:
            raise BuildError(f"отчёт квартала из фактов: нет числа {where}")
        return float(n["v"])

    row = files["pnl_quarterly"]["quarters"][period]
    pnl: dict = {k: need(row[k], f"pnl_quarterly.{period}.{k}") for k in REPORT_PNL}
    if row.get("oci_fvoci", {}).get("v") is not None:
        pnl["oci_fvoci"] = float(row["oci_fvoci"]["v"])
    if row["ni_shareholders"].get("estimated"):
        pnl["estimated"] = True
    mrow = files["mgmt_quarterly"]["quarters"][period]
    mgmt = {}
    for x in ("nim", "cor", "cir"):
        n = mrow.get(x + "_exact") if (mrow.get(x + "_exact") or {}).get("v") is not None else mrow.get(x)
        if x != "cir" or (n or {}).get("v") is not None:
            mgmt[x] = need(n, f"mgmt_quarterly.{period}.{x}")
    capital = {"n20_0": need(cap["n20_0"]["value"], "capital.n20_0.value"),
               "n20_pre_dividend": bool(cap["n20_0"]["pre_dividend"]),
               "n1_1_bank": need(cap["n1_1_bank"]["value"], "capital.n1_1_bank.value"),
               "basel_cet1": need(cap["basel"]["cet1"], "capital.basel.cet1"),
               "basel_rwa": need(cap["basel"]["rwa"], "capital.basel.rwa"),
               "bank_base_capital": need(cap["bank_base_capital"], "capital.bank_base_capital"),
               "t2": need(cap["t2_recognized"], "capital.t2_recognized"),
               "estimated": bool(cap["n20_0"].get("estimated"))}
    if capital["estimated"]:
        capital["estimate"] = {slot: {k: (v["v"] if isinstance(v, dict) else v) for k, v in cap[slot]["estimate"].items()}
                               for slot in ("n20_0", "n1_1_bank")}
    report = {
        "schema": REPORT_SCHEMA, "period": period, "as_of": str(files["anchor"]["as_of"]), "source": source,
        "balance": {
            "books": {b: need(bal["books"][b], f"balance.books.{b}") for b in BOOKS},
            "loans_fvtpl": need(bal["loans_fvtpl"], "balance.loans_fvtpl"),
            "fvoci": r6(need(bal["securities"]["fvoci_debt"], "balance.securities.fvoci_debt")
                        + need(bal["securities"]["fvoci_repo"], "balance.securities.fvoci_repo")),
            "fvtpl_bonds": need(bal["securities"]["fvtpl_bonds"], "balance.securities.fvtpl_bonds"),
            "allowance": need(bal["allowance_ac"], "balance.allowance_ac"),
            "other_assets": need(bal["other_assets"], "balance.other_assets"),
            "other_assets_fixed": need(bal["other_assets_fixed"], "balance.other_assets_fixed"),
            "other_liabilities": need(bal["other_liabilities"], "balance.other_liabilities"),
            "dividends_payable": need(bal["dividends_payable"], "balance.dividends_payable"),
            "dividends_payable_declared": [{"period": x["period"], "amount": need(x["amount"], "balance.dividends_payable_declared")}
                                           for x in bal.get("dividends_payable_declared") or []],
            "bv_common": need(bal["equity"]["bv_common"], "balance.equity.bv_common"),
            "fvoci_reserve": need(cap["fvoci_reserve"], "capital.fvoci_reserve"),
            "at1": need(bal["equity"]["at1"], "balance.equity.at1"), "nci": need(bal["equity"]["nci"], "balance.equity.nci"),
        },
        "interest": {b: need(nb["books"][b]["interest_q"], f"nii_books.books.{b}.interest_q") for b in BOOKS},
        "dia": need(nb["dia_q"], "nii_books.dia_q"),
        "pnl": pnl,
        "capital": capital,
        "market": {"ofz_curve": {t: need(cap["ofz_curve_anchor"][t], f"capital.ofz_curve_anchor.{t}") for t in CURVE_NODES},
                   "key_avg": need(nb["key_avg_anchor_q"], "nii_books.key_avg_anchor_q")},
        "mgmt": mgmt,
        "shares": {k: need(sh[k], f"shares.{k}") for k in ("issued_total", "outstanding_total", "economic_treasury",
                                                           "issued_ordinary", "outstanding_ordinary")},
        "dividend_decisions": report_decisions(files),
    }
    check_report(report)
    return report


def report_decisions(files: dict[str, dict]) -> list[dict]:
    """Решения собраний о дивиденде, принятые в квартале якоря (позже конца прошлого квартала и не позже якоря), —
    раздел `dividend_decisions` файла отчёта: квартал прибыли, DPS после дробления, день решения, даты реестра и
    срока выплаты, сумма на все размещённые акции."""
    period, as_of = str(files["anchor"]["period"]), str(files["anchor"]["as_of"])
    opened = q_end(q_prev(period)).isoformat()
    out = []
    for h in files["dividends"].get("history") or []:
        if not opened < str(h.get("decided_date") or "") <= as_of:
            continue
        row = {"period": h["period"], "dps": float(h["dps"]["v"]), "decided_date": h["decided_date"]}
        for key in ("record_date", "pay_date"):
            if h.get(key):
                row[key] = h[key]
        if (h.get("pool_declared") or {}).get("v") is not None:
            row["pool_declared"] = float(h["pool_declared"]["v"])
        out.append(row)
    return out


def check_report(report: dict) -> None:
    """Состав и тождества файла отчёта: недостающий ключ или несходящийся баланс — отказ."""
    problems = [f"нет {k}" for k in REPORT_TOP if k not in report]
    if not problems:
        b, p = report["balance"], report["pnl"]
        problems += [f"нет balance.books.{x}" for x in BOOKS if x not in b["books"]]
        problems += [f"нет interest.{x}" for x in BOOKS if x not in report["interest"]]
        problems += [f"нет pnl.{x}" for x in REPORT_PNL if x not in p]
        if not problems:
            assets = sum(b["books"][x] for x in books_of("asset")) - b["allowance"] + b["other_assets"]
            claims = (sum(b["books"][x] for x in books_of("liability")) + b["other_liabilities"] + b["dividends_payable"]
                      + b["bv_common"] + b["at1"] + b["nci"])
            if abs(assets - claims) > 0.5:
                problems.append(f"баланс не сходится: активы {assets:.3f}, обязательства и капитал {claims:.3f}")
            lines = sum(p[k] for k in ("nii", "llp_debt_fa", "fees_net", "insurance_net", "noncore_net", "opex", "misc_net"))
            if abs(lines - p["pbt"]) > 1e-4 or abs(p["pbt"] + p["tax"] - p["ni"]) > 1e-4:
                problems.append("ОПУ не сходится: сумма строк против pbt или pbt + tax против ni")
            if sum(x["amount"] for x in b["dividends_payable_declared"]) > b["dividends_payable"] + 1e-9:
                problems.append("объявленные дивиденды больше остатка к выплате")
        if not isinstance(report["capital"].get("n20_pre_dividend"), bool):
            problems.append("capital.n20_pre_dividend — true или false")
    if problems:
        raise BuildError("отчёт квартала: " + "; ".join(problems))


def write_report(files: dict[str, dict], path: Path, *, source: str) -> None:
    report = report_from_facts(files, source=source)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(report))
    print(f"записан отчёт квартала {report['period']} ({REPORT_SCHEMA}): {path}")


# ------------------------------------------------------------------ режим --expected: отчёт квартала → факты
#
# Факты следующего квартала из фактов якоря и файла отчёта квартала — того, что пишет `reanchor.py --expected`
# (ожидание модели). Независимая от `reanchor.py` сборка тех же правил переноса (docs/MODEL.md §15.2): ставки якоря
# несут весь ЧПД; упр. факт квартала входит в историю мостов, их значения продлеваются закрытым кварталом; решения
# собраний закрываемого квартала становятся строками истории дивидендов, объявленное и не выплаченное — списком по
# периодам; строки, которых модель не ведёт, — `null` с причиной.

EXPECTED_TOP = (("period", "balance", "interest", "dia", "pnl", "capital", "market", "mgmt"),
                ("schema", "as_of", "published", "source", "note", "shares", "dividend_decisions"))
EXPECTED_SECTIONS = {
    "balance": (("books", "loans_fvtpl", "fvoci", "fvtpl_bonds", "allowance", "other_assets", "other_liabilities",
                 "dividends_payable", "bv_common", "fvoci_reserve"),
                ("dividends_payable_year", "dividends_payable_declared", "other_assets_fixed", "at1", "nci")),
    "pnl": (("nii", "fees_net", "llp_debt_fa", "insurance_net", "noncore_net", "opex", "pbt", "tax", "ni", "ni_shareholders"),
            ("misc_net", "oci_fvoci", "other_equity_movements", "estimated")),
    "capital": (("n20_0", "n20_pre_dividend", "n1_1_bank", "basel_cet1", "basel_rwa", "bank_base_capital"),
                ("t2", "estimated", "estimate")),
    "market": (("ofz_curve", "key_avg"), ("price_index",)),
    "mgmt": (("nim", "cor"), ("cir",)),
    "shares": ((), ("issued_total", "issued_ordinary", "issued_preferred", "outstanding_total", "outstanding_ordinary",
                    "outstanding_preferred", "economic_treasury")),
}
MGMT_WORDS = {"nim": "чистая процентная маржа", "cor": "стоимость риска", "cir": "отношение расходов к доходам"}
EXPECTED_SUM = ("nii", "llp_debt_fa", "fees_net", "insurance_net", "noncore_net", "opex", "misc_net")   # = pbt


def q_next(p: str) -> str:
    y, k = q_parse(p)
    return f"{y + 1}Q1" if k == 4 else f"{y}Q{k + 1}"


def check_report_shape(report: dict) -> None:
    """Состав файла отчёта: незнакомый или недостающий ключ — отказ (опечатка не должна пройти молча)."""
    if not isinstance(report, dict):
        raise BuildError("отчёт квартала: ожидается словарь JSON")
    if report.get("schema", REPORT_SCHEMA) != REPORT_SCHEMA:
        raise BuildError(f"отчёт квартала: schema {report.get('schema')!r}, нужна {REPORT_SCHEMA!r} (docs/REANCHOR.md)")
    required, optional = EXPECTED_TOP
    problems = [f"нет {k}" for k in required if k not in report]
    problems += [f"незнакомый ключ {k}" for k in report if k not in required + optional]
    for name, (req, opt) in EXPECTED_SECTIONS.items():
        section = report.get(name)
        if section is None:
            continue
        if not isinstance(section, dict):
            problems.append(f"{name} — не словарь")
            continue
        problems += [f"нет {name}.{k}" for k in req if k not in section]
        problems += [f"незнакомый ключ {name}.{k}" for k in section if k not in req + opt]
    for where, block in (("balance.books", (report.get("balance") or {}).get("books")), ("interest", report.get("interest"))):
        if isinstance(block, dict):
            problems += [f"нет {where}.{b}" for b in BOOKS if b not in block]
            problems += [f"незнакомая книга {where}.{b}" for b in block if b not in BOOKS]
        elif block is not None:
            problems.append(f"{where} — не словарь по книгам")
    curve = (report.get("market") or {}).get("ofz_curve")
    if isinstance(curve, dict):
        problems += [f"нет market.ofz_curve.{t}" for t in CURVE_NODES if t not in curve]
    if problems:
        raise BuildError("отчёт квартала: " + "; ".join(problems))
    if not isinstance(report["capital"]["n20_pre_dividend"], bool):
        raise BuildError("отчёт квартала: capital.n20_pre_dividend — true или false")
    if (report["capital"].get("estimated") is True) != ("estimate" in report["capital"]):
        raise BuildError("отчёт квартала: capital.estimate — блок оценки есть тогда и только тогда, когда estimated: true")


def expected_facts(prev: dict[str, dict], report: dict, *, name: str, sha: str) -> tuple[dict[str, dict], list]:
    """Факты нового якоря (файлы сборщика) из фактов прежнего якоря `prev` и отчёта следующего квартала `report`.
    Возвращает (файлы, сверки). Чистая функция: вход не меняет."""
    checks: list[tuple[str, bool, str]] = []
    check_report_shape(report)
    old, new = Anchor(str(prev["anchor"]["period"])), Anchor(str(report["period"]))
    if new.period != q_next(old.period):
        raise BuildError(f"отчёт квартала — за {new.period}, факты стоят на {old.period}: нужен отчёт следующего "
                         f"квартала ({q_next(old.period)})")
    if "as_of" in report and str(report["as_of"]) != new.date:
        raise BuildError(f"отчёт квартала: as_of {report['as_of']} — не конец квартала {new.period} ({new.date})")

    def has(path: str) -> bool:
        try:
            return dig(report, path) is not None
        except KeyError:
            return False

    def num(path: str) -> float:
        x = dig(report, path)
        if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x or abs(x) == float("inf"):
            raise BuildError(f"отчёт квартала: {path} — не число ({x!r})")
        return float(x)

    def ref(path: str) -> str:
        return f"{name}, {path}, sha256 {sha[:16]}"

    def en(path: str, what: str, *, value: float | None = None, **extra) -> dict:
        """Узел из отчёта квартала — с точностью файла отчёта (девять знаков): число — ожидание модели, не отчётность."""
        return node(r9(num(path) if value is None else value), src=ref(path), calc=f"отчёт квартала: {what}", **extra)

    def calc(v: float, how: str, **extra) -> dict:
        return node(r9(v), calc=f"отчёт квартала: {how}", **extra)

    def kept(n: dict, **extra) -> dict:
        """Величина, которую отчёт квартала не называет, а модель не двигает: значение прежнего якоря."""
        if n.get("v") is None:
            return dict(n)
        return node(n["v"], calc=f"как на {d_ru(old.date)}: отчёт квартала величину не называет", **extra)

    def none(why: str, **extra) -> dict:
        return na(f"нет данных: отчёт квартала строку не несёт — {why}", **extra)

    out = {k: copy.deepcopy(prev[k]) for k in BUILT}
    d, days = new.date, q_days(new.period)
    on, kq = d_ru(d), q_ru(new.period)
    assets_b, liabs_b, loans_b = books_of("asset"), books_of("liability"), books_of(loans=True)

    # ---------------- balance.json
    pb, bal = prev["balance"], out["balance"]
    bal["as_of"] = d
    book = {b: num(f"balance.books.{b}") for b in BOOKS}
    for b in BOOKS:
        bal["books"][b] = en(f"balance.books.{b}", f"остаток книги «{BOOKS[b]['name']}» на {on}")
    given = {FV_NODE: num("balance.loans_fvtpl"), "securities.fvtpl_bonds": num("balance.fvtpl_bonds")}
    f_old = [float(dig(pb, p)["v"]) for p in FVOCI_NODES]
    given[FVOCI_NODES[0]] = r9(num("balance.fvoci") * f_old[0] / sum(f_old))
    given[FVOCI_NODES[1]] = r9(num("balance.fvoci") - given[FVOCI_NODES[0]])
    for b, spec in BOOKS.items():
        nodes = spec.get("nodes") or {}
        whole = {ln for ls in nodes.values() for ln in ls} == set(spec["balance"])     # узлы раскладывают книгу целиком
        free = [p for p in nodes if p not in given]
        olds = {p: float(dig(pb, p)["v"]) for p in nodes}
        rest = book[b] - sum(given[p] for p in nodes if p in given) if whole else book[b]
        base = sum(olds[p] for p in free) if whole else float(pb["books"][b]["v"])
        if whole and rest < -0.05:
            raise BuildError(f"отчёт квартала: строки книги {b}, заданные отдельно, больше её остатка")
        vals = {p: r9(rest * olds[p] / base) for p in free}
        if whole and free:
            vals[free[-1]] = r9(rest - sum(vals[p] for p in free[:-1]))
        for p in nodes:
            if p in given:
                what = "balance.loans_fvtpl" if p == FV_NODE else "balance.fvoci" if p in FVOCI_NODES else "balance.fvtpl_bonds"
                put(bal, p, node(given[p], src=ref(what), calc=f"отчёт квартала: строка книги «{spec['name']}» на {on}"
                                 + (f" — долей строки на {d_ru(old.date)}" if p in FVOCI_NODES else "")))
            else:
                put(bal, p, node(vals[p], src=ref(f"balance.books.{b}"),
                                 calc=f"отчёт квартала: остаток книги «{spec['name']}» × доля строки на {d_ru(old.date)} — "
                                      "модель ведёт книгу одной суммой"))
    for spec in (OTHER_ASSETS, OTHER_LIABILITIES):
        for s in spec.values():
            if s.get("reference"):
                put(bal, s["reference"], none("часть прочих активов и обязательств модель отдельно не ведёт"))
    bal["allowance_ac"] = en("balance.allowance", f"резерв по кредитам и лизингу на {on} (величиной)")
    bal["other_assets"] = en("balance.other_assets", f"прочие активы на {on}")
    fixed0 = pb["other_assets_fixed"]
    bal["other_assets_fixed"] = (en("balance.other_assets_fixed", f"постоянные прочие активы на {on}")
                                 if has("balance.other_assets_fixed") else kept(fixed0))
    share = bal["other_assets_fixed"]["v"] / fixed0["v"] if fixed0["v"] else 0.0
    bal["other_assets_fixed_parts"] = {k: calc(v["v"] * share, f"часть постоянных прочих активов — долей на {d_ru(old.date)}")
                                       for k, v in pb["other_assets_fixed_parts"].items()}
    bal["other_assets_parts"] = {k: none("разбивку прочих активов модель не ведёт") for k in pb["other_assets_parts"]}
    bal["other_liabilities"] = en("balance.other_liabilities", f"прочие обязательства на {on} (без дивидендов к выплате)")
    bal["other_liabilities_parts"] = {k: none("разбивку прочих обязательств модель не ведёт")
                                      for k in pb["other_liabilities_parts"]}
    bal["dividends_payable"] = en("balance.dividends_payable", f"дивиденды к выплате на {on}")
    declared = dig(report, "balance.dividends_payable_declared") if has("balance.dividends_payable_declared") else []
    bal["dividends_payable_declared"] = [
        {"period": str(x["period"]), "amount": node(r6(float(x["amount"])), src=ref("balance.dividends_payable_declared"),
                                                     calc=f"отчёт квартала: объявлено и не выплачено на {on}")}
        for x in declared]
    eq, peq = bal["equity"], pb["equity"]
    for k in ("at1", "nci"):
        eq[k] = en(f"balance.{k}", f"{k} на {on}") if has(f"balance.{k}") else kept(peq[k])
    eq["bv_common"] = en("balance.bv_common", f"капитал акционеров на {on}")
    bv, at1, nci = eq["bv_common"]["v"], eq["at1"]["v"], eq["nci"]["v"]
    eq["total"] = calc(bv + at1 + nci, "bv_common + at1 + nci")
    for k in EQUITY_PARTS:
        eq[k] = none("компонент капитала модель отдельно не ведёт")
    eq["fvoci_reserve"] = en("balance.fvoci_reserve", f"фонд переоценки бумаг после налога на {on}")
    al, oa = bal["allowance_ac"]["v"], bal["other_assets"]["v"]
    sum_a, sum_l = sum(book[b] for b in assets_b), sum(book[b] for b in liabs_b)
    total_a = sum_a - al + oa
    total_l = sum_l + bal["other_liabilities"]["v"] + bal["dividends_payable"]["v"]
    bal["total_assets"] = calc(total_a, "Σ книг активов − резерв + прочие активы")
    bal["total_liabilities"] = calc(total_l, "Σ книг пассивов + прочие обязательства + дивиденды к выплате")
    checks.append(("отчёт квартала: активы = обязательства + капитал", abs(total_a - (total_l + eq["total"]["v"])) < 0.05,
                   f"активы {ru(total_a)}, обязательства и капитал {ru(total_l + eq['total']['v'])}"))
    listed = sum(x["amount"]["v"] for x in bal["dividends_payable_declared"])
    checks.append(("отчёт квартала: объявленные и не выплаченные дивиденды — часть остатка к выплате",
                   listed <= bal["dividends_payable"]["v"] + 1e-6 and 0 <= bal["other_assets_fixed"]["v"] <= oa,
                   f"по периодам {ru(listed, 3)} из {ru(bal['dividends_payable']['v'], 3)}; постоянные прочие активы "
                   f"{ru(bal['other_assets_fixed']['v'])} из {ru(oa)}"))
    if new.year != old.year:                           # новый год якоря: концы прошлого года — прежний якорь
        ends = {}
        for seg in ("corporate", "retail"):
            names = [b for b in loans_b if BOOKS[b]["segment"] == seg]
            ends[f"loans_{seg}"] = node(r6(sum(float(pb["books"][b]["v"]) for b in names)),
                                        calc=f"кредитные книги сегмента на {d_ru(old.date)}: balance.json фактов {old.period}")
        bal["prev_year_end"] = {"as_of": old.date, **ends}
    loans, funds = sum(book[b] for b in loans_b), sum(book[b] for b in (RETAIL_CURRENT, RETAIL_TERM, "corp_funds"))
    bal["iea"] = calc(sum_a, "процентные активы движка: кредитные книги + долговые бумаги + ликвидность")
    bal["history"][new.period] = {
        "date": d, "bv_common": calc(bv, "balance.equity.bv_common"), "loans": calc(loans, "сумма кредитных книг"),
        "loans_ac_gross": calc(loans, "= loans: отдельной книги кредитов по справедливой стоимости нет"),
        "loans_fvtpl": calc(given[FV_NODE], "balance.loans_fvtpl (справочно: внутри корпоративной книги)"),
        "funds": calc(funds, "средства клиентов: текущие счета и срочные вклады физлиц + средства бизнеса"),
        "iea": calc(sum_a, "balance.iea"), "total_assets": calc(total_a, "balance.total_assets"),
    }

    # ---------------- nii_books.json: ставки якоря несут весь ЧПД
    pn, nb = prev["nii_books"], out["nii_books"]
    nb.update(as_of=d, period=new.period, days=node(days, calc=f"дней в квартале {kq} (act/365)"), rates_carry_residual=True)
    interest = {b: abs(num(f"interest.{b}")) for b in BOOKS}
    nii, dia = num("pnl.nii"), abs(num("dia"))
    residual, scale = carry_scale(interest, nii, dia)
    inc, exp = sum(interest[b] for b in assets_b), sum(interest[b] for b in liabs_b)
    checks.append(("отчёт квартала: проценты книг дают ЧПД отчёта (остаток вне книг — меньше 10 % ЧПД)",
                   abs(residual) < 0.10 * abs(nii), f"Σ книг − страхование вкладов {ru(nii - residual)}, ЧПД {ru(nii)}, "
                                                    f"остаток {ru(residual, 3)}"))
    for b in BOOKS:
        bo, bc = float(pb["books"][b]["v"]), book[b]
        avg = (bo + bc) / 2
        asset = b in assets_b
        how = (f"interest_q × (1 + остаток ЧПД {ru(residual, 3)} / Σ процентов книг активов {ru(inc)}) / balance_avg × 365/{days}: "
               "ставка книги активов несёт долю процентов вне книг") if asset else f"interest_q / balance_avg × 365/{days}"
        nb["books"][b] = {
            "balance_open": node(bo, calc=f"остаток книги на {d_ru(old.date)} (balance.books.{b} фактов {old.period})"),
            "balance_close": node(r9(bc), calc=f"остаток книги на {on} (balance.books.{b})"),
            "balance_avg": node(r9(avg), calc="(balance_open + balance_close) / 2"),
            "interest_q": en(f"interest.{b}", f"проценты книги за {kq} (величиной)", value=interest[b]),
            "rate_anchor": node(round(interest[b] * (scale if asset else 1.0) / avg * 365 / days, 9), src=ref(f"interest.{b}"),
                                calc=f"отчёт квартала: {how}"),
        }
    iea_avg = sum((float(pb["books"][b]["v"]) + book[b]) / 2 for b in assets_b)
    nb.update(
        interest_assets_q=calc(inc, "Σ interest_q книг активов"),
        interest_liabilities_q=calc(exp, "Σ interest_q книг пассивов (величиной)"),
        other_interest_net_q=calc(residual, "остаток: nii_q − (Σ процентов книг активов − Σ пассивов − dia_q); разнесён по "
                                            "ставкам книг активов (rates_carry_residual)"),
        dia_q=en("dia", f"расходы на страхование вкладов за {kq}, величиной", value=dia),
        nii_q=en("pnl.nii", f"ЧПД за {kq}"),
        iea_avg=calc(iea_avg, "Σ balance_avg книг активов"),
        nim_eng_q=node(round(nii * 365 / days / iea_avg, 9), calc=f"отчёт квартала: nii_q × 365/{days} / iea_avg (ЧПМ базиса движка)"),
        current_share_anchor=node(round(book[RETAIL_CURRENT] / (book[RETAIL_CURRENT] + book[RETAIL_TERM]), 9),
                                  calc="отчёт квартала: текущие счета физлиц / (текущие счета + срочные вклады) на якоре"),
        key_avg_anchor_q=en("market.key_avg", f"средняя ключевая ставка за {kq}"),
    )

    # ---------------- pnl_quarterly.json
    pq = out["pnl_quarterly"]
    pq["as_of"] = d
    last_row = prev["pnl_quarterly"]["quarters"][old.period]
    row = {k: none("строку отчёта модель отдельно не ведёт") for k, v in last_row.items() if isinstance(v, dict) and "v" in v}
    for k in EXPECTED_SECTIONS["pnl"][0]:
        row[k] = en(f"pnl.{k}", f"строка движка за {kq} (операционный базис)")
    for k in ("oci_fvoci", "other_equity_movements"):
        if has(f"pnl.{k}"):
            row[k] = en(f"pnl.{k}", f"движение капитала за {kq}")
    lines = sum(row[k]["v"] for k in EXPECTED_SUM if k != "misc_net")
    row["misc_net"] = (en("pnl.misc_net", f"прочие строки за {kq}") if has("pnl.misc_net")
                       else calc(row["pbt"]["v"] - lines, "pbt − (nii + llp_debt_fa + fees_net + insurance_net + noncore_net + opex)"))
    p = {k: row[k]["v"] for k in EXPECTED_SECTIONS["pnl"][0] + ("misc_net",)}
    row["ni_nci"] = calc(p["ni"] - p["ni_shareholders"], "ni − ni_shareholders")
    row["dia"] = calc(dia, "nii_books.dia_q: расходы на страхование вкладов, величиной")
    row["at1_coupon"] = kept(last_row["at1_coupon"])
    row["key_avg"] = en("market.key_avg", f"средняя ключевая ставка за {kq}")
    if dig(report, "pnl").get("estimated") is True:    # прибыль квартала — напечатанное значение: точное придёт позже
        for k in ("ni_shareholders", "ni", "ni_nci", "pbt", "tax", "misc_net", "noncore_net"):
            row[k]["estimated"] = True
    pq["quarters"][new.period] = row
    s = sum(p[k] for k in EXPECTED_SUM)
    checks.append((f"отчёт квартала: прибыль до налога {kq} = сумме строк; прибыль = прибыль до налога + налог; расходы — "
                   "со знаком минус", abs(s - p["pbt"]) < 0.05 and abs(p["pbt"] + p["tax"] - p["ni"]) < 0.05 and p["opex"] < 0,
                   f"Σ строк {ru(s, 2)} против {ru(p['pbt'], 2)}; налог {ru(p['tax'], 2)}, прибыль {ru(p['ni'], 2)}"))

    # ---------------- capital.json
    cap0, cap = prev["capital"], out["capital"]
    cap["as_of"] = d
    estimated = dig(report, "capital").get("estimated") is True
    flag = {"estimated": True} if estimated else {}
    form = cap0["n20_0"]["basis"].split(":")[0]
    t2 = (en("capital.t2", f"регуляторные инструменты группы без прибыли на {on}", basis=form) if has("capital.t2")
          else kept(cap0["t2_recognized"], basis=form))
    cet1, rwa, base = num("capital.basel_cet1"), num("capital.basel_rwa"), num("capital.bank_base_capital")
    pre = bool(dig(report, "capital.n20_pre_dividend"))
    for slot, what in (("n20_0", "Н20.0"), ("n1_1_bank", "Н20.1")):
        block = {"basis": cap0[slot]["basis"], "value": en(f"capital.{slot}", f"{what} банковской группы на {on}", **flag),
                 "as_of": d, "estimated": estimated}
        if estimated:
            est = dig(report, f"capital.estimate.{slot}")
            block["estimate"] = {"bank_value": node(float(est["bank_value"]), src=ref(f"capital.estimate.{slot}.bank_value"),
                                                    calc="норматив банка на дату якоря"),
                                 "spread": node(float(est["spread"]), src=ref(f"capital.estimate.{slot}.spread"),
                                                calc="норматив группы − норматив банка на последнюю общую дату"),
                                 "spread_as_of": str(est["spread_as_of"])}
        cap[slot] = block
    cap["n20_0"]["pre_dividend"] = pre
    cap["n20_0"]["pre_dividend_note"] = ("норматив — до вычета объявленных дивидендов из регуляторного капитала" if pre else
                                         "объявленных и не вычтенных из норматива дивидендов на якоре нет")
    cap["n20_2"] = none("третий норматив группы модель не ведёт", basis=form)
    cap["bank_base_capital"] = en("capital.bank_base_capital", f"базовый капитал банковской группы на {on} (слот ядра)",
                                  basis=form, **flag)
    total = cet1 + t2["v"]
    cap["group_capital"] = {"basis": form, "total": calc(total, "basel.cet1 + t2_recognized", **flag),
                            "base": calc(base, "bank_base_capital", **flag), "additional": calc(t2["v"], "t2_recognized", **flag),
                            "supplementary": none("дополнительный капитал группы модель не ведёт")}
    cap["basel"] = {"basis": cap0["basel"]["basis"], "as_of": d,
                    "cet1": en("capital.basel_cet1", f"капитал группы без регуляторных инструментов на {on}", **flag),
                    "rwa": en("capital.basel_rwa", f"активы, взвешенные по риску, на {on}", **flag),
                    "cet1_ratio": calc(cet1 / rwa, "basel.cet1 / basel.rwa", **flag),
                    "total_ratio": calc(total / rwa, "group_capital.total / basel.rwa", **flag)}
    cap["t2_recognized"] = t2
    cap["fvoci_reserve"] = en("balance.fvoci_reserve", "фонд переоценки бумаг после налога; = balance.equity.fvoci_reserve",
                              basis="IFRS")
    cap["ofz_curve_anchor"] = {"basis": "отчёт квартала (у ожидаемого отчёта — кривая миров слоя «свой взгляд»)", "as_of": d,
                               "convention": cap0["ofz_curve_anchor"]["convention"],
                               **{t: en(f"market.ofz_curve.{t}", f"бескупонная доходность ОФЗ {t} лет на {on}") for t in CURVE_NODES}}
    cap["basel_ifrs"] = {"basis": cap0["basel_ifrs"]["basis"], "as_of": d,
                         **{k: none("примечание об управлении капиталом — только в отчётности")
                            for k, v in cap0["basel_ifrs"].items() if isinstance(v, dict)}}
    cap["history"].append({
        "period": new.period, "date": d, "n20_0": calc(cap["n20_0"]["value"]["v"], "capital.n20_0.value", basis=form, **flag),
        "n20_1": calc(cap["n1_1_bank"]["value"]["v"], "capital.n1_1_bank.value", basis=form, **flag),
        "n20_2": none("третий норматив группы модель не ведёт", basis=form),
        "capital_total": calc(total, "group_capital.total", basis=form, **flag),
        "capital_base": calc(base, "bank_base_capital", basis=form, **flag),
        "capital_additional": calc(t2["v"], "t2_recognized", basis=form, **flag),
        "capital_supplementary": none("дополнительный капитал группы модель не ведёт", basis=form),
        "rwa_imputed": calc(rwa, "basel.rwa", basis=form, **flag)})
    cap.pop("core_form_check", None)                   # сверка формой ядра на ключах листа капитала — только из листов
    checks.append(("отчёт квартала: вычеты якоря (капитал акционеров − капитал группы без инструментов) положительны",
                   0 < bv - cet1 < bv, ru(bv - cet1, 3)))

    # ---------------- shares.json
    out["shares"]["as_of"] = d
    for k in EXPECTED_SECTIONS["shares"][1]:
        if has(f"shares.{k}"):
            out["shares"][k] = en(f"shares.{k}", f"число акций на {on}, млн шт.")

    # ---------------- dividends.json: решения закрываемого квартала — строки истории; затравка реестра
    div = out["dividends"]
    div["as_of"] = d
    rows = {h["period"]: h for h in div["history"]}
    n_iss = float(out["shares"]["issued_total"]["v"])
    seeded = {s_["period"] for s_ in div["register_seed"]}
    for i, x in enumerate(dig(report, "dividend_decisions") if has("dividend_decisions") else []):
        per, dps = str(x["period"]), float(x["dps"])
        where = f"dividend_decisions.{i}"
        if not old.date < str(x["decided_date"]) <= d:
            raise BuildError(f"отчёт квартала: {where}.decided_date {x['decided_date']} — решение закрываемого квартала: позже "
                             f"{d_ru(old.date)} и не позже {on}")
        h = rows.get(per)
        if h is None:
            h = {"year": q_parse(per)[0], "period": per}
            div["history"].append(h)
            rows[per] = h
        if h.get("dps") is None or abs(float(h["dps"]["v"]) - dps) > 1e-6:
            h["dps"] = node(dps, src=ref(f"{where}.dps"), calc="отчёт квартала: дивиденд на акцию, ₽")
            h["pool_declared"] = (node(r6(float(x["pool_declared"])), src=ref(f"{where}.pool_declared"),
                                       calc="отчёт квартала: сумма на все размещённые акции")
                                  if x.get("pool_declared") is not None else
                                  calc(dps * n_iss / 1000, "DPS × размещённые акции / 1000"))
        h["decided_date"] = str(x["decided_date"])
        for k in ("record_date", "pay_date"):
            if x.get(k) is not None:
                h[k] = str(x[k])
        if x.get("record_date") is not None and str(x["record_date"]) > d and per not in seeded:
            div["register_seed"].append({"year": q_parse(per)[0], "period": per,
                                         "dps": node(dps, src=ref(f"{where}.dps"), calc="отчёт квартала: дивиденд на акцию, ₽"),
                                         "status": "declared", "decided_date": str(x["decided_date"]),
                                         "record_date": str(x["record_date"]), "ex_date": str(x["record_date"]),
                                         **({"pay_date": str(x["pay_date"])} if x.get("pay_date") is not None else {}),
                                         "sources": [f"manual: отчёт квартала {new.period} ({name})"]})
            seeded.add(per)
    div["history"].sort(key=lambda h: h["period"])
    unpaid = {x["period"] for x in bal["dividends_payable_declared"]}
    div["register_seed"] = [s_ for s_ in div["register_seed"]
                            if s_["period"] in unpaid or not (s_.get("ex_date") or s_.get("record_date"))
                            or str(s_.get("ex_date") or s_["record_date"]) > d]
    closed = {h["period"] for h in div["history"] if str(h.get("decided_date") or "9") <= d}
    checks.append(("отчёт квартала: у каждой суммы «объявлено, не выплачено» есть решение не позже якоря",
                   unpaid <= closed, ", ".join(sorted(unpaid)) or "список пуст"))

    # ---------------- bridge_mgmt_ifrs.json и mgmt_quarterly.json
    br = out["bridge_mgmt_ifrs"]
    br["as_of"] = d
    l0 = sum(float(pb["books"][b]["v"]) for b in loans_b)
    i0 = sum(float(pb["books"][b]["v"]) for b in assets_b)
    income = sum(p[k] for k in ("nii", "fees_net", "insurance_net", "misc_net"))
    engine = {"cor": (-p["llp_debt_fa"] * 365 / days / ((l0 + loans) / 2),
                      f"−llp_debt_fa {ru(p['llp_debt_fa'], 3)} × 365/{days} / средняя сумма кредитных книг {ru((l0 + loans) / 2, 2)}"),
              "nim": (nii * 365 / days / ((i0 + sum_a) / 2),
                      f"nii {ru(nii, 3)} × 365/{days} / средние процентные активы движка {ru((i0 + sum_a) / 2)}"),
              "cir": (-p["opex"] / income, f"−opex {ru(p['opex'], 3)} / (nii + fees_net + insurance_net + misc_net) {ru(income, 3)}")}
    mgmt_nodes = {}
    for x_, (eng, how) in engine.items():
        block, value0, n0 = br[x_], float(prev["bridge_mgmt_ifrs"][x_]["value"]["v"]), int(prev["bridge_mgmt_ifrs"][x_]["n"]["v"])
        mg = (en(f"mgmt.{x_}", f"упр. {MGMT_WORDS[x_]} за {kq}") if has(f"mgmt.{x_}")
              else calc(eng - value0, f"упр. базис через мост: engine − bridge_mgmt_ifrs.{x_}.value фактов {old.period}"))
        mgmt_nodes[x_] = mg
        gap = eng - mg["v"]
        line = {"period": new.period, "mgmt": dict(mg), "engine": node(round(eng, 9), calc=how),
                "gap": node(round(gap, 9), calc="engine − mgmt")}
        level = gap
        if x_ == "cor":
            line["engine_books"] = node(round(eng, 9), calc="знаменатель движка — сумма шести кредитных книг: тот же engine")
            line["gap_books"] = node(round(gap, 9), calc="engine_books − mgmt")
        if x_ == "nim":
            eng4 = eng * 4 * days / 365
            level = eng4 - mg["v"]
            line["engine_x4"] = node(round(eng4, 9), calc="nii × 4 / средние процентные активы движка — без ряби счёта дней")
            line["gap_x4"] = node(round(level, 9), calc="engine_x4 − mgmt (обе стороны на базе «× 4»)")
        block["history"].append(line)
        if x_ == "nim" and new.year != old.year:       # окно значения моста ЧПМ — отчётные кварталы года якоря
            block["window"], n1 = [new.period, new.period], 1
            block["value"] = node(round(level, 9), calc=f"gap_x4 первого отчётного квартала года якоря {new.period} (n = 1)")
        else:
            block["window"], n1 = [block["window"][0], new.period], n0 + 1
            block["value"] = node(round((value0 * n0 + level) / n1, 9),
                                  calc=f"среднее по окну {block['window'][0]}–{new.period}: значение фактов {old.period} "
                                       f"продлено кварталом (n = {n1})")
        block["n"] = node(n1, calc="кварталов в окне")
        block["sd"] = none("разброс по окну считается из листов этапа 1")
        if x_ == "cor":
            block["value_books"] = dict(block["value"])
            block["value_ac_only"] = none("вариант на знаменателе без кредитов по справедливой стоимости — из листов этапа 1")
        checks.append((f"отчёт квартала: мост «{MGMT_WORDS[x_]}» упр. ↔ движок", True,
                       f"{ru(value0 * 100, 4)} → {ru(block['value']['v'] * 100, 4)} п.п. (n = {n1})"))
    br["window"] = [br["window"][0], new.period]
    mq = out["mgmt_quarterly"]
    mq["as_of"] = d
    mrow = {k: none("управленческую метрику модель не ведёт") for k in prev["mgmt_quarterly"]["quarters"][old.period]}
    for x_ in ("nim", "cor", "cir"):
        mrow[x_] = dict(mgmt_nodes[x_])
    mrow["op_np"] = calc(p["ni_shareholders"], "pnl_quarterly: операционная прибыль акционеров — прибыль движка")
    mq["quarters"][new.period] = mrow

    # ---------------- bridge_ras_ifrs.json, guidance.json: состав прежний
    out["bridge_ras_ifrs"]["as_of"] = d
    out["bridge_ras_ifrs"]["note"] = (f"отчёт квартала {new.period}: формы банка за квартал не собраны — мосты по {old.period} "
                                      "(ядро их не читает)")
    checks.append(("гайденс — как в фактах прежнего якоря", True,
                   f"год гайденса {out['guidance']['year']}" + ("" if int(out["guidance"]["year"]) == new.year else
                                                              f" при якоре {new.period}: гайденс нового года — из листов этапа 1")))

    # ---------------- anchor.json: отчёт — документ реестра
    an = out["anchor"]
    an.update(as_of=d, period=new.period,
              note=(f"ЯКОРЬ ИЗ ОТЧЁТА КВАРТАЛА (сухой прогон перезаякоривания, docs/MODEL.md §15.2): числа {new.period} — из файла "
                    f"«{name}» (у ожидаемого отчёта — ожидание модели, не отчётность); кварталы по {old.period} — факты. "
                    "В data/facts не кладётся"),
              expected={"period": new.period, "from_anchor": old.period, "report": name, "sha256": sha,
                        "source": "; ".join(str(report[k]) for k in ("source", "note") if report.get(k))})
    an["documents"] = sorted(an["documents"] + [{
        "key": f"quarter_report_{new.period}", "file": None, "sha256": sha, "url": None,
        "title": f"Отчёт квартала {new.period} (quarter-report/1) — вход сухого прогона перезаякоривания; не отчётность",
    }], key=lambda r: (r["key"], r["sha256"]))
    return {k: out[k] for k in BUILT}, checks


def main_expected(a) -> int:
    """Режим --expected: факты следующего квартала из фактов якоря и отчёта квартала; только в --out."""
    source = a.facts or FACTS
    if a.out is None or a.out.resolve() == FACTS.resolve():
        print("ПРОВАЛ: --expected пишет только в --out, и это не data/facts (ожидание — не факт)", file=sys.stderr)
        return 1
    try:
        raw = a.expected.read_bytes()
        report = json.loads(raw.decode("utf-8"))
        prev = {k: json.loads((source / f"{k}.json").read_text(encoding="utf-8")) for k in BUILT}
        if a.anchor and isinstance(report, dict) and a.anchor != report.get("period"):
            raise BuildError(f"--anchor {a.anchor}, а отчёт квартала — за {report.get('period')}")
        files, checks = expected_facts(prev, report, name=a.expected.name, sha=hashlib.sha256(raw).hexdigest())
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"ПРОВАЛ: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    except BuildError as e:
        print(f"ПРОВАЛ сборки: {e}", file=sys.stderr)
        return 1
    print(f"якорь {files['anchor']['period']} ({files['anchor']['as_of']}) из фактов {prev['anchor']['period']} и {a.expected.name}")
    for name, ok, detail in checks:
        print(f"{'ок  ' if ok else 'СБОЙ'} {name}: {detail}")
    if any(not ok for _, ok, _ in checks):
        print("ПРОВАЛ: отчёт квартала не сошёлся — файлы не записаны", file=sys.stderr)
        return 1
    manual = {k: (source / f"{k}.json").read_text(encoding="utf-8") for k in MANUAL if (source / f"{k}.json").exists()}
    if a.check:
        diff = [k for k, v in files.items() if not (a.out / f"{k}.json").exists()
                or (a.out / f"{k}.json").read_text(encoding="utf-8") != dumps(v)]
        if diff:
            print(f"РАСХОЖДЕНИЕ с {a.out}: " + ", ".join(f"{k}.json" for k in diff), file=sys.stderr)
            return 1
        print(f"ок: {len(files)} файлов совпали с {a.out}")
        return 0
    write(files, a.out)
    for k, body in manual.items():                     # календарь и аналоги ведутся вручную: копия прежних
        with open(a.out / f"{k}.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
    print(f"записано: {len(files)} файлов в {a.out}" + (f"; скопированы без изменений: {', '.join(manual)}" if manual else ""))
    return 0


# ------------------------------------------------------------------ командная строка

def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Факты эмитента из листов этапа 1 (папка передачи — BANK_HANDOFF_DIR)")
    ap.add_argument("--check", action="store_true", help="сверить с каталогом выхода, не писать")
    ap.add_argument("--out", type=Path, default=None, help="каталог для записи (по умолчанию data/facts)")
    ap.add_argument("--anchor", default=None, metavar="ПЕРИОД",
                    help="квартал якоря вида ГГГГQк (по умолчанию — period из data/facts/anchor.json)")
    ap.add_argument("--report", type=Path, default=None, metavar="ФАЙЛ",
                    help="записать файл отчёта квартала якоря (quarter-report/1) — вход reanchor.py --facts")
    ap.add_argument("--expected", type=Path, default=None, metavar="ФАЙЛ",
                    help="сухой прогон перезаякоривания: факты следующего квартала из фактов якоря и отчёта квартала "
                         "(quarter-report/1, его пишет reanchor.py --expected); пишет только в --out; папка передачи не нужна")
    ap.add_argument("--facts", type=Path, default=None, metavar="КАТАЛОГ",
                    help="с --report: готовый каталог фактов вместо сборки из папки передачи; с --expected: каталог фактов "
                         "прежнего якоря (по умолчанию data/facts)")
    a = ap.parse_args(argv)
    if a.expected is not None:
        return main_expected(a)
    try:
        if a.report is not None and a.facts is not None:
            files = {k: json.loads((a.facts / f"{k}.json").read_text(encoding="utf-8")) for k in BUILT}
            if a.anchor and a.anchor != files["anchor"]["period"]:
                raise BuildError(f"--anchor {a.anchor}, а факты в {a.facts.name} — на {files['anchor']['period']}")
            write_report(files, a.report, source=f"факты сборщика на якоре {files['anchor']['period']}")
            return 0
        root = os.environ.get("BANK_HANDOFF_DIR")
        if not root:
            print("ПРОВАЛ: BANK_HANDOFF_DIR не задан — нужна папка передачи с листами этапа 1", file=sys.stderr)
            return 1
        anchor = Anchor(a.anchor or default_anchor())
        files, checks = build(Path(root), anchor)
    except (OSError, ValueError, KeyError) as e:
        print(f"ПРОВАЛ: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    except BuildError as e:
        print(f"ПРОВАЛ сборки: {e}", file=sys.stderr)
        return 1
    print(f"якорь {anchor.period} ({anchor.date})")
    for name, ok, detail in checks:
        print(f"{'ок  ' if ok else 'СБОЙ'} {name}: {detail}")
    if any(not ok for _, ok, _ in checks):
        print("ПРОВАЛ: сверки не сошлись — файлы не записаны", file=sys.stderr)
        return 1
    target = a.out or FACTS
    if a.check:
        diff = [k for k, v in files.items() if not (target / f"{k}.json").exists()
                or (target / f"{k}.json").read_text(encoding="utf-8") != dumps(v)]
        if diff:
            print(f"РАСХОЖДЕНИЕ с {target}: " + ", ".join(f"{k}.json" for k in diff), file=sys.stderr)
            return 1
        print(f"ок: {len(files)} файлов совпали с {target}")
    else:
        write(files, target)
        print(f"записано: {len(files)} файлов в {target}")
    if a.report is not None:
        try:
            write_report(files, a.report, source=f"листы этапа 1, якорь {anchor.period}")
        except BuildError as e:
            print(f"ПРОВАЛ сборки: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
