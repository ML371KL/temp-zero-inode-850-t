# Факты эмитента: схема узлов

Каталог `data/facts/` — факты МКПАО «Т-Технологии» (тикер T) на якоре: 13 файлов JSON. Одиннадцать пишет
сборщик `ops/tools/build_facts.py` (листы этапа 1 из `$BANK_HANDOFF_DIR`; якорь — аргумент `--anchor`; в CI не
запускается — файлы закоммичены), два — `calendar.json` и `peers.json` — ведутся вручную. Происхождение каждого
числа словами — `docs/FACTS.md`; что из фактов читает ядро — методика, приложение B.

## 1. Общие правила

* **Узел.** Каждое число — узел `{"v": число, "src": …}` или `{"v": число, "calc": …}`; у узла может быть и то и
  другое. `src` — документ и место в нём: страница («с. 6») либо адрес «Лист!Ячейка» справочника аналитика
  эмитента, затем `sha256` и первые 16 знаков хэша файла. Полный хэш, путь в папке передачи, адрес и заголовок
  документа — в реестре `anchor.json → documents` (у ручных файлов — в их `sources`). `calc` — формула из узлов
  или слова о способе.
* **Квартал-разность.** Строка отчётности за квартал, которого документ отдельно не печатает (1-й квартал — из отчёта
  за полугодие, 4-й — из годового), — разность нарастающих итогов. Такой узел несёт и `src`, и `calc`: страница из
  `src` печатает уменьшаемое и вычитаемое, `calc` называет их периоды, редакцию отчёта и сами числа — «разность
  нарастающих итогов 6М2026 − 2К2026 (редакция отчёта за 6М2026): 97,6 − 53,1»; у суммы строк — «каждое слагаемое —
  разность нарастающих итогов …».
* **Нераскрытое** — `{"v": null, "calc": причина}`. Ноль пишется только там, где он раскрыт или следует из
  устройства отчётности (тогда причина — в `calc`).
* **Единицы.** Деньги — млрд ₽; акции — млн шт.; ставки, доли и нормативы — доли единицы (1 п.п. = 0,01); дивиденд на
  акцию — ₽. **Всё «на акцию» — после дробления 1:10** (15.04.2026); исходное значение решения — рядом
  (`dps_pre_split`, `split_factor`).
* **Знаки ОПУ** — как в отчётности: расходы, резервы, налог — со знаком минус. Проценты пассивных книг и взносы на
  страхование вкладов в `nii_books.json` и `dia` — величиной.
* **Базис** — поле `basis` файла: `IFRS`, `mgmt`, `mgmt↔IFRS`, `RAS→IFRS`, `mixed`. В смешанном файле
  (`capital.json`) базис есть у каждого блока и у каждого узла верхнего уровня и истории. Базисы не смешиваются:
  число банковской группы по форме Банка России не складывается с числом МСФО без моста, названного в `calc`.
* **Три прибыли** (подробно — `docs/FACTS.md` §3): отчётная прибыль акционеров по МСФО (`pnl_quarterly → reported`,
  `dividends → years`), операционная прибыль акционеров в определении эмитента (`pnl_quarterly → ni_shareholders` —
  прибыль движка), управленческие значения документов (`mgmt_quarterly → op_np`, `op_np_exact`).
* **Оценочный узел** несёт `"estimated": true`: значение названо до выхода документа (операционная прибыль до
  выхода справочника аналитика; нормативы группы до выхода формы 0409805). Замена оценки фактом — правка фактов
  без смены якоря.
* **Голые числа** вне узлов допустимы только в полях `year` и `split_factor`. Даты — строки ISO.
* Подписи, которые печатает витрина (`calendar → title`, `note`; `guidance → text`, `scope_note`, `event`, `note`;
  `dividends → policy.name`, `text`, `valid_until_note`, `label`; `shares → corporate_actions[].title`; `peers →
  basis`, `name`), написаны словами, даты — с годом.

## 2. Файлы

### 2.1. `anchor.json` (IFRS)

`as_of`, `period` — дата и квартал якоря; `note`; `documents[]` — реестр `{key, file, sha256, url, title}`: все
документы, на которые ссылаются `src` одиннадцати файлов сборщика. `file` — путь от корня папки передачи; сами
документы в репозиторий не кладутся.

### 2.2. `balance.json` (IFRS, на дату якоря)

| Узел | Что это |
|---|---|
| `books.<книга>` — 12 узлов | остатки книг: `cards`, `cash_loans`, `auto`, `mortgage`, `sme_loans`, `corp_loans`, `securities`, `liquidity`, `retail_current`, `retail_term`, `corp_funds`, `wholesale`; состав — в `calc` |
| `loans_fvtpl`, `lease_gross` | справочно: кредиты по справедливой стоимости и лизинг внутри `corp_loans` |
| `allowance_ac` | резерв по кредитам и лизингу, величиной |
| `securities.{fvoci_debt, fvoci_repo, ac, ac_repo, fvtpl_bonds}` | состав книги долговых бумаг (ядро: доли бумаг через прочий совокупный доход и облигаций через прибыль) |
| `securities.{equity_other, yandex_stake}` | справочно: вне книги, в прочих активах |
| `liquidity.{cash, mandatory_reserves, due_from_banks}`; `liquidity.reverse_repo` | состав книги ликвидности; обратное репо — `null` с причиной (внутри двух строк) |
| `funds.{retail_current, retail_term, corp_business, sme}`; `funds.retail_brokerage` | состав книг средств клиентов; брокерские счета физлиц — справочно (в прочих обязательствах) |
| `wholesale.{banks, other_borrowed, nonfin_debt, perpetual_sub}` | состав книги оптового фондирования |
| `other_assets`, `other_liabilities` | остатком до итогов баланса; по строкам отчёта — `other_assets_parts`, `other_liabilities_parts` |
| `other_assets_fixed`, `other_assets_fixed_parts.{yandex_stake, associates}` | постоянные прочие активы (не растут с кредитами) |
| `total_assets`, `total_liabilities` | итоги отчёта о финансовом положении |
| `dividends_payable` | дивиденды к выплате: строка годового отчёта, а на промежуточную дату — расчёт по движению с начала года |
| `dividends_payable_declared[]` | `{period, amount}` — объявленные до якоря и не выплаченные к нему дивиденды закрытых кварталов прибыли; пустой список — таких нет |
| `equity.{total, at1, nci, bv_common}` и компоненты | капитал; `at1` — ноль с причиной (бессрочные займы — обязательство) |
| `prev_year_end.{as_of, loans_corporate, loans_retail}` | кредитные книги на конец прошлого года по сегменту стоимости риска |
| `iea` | процентные активы движка: кредитные книги + долговые бумаги + ликвидность |
| `history.<период>` | концы кварталов: `date`, `bv_common`, `loans`, `loans_ac_gross` (= `loans`), `loans_fvtpl` (справочно), `funds`, `iea`, `total_assets` |

### 2.3. `nii_books.json` (IFRS; квартал якоря)

`period`, `days`, `rates_carry_residual: false`; `books.<книга>.{balance_open, balance_close, balance_avg,
interest_q, rate_anchor}`, `rate_anchor = interest_q / balance_avg × 365 / days`; `interest_assets_q`,
`interest_liabilities_q`; `other_interest_net_q` — проценты вне книг; `dia_q`; `nii_q`; `iea_avg`, `nim_eng_q`;
`current_share_anchor`; `key_avg_anchor_q`.

### 2.4. `pnl_quarterly.json` (IFRS; `profit_basis: "operating"`; `quarters.<период>`)

Строки движка на операционном базисе: `nii`, `fees_net`, `insurance_net`, `llp_debt_fa`, `opex` — строки отчёта;
`misc_net`, `noncore_net`, `pbt`, `tax`, `ni`, `ni_nci` — расчётные; `ni_shareholders` — операционная прибыль
акционеров, строка эмитента. Справочно: `dia`, `at1_coupon` (ноль с причиной), `key_avg`, `fee_income`,
`fee_expense`, `oci_fvoci`, `ci_shareholders`, `fv_loans_credit` (`null`).
`reported.{pbt, tax, ni, ni_shareholders, ni_nci}` — строки отчётности. У кварталов-разностей (§1) формула — в `calc`:
`reported.*`, `llp_debt_fa`, `opex`, `dia`, `fee_income`, `fee_expense`, `oci_fvoci`, `ci_shareholders`,
`investment_block.{reval, nonfin_interest}`.
`investment_block.{reval, dividends, debt_interest, pbt, tax, ni, nci, ni_shareholders, nonfin_interest,
adj_stake_sh, adj_interest_sh}` — исключённое из строк движка (пакет Яндекса): `reported.x = x +
investment_block.x` (для `ni_nci` — `investment_block.nci`); `noncore_net = −investment_block.debt_interest`.

### 2.5. `capital.json` (mixed)

`n20_0.{value, as_of, estimated, pre_dividend, pre_dividend_note, min_with_buffers}` — Н20.0 банковской группы;
`n1_1_bank.{value, as_of, estimated}` — Н20.1 банковской группы (имя слота историческое); `n20_2`;
`bank_base_capital` — базовый капитал группы; `group_capital.{total, base, additional, supplementary}`;
`basel.{cet1, rwa, cet1_ratio, total_ratio}` — слоты ядра: капитал группы без регуляторных инструментов и вменённые
активы, взвешенные по риску; `t2_recognized` — регуляторные инструменты группы; `at1.{amount, coupon_annual,
coupon_quarter}` — нули с причиной; `fvoci_reserve`; `ofz_curve_anchor.{1, 3, 5, 10}`; `basel_ifrs.*` — Базель III
по МСФО (справочно); `instruments[]`, `instruments_total` — бессрочные субординированные займы; `history[]` —
нормативы и капитал группы по концам кварталов; `core_form_check` — сверка сборщика: нормативы якоря формой ядра
на ключах листа калибровки капитала (ядро блок не читает). При оценке до выхода формы у слотов — `estimated: true`
и блок `estimate.{bank_value, spread, spread_as_of}`.

### 2.6. `shares.json` (IFRS; млн шт. после дробления)

`issued_total`, `issued_ordinary`, `treasury_ordinary`, `outstanding_total`, `outstanding_ordinary`;
`depositary_block` — акции без голосов и выплат (в делитель входят); `economic_treasury` — ноль с причиной;
`voting`, `motivation_program`, `par_value`; `by_ticker`; `corporate_actions[]` — `{date, kind, title, src}`, у
дробления — `factor` и `first_trade_date`, у выпуска — `shares_before`, `shares_after`.

### 2.7. `dividends.json` (IFRS)

`policy.{name, doc, doc_title, sha256, approved, approved_by, frequency, cap, threshold, valid_until,
valid_until_note, text, src}` — `cap` 0,30; `threshold` и `valid_until` — `null` с причиной; `doc_title` — название
документа политики словами: его, а не имя файла `doc`, выпуск несёт в `dividends.policy.doc`. `history[]` — одна строка на решение собрания:
`year`, `period` (квартал прибыли), `label`, `dps`, `dps_pre_split`, `split_factor`, `recommended_date`,
`decided_date`, `decided_by`, `record_date`, `last_buy_date`, `ex_date`, `pay_date`, `pay_deadline_others`,
`settlement`, `pool_declared`, `sources[]` (строки «вид: …», виды `manual` и `news`, у каждого решения оба).
`pay_date` — срок выплаты номинальным держателям по решению собрания (10 рабочих дней после реестра),
`pay_deadline_others` — срок прочим лицам реестра (25 рабочих дней); источник обоих — рекомендация совета директоров
или протокол собрания. День фактической выплаты в фактах не хранится: колонка «Дата выплаты» файла эмитента «История
дивидендных выплат» — другая величина (`docs/FACTS.md` §4.6).
`years.<год>.{ni_shareholders, complete, through}` — отчётная прибыль акционеров для проверки потолка политики.
`register_seed[]` — решения с экс-датой позже якоря: поля записи реестра и `status`. `dates_rule`,
`broker_check` — словами; `snapshot` — день снимка листа решений.

### 2.8. `guidance.json` (mgmt)

`year`, `as_of`; `items.{op_np_growth, dps_growth, roe_target}` — узлы с `kind`, `text`, `date`, `event`, `scope`,
у точки — `tol`, у пункта с оговоркой — `scope_note`; `items.{roe, nim, cor_max, cir}` — `null` с причиной;
`history[]` — `{date, key, value, event, note}`.

### 2.9. `mgmt_quarterly.json` (mgmt)

`quarters.<период>`: напечатанное в документах квартала — без суффикса, точное значение справочника аналитика — с
суффиксом `_exact`: `nim`, `cor`, `cir`, `roe`, `op_np`, `op_equity`, `roe_shareholders`, `roe_reported`,
`cost_of_funding`, `clients_total`, `clients_active`; только точное — `cor_cards`, `cor_cash`, `cor_auto`,
`cor_mortgage`, `cor_sme`, `cor_corp`, `cor_lease`; только напечатанное — `asset_yield`.
`annual.<год>.{nim, cor, cir, roe}`.
`history_gaps[] = {period, basis, reason}` — частичные провалы раскрытия отчётной истории выпуска: `period` — квартал
или диапазон `ГГГГQn–ГГГГQn`, `basis` — `mgmt` (у квартала напечатана только часть метрик `nim`, `cor`, `cir`, `roe`)
или `ifrs` (до первого конца квартала истории баланса не считаются капитал, ROE и стоимость риска по МСФО; до первой
формы с нормативами группы нет Н20.0), `reason` — словами для экрана: какая метрика пуста и почему. Список пишет
сборщик из пустых узлов кварталов и из первых кварталов истории баланса и капитала; квартал, у которого базис пуст
целиком, называет сама сборка выпуска.

### 2.10. `bridge_mgmt_ifrs.json` (mgmt↔IFRS)

`window`, `direction`; для `cor`, `nim`, `cir` — `method: "additive"`, `window`, `value`, `sd`, `n`, `definition`,
`history[] = {period, mgmt, engine, gap}`; `to_engine(v) = v + value`. У `nim` в истории ещё `engine_x4`, `gap_x4`
(без ряби счёта дней; по ним `value`). У `cor` знаменатель моста — параметр сборщика: сумма кредитных книг (знаменатель
движка; на нём мост и калибруется) либо кредиты по амортизированной стоимости с лизингом без кредитов по справедливой
стоимости (определение листа калибровки, справочно); история несёт оба варианта
(`engine`, `gap` — выбранный; `engine_books`, `gap_books` — на сумме книг, знаменателе движка), значения обоих — узлы
`value_ac_only` и `value_books`.

### 2.11. `bridge_ras_ifrs.json` (RAS→IFRS)

`quarters[] = {period, ras_ni, ifrs_ni_sh, ratio, src}` — справочный ряд; `by_quarter.{1…4}` — `null` с причиной
(моста прибыли нет). `nii.{definition, method: "prev_quarter", window, quarters[], value, n, sd, by_quarter}` — мост
ЧПД по форме 0409102. `iea` — определение процентных активов по форме 0409101 (`codes`, `codes_required`); `value` —
`null`. `cor` — `null` с причиной.

### 2.12. `calendar.json` (вручную)

`as_of`, `horizon`, `note`, `sources[]`, `events[] = {id, kind, date, title, covers, confirmed, precision, src}` и
необязательные `estimated`, `earliest`, `latest`, `in_book`, `note`. Виды: `ifrs`, `databook`,
`dividend_decision`, `record`, `form805`, `ops_release`, `cbr_rate`, `cbr_forecast`, `call_option`, `deal`,
`regulation`. Событие с `estimated: true` несёт `confirmed: false`, `precision: "window"`, `earliest`, `latest`.

### 2.13. `peers.json` (вручную)

`as_of`, `basis`, `subject_ticker`, `note`, `sources[]`, `banks[] = {ticker, name, basis, bv_date, ni_ltm_period,
bv, bv_prev, ni_ltm, roe_ltm, shares_outstanding, shares_issued, dps_ltm, capital_ratio {name, value, as_of},
src}`. Строки эмитента в файле нет: её собирает выпуск из фактов. `src` строки банка уходит в выпуск (источник
строки таблицы аналогов, без хвостов sha256), поэтому в нём название документа словами, страница и `sha256` с первыми
16 знаками хэша по каждому документу — без имени файла; без хвостов строка не длиннее 120 знаков. У узлов внутри
строки `src` — как у прочих фактов.

## 3. Якорь и параметры сборщика

`python -B ops/tools/build_facts.py [--check] [--anchor <период>] [--out <каталог>] [--report <файл>]`; сухой прогон
перезаякоривания — `--expected <файл отчёта квартала> --out <каталог> [--facts <каталог>]` (§4). Из якоря и
листов выводятся: дата и начало квартала, лист якоря (`stage1/ifrs/ifrs_anchor_<период>.csv`), нарастающий итог,
конец прошлого года, отчётные кварталы года якоря (окно моста ЧПМ), годы проверки потолка, стартовый реестр
(решения с экс-датой позже якоря), статус записи (по дню снимка листа решений).

Состав — три таблицы в начале сборщика: `BOOKS` (книга → строки остатка и процентов, справочные узлы),
`PNL_LINES` с `PNL_REPORTED` и `BLOCK` (строка ОПУ ядра → строки отчёта; блок пакета), `OTHER_ASSETS` и
`OTHER_LIABILITIES` (прочие активы и обязательства; постоянная часть). Параметры сборщика, не привязанные к якорю:

| Параметр | Значение | Что это |
|---|---|---|
| `PNL_FIRST` | 2024Q1 | первый квартал ОПУ в новом формате отчёта |
| `HISTORY_FIRST`, `CAPITAL_HISTORY_FIRST` | 2024Q4 | начало истории баланса и капитала группы |
| `DEBT_SECURITIES_FROM` | 2025Q4 | с этого конца квартала долговые бумаги раскрыты отдельно от акций и паёв |
| `BRIDGE_FIRST` | 2024Q4 | начало окна мостов CoR и C/I |
| `NIM_BRIDGE_COMPARABLE_FROM` | 2024Q2 | первый квартал сопоставимой управленческой маржи |
| `COR_BRIDGE_DENOMINATOR` | books | знаменатель CoR в мосте: `books` — сумма кредитных книг (знаменатель движка), `ac` — без кредитов по справедливой стоимости (лист калибровки ОПУ, справочно) |
| `RATES_CARRY_FROM` | 2026Q3 | с этого якоря ставки книг активов несут и проценты вне книг (`nii_books.rates_carry_residual: true`) — правило перезаякоривания |
| `CAPITAL_KEYS_ANCHOR` | 2026Q2 | квартал, на котором выведены ключи листа капитала: сверка формой ядра (`capital.core_form_check`) — только на нём |
| `RAS_FROM` | 2025Q1 | формы банка сопоставимы с группой с квартала после присоединения Росбанка |
| `POLICY`, `ACTIONS`, `SPLIT_FIRST_TRADE`, `INSTRUMENTS`, `GUIDANCE_ITEMS`, `MGMT_PAIRS` | — | дивидендная политика, подписи корпоративных событий, первый торговый день после дробления, бессрочные займы, пункты гайденса, имена управленческих метрик |

## 4. Файл отчёта квартала (`quarter-report/1`)

`--report <файл>` пишет вход `ops/tools/reanchor.py --facts`: `period`, `as_of`, `source`; `balance.{books,
loans_fvtpl, fvoci, fvtpl_bonds, allowance, other_assets, other_liabilities, dividends_payable,
dividends_payable_declared[], bv_common, fvoci_reserve, at1, nci}`; `interest.<книга>`; `dia`; `pnl` — строки
движка (и `estimated`, если прибыль квартала — оценка); `capital.{n20_0, n20_pre_dividend, n1_1_bank, basel_cet1,
basel_rwa, bank_base_capital, t2, estimated}` (при оценке — `estimate`); `market.{ofz_curve, key_avg}`;
`mgmt.{nim, cor, cir}` — точные значения, а пока их нет — напечатанные; `shares.{issued_total, outstanding_total,
economic_treasury, issued_ordinary, outstanding_ordinary}`; `balance.other_assets_fixed`; `dividend_decisions[]` —
решения собраний, принятые в квартале якоря: `{period, dps, decided_date, record_date, pay_date, pool_declared}`.
Отличия от формы семейства: период дивиденда вместо года (`dividends_payable_declared` и `dividend_decisions` вместо
`dividends_payable_year`), слоты нормативов в смысле банковской группы, флаг оценки, акции одной категории.

`--expected <файл>` читает тот же файл (его пишет и `ops/tools/reanchor.py --expected` — ожидание модели) и строит
из фактов якоря факты следующего квартала — в `--out`, не в `data/facts`: узлы якоря — числа отчёта (`src` — файл
отчёта и его sha256), строки внутри книг — долей строки на прежнем якоре, ставки книг активов — с долей остатка ЧПД,
квартал добавлен в истории, решения отчёта — строками истории дивидендов, значения мостов продлены кварталом;
строки, которых модель не ведёт, — `null` с причиной; `anchor.json` несёт блок `expected` (квартал, прежний якорь,
файл отчёта). Правила — `docs/FACTS.md`, раздел 9.

## 5. Тождества (тесты фактов)

1. `Σ books активов − allowance_ac + other_assets = total_assets`; `Σ books пассивов + other_liabilities +
   dividends_payable + equity.total = total_assets`; `0 ≤ other_assets_fixed ≤ other_assets`;
   `other_assets_fixed = Σ other_assets_fixed_parts`; `Σ dividends_payable_declared ≤ dividends_payable`.
2. `prev_year_end.loans_corporate + loans_retail = history.<конец прошлого года>.loans`.
3. `Σ процентов активных книг − Σ пассивных − dia_q + other_interest_net_q = nii_q`.
4. `pbt = nii + llp_debt_fa + fees_net + insurance_net + noncore_net + opex + misc_net`; `ni = pbt + tax`;
   `ni_shareholders = ni − ni_nci`; `reported = строки движка + investment_block`; `|debt_interest| ≤
   nonfin_interest`.
5. Прибыль движка квартала якоря, сумма за последний полный год и за год якоря нарастающим итогом равны
   операционной прибыли эмитента.
6. Нормативы якоря формой ядра на ключах листа капитала равны нормативам формы 0409805 (`core_form_check`).
7. Дивиденды: `dps × split_factor = dps_pre_split`; `pool_declared = dps × issued_total`; дата реестра — через
   10–20 дней после решения; у записи стартового реестра есть строка истории с тем же периодом.
8. Мосты: `value` — среднее `gap` (у ЧПМ — `gap_x4`) по своему окну; `engine` и `engine_books` воспроизводятся из
   `pnl_quarterly` и `balance.history`.
