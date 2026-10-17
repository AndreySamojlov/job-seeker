"use strict";

// table-engine.js — общий движок интерактивной таблицы: состояние колонок,
// заголовок с сортировкой/скрытием/ресайзом, обёртка с возвратом скрытых
// колонок, закреплённая шапка с лимитом видимых строк.
//
// Что делает. Отвечает за МЕХАНИКУ колонок, а не за смысл ячеек: кто как
// форматирует значение, какие колонки показывать и чем их красить — решает
// вызывающий (домен объявляет, движок рисует, §5 доктрины унификации).
//
// Как используется (контракт):
//   tblColState()                      → {hidden:Set, sortKey, sortDir, widths,
//                                         anchor, focus, filters, search}
//   tblApplyWidths(root, cs)           → разлить ручные ширины по <col> внутри root
//   tblColgroup(cols, cs)              → <colgroup> с data-key на каждой <col>
//   tblHeadCell(col, cs, opts)         → интерактивный <th>
//        opts: { rerender(reason), root, cls?, label?, filterRows?, getValue? } —
//        rerender вызывающего движок зовёт после смены сортировки/скрытия/
//        фильтра, передавая причину ("sort"|"hide"|"filter"); домен вправе её
//        игнорировать (блок сигналов сбрасывает по "filter" страницу пейджера).
//        root — узел, внутри которого живёт таблица (скоуп для ширин); cls —
//        доп. классы (r/accent/…); label — переопределение подписи (строка,
//        Node или массив); filterRows — строки ДО фильтрации, из которых
//        собирается список значений фильтра "values" и верхняя граница «≥ k»
//        фильтра "tiers" (иначе список схлопывался бы до уже выбранного
//        значения); getValue — тот же адаптер значения.
//        col.fixed — колонку нельзя скрыть (нет кнопки «×»).
//        col.filter = "text"|"values"|"range"|"tiers" — объявление фильтра
//        колонки (задача 3): движок рисует воронку в шапке, сам собирает
//        уникальные значения и режет строки. Не объявлен — воронки нет
//        НИКОГДА.
//        col.filterKey — ключ, которым фильтр ЧИТАЕТ значение строки И под
//        которым ХРАНИТ своё состояние в cs.filters (по умолчанию col.key,
//        _tblFilterKey(col) ниже). Несколько колонок с одним filterKey делят
//        ОДНО состояние — переживает смену видимого набора колонок (task-main-
//        191: __score/__hits блока сигналов меняются местами при фокусе
//        правила, а фильтр тяжести обязан пережить переключение).
//        col.filterLabel — заголовок меню воронки и текст подсказки (по
//        умолчанию col.label) — нужен, когда подпись САМОЙ колонки не
//        объясняет, что фильтруется («Правила» сама по себе не читается как
//        «Тяжесть»).
//        col.filterOrder — порядок пунктов фильтра "values" (массив строк);
//        по умолчанию — русская локаль. Значения вне filterOrder идут ПОСЛЕ
//        перечисленных, между собой — тоже русской локалью.
//        Фильтр "values" — МНОЖЕСТВЕННЫЙ (task-main-197, П5 спеки
//        2026-08-18, владелец 18.08: единый механизм, не аддитивный тип):
//        меню — чекбоксы + «Применить»/«Сбросить» (мгновенное применение на
//        каждой галке физически невозможно — apply() закрывает меню). Состояние
//        пишется как {values:[...]}; читается ЛЮБАЯ форма — и новая
//        {values:[...]}, и старая {value:"…"} (drill по категории в блоке
//        сигналов пишет её и продолжает писать ВЕЧНО, это не переходный
//        костыль) — единственная точка разбора формы: _tblFilterValuesOf(st)
//        ниже. Пустой список и отсутствующее/пустое value — «нет ограничения».
//        col.filterTiers — ОБЯЗАТЕЛЬНОЕ объявление фильтра "tiers"
//        (task-main-196): [{key, label, color}] — порядок, подпись и ЦВЕТ
//        кружка объявляет ДОМЕН. Значение строки под таким фильтром — не
//        скаляр, а КАРТА «ключ тира → число» (getValue обязан её отдать);
//        движок рисует по строке на тир (кружок-подпись + <select> «все /
//        ≥ k / нет») и режет строки по счётчикам, НЕ ЗНАЯ, что эти числа
//        значат. Тир с color:null рисуется контурным кружком — движок и здесь
//        не изобретает смысла, а читает декларацию. Все объявленные строки
//        рисуются ВСЕГДА, даже при n = 0 в наборе: исчезнувшая строка сделала
//        бы поставленное ограничение неснимаемым.
//   tblApplyFilters(cols, rows, cs, opts?) → строки после кросс-колоночного
//        поиска (opts.searchKeys) И фильтров колонок; opts.getValue — адаптер.
//        Композиция tblSearchRows + tblFilterRows, обе доступны отдельно.
//   tblFilterValues(rows, col, getValue?) → уникальные непустые значения колонки,
//        отсортированные по col.filterOrder (если объявлен) либо русской локалью
//   tblSearchBar(cs, rerender, opts?)  → <input type=search> НАД таблицей:
//        кросс-колоночный поиск не принадлежит ни одной колонке и потому не
//        воронка, а отдельный элемент управления. opts.root — узел, внутри
//        которого домен перерисует бар (возврат фокуса и каретки).
//   tblSortByColumn(rows, cs, valueOf) → отсортированные строки, либо null,
//        если сортировка по колонке не выбрана (вызывающий берёт свой дефолт).
//        valueOf(row, key) — доступ к значению (у сигналов часть колонок
//        виртуальные: балл правила, число хитов).
//   tblWrap(cs, rerender, exportInfo)  → .tblwrap.tbleng (+ «⊞» возврата скрытых
//        колонок, + «Скачать», если exportInfo:{cols, rows, filename, getValue?,
//        totalRow?} передан) — тулбар живёт в НОРМАЛЬНОМ потоке над лентой (не
//        absolute): якорь в углу, срезаемый overflow-y ленты и спорящий
//        z-index'ом со sticky-шапкой, ломал кликабельность (находка ревью
//        общего шва 2026-08-15) — высота тулбара учтена в tblCapRows
//        (--tbl-max). Класс `tbleng` — признак «это таблица общего движка»
//        (ставит движок САМ, домен не объявляет его никогда, task-main-190):
//        под него в styles.css живут единая плотность строки и закреплённая
//        шапка ЛЮБОЙ таблицы движка, а голый `.tblwrap` (flat-table.js,
//        matrix-table.js — свои раскладки, не зовут tblWrap) их не получает.
//        tblWrap регистрирует умолчание капа — TBL_VISIBLE_ROWS строк — сразу
//        здесь; реально капает ленту уже существующий цикл авторазметки (см.
//        tblCapRows ниже), домен не зовёт капающую функцию сам, пока не
//        решит переопределить число (О1 спеки 2026-08-17).
//        exportInfo.toolsHost — объявленный доменом УЗЕЛ-ХОЗЯИН тулбара: когда
//        он передан, строка кнопок уезжает туда (у GA.MA — в строку табов
//        «Дни/Недели», решение владельца 16.08), а над лентой её нет вовсе.
//        Кнопки при этом те же и строит их движок — домен объявляет МЕСТО, не
//        содержимое (ось 2 доктрины унификации). Свои прежние .tbltools движок
//        из хозяина убирает сам: перерисовка домена не обязана его чистить.
//   tblCapRows(wrap, visibleRows)   → ограничить ленту N строками внутренним
//        скроллом (класс `tblcap`, снимается на ВСЕХ ранних выходах функции —
//        капнутая лента не имеет права пережить своё основание). Закрепление
//        ШАПКИ — с task-main-190 чистый CSS (`.tbleng thead/tfoot th`,
//        styles.css), эта функция сама шапку больше не позиционирует, только
//        считает высоту ленты (строка «Итого» в <tfoot> входит в неё наравне
//        с шапкой — иначе лента показывала бы на строку меньше заявленных
//        visibleRows)
//   tblExportRows(cols, rows, state, opts?) → 2D-массив (шапка + данные) —
//        модель Excel «ячейка хранит значение, формат отвечает за вид»
//        (решение владельца 14.08): значение сырое (по умолчанию
//        row[col.key], БЕЗ форматтера — col.kind красит только экран), пропуск
//        — пустая строка "" (не «—»), единица col.unit уезжает в шапку колонки
//        («СПП, %»). state.hidden исключает скрытые колонки целиком; порядок
//        rows — на совести вызывающего: функция сама не сортирует и не
//        фильтрует, а ЧТО считается «выбранным» решает вызывающий — это НЕ
//        обязано быть страницей на экране (task-main-194, exportInfo.rows у
//        tblWrap ниже — набор может быть шире видимой страницы пейджера).
//        opts.getValue(row, key) — та же идиома, что у
//        tblSortByColumn: опциональный адаптер доступа к значению, когда
//        сырое значение колонки не равно row[key] (день/неделя несут разное
//        «сырое» для одной и той же колонки-идентичности). ИМЯ getValue, не
//        valueOf: свойство "valueOf" есть у ЛЮБОГО объекта (унаследовано от
//        Object.prototype) — потребитель без адаптера получал бы не
//        undefined, а этот унаследованный метод, и движок принимал бы его за
//        адаптер (TypeError внутри клика «Скачать», находка ревью общего шва
//        2026-08-15). opts.totalRow — опциональная итоговая строка («Итого»
//        и т.п.): движок дописывает её ПОСЛЕДНЕЙ через тот же getValue, сам не
//        зная, что это за строка — домен объявляет, движок рисует. Хвост
//        параметров (было: valueOf, totalRow позиционно — симптом уже был
//        виден в собственном тесте задачи 1, null-заглушка на четвёртой
//        позиции) свёрнут в один opts, задача 2 добавляет в него же поле
//        getValue переиспользуемое выделением/буфером — вторая копия правил
//        форматирования не заводится (ЖЁСТКОЕ ТРЕБОВАНИЕ ревью задачи 2).
//   tblExportCsv(cols, rows, state, opts?) → CSV-строка поверх tblExportRows:
//        разделитель ";", десятичная ЗАПЯТАЯ (точкой Excel принял бы число за
//        текст), UTF-8 BOM первым символом (двойной клик открывает без
//        мастера импорта), кавычки/";" в текстовых ячейках экранированы
//        (обрамление + удвоение кавычек); NaN/±Infinity — пустая ячейка, как у
//        null (общий шов — второй потребитель придёт с произвольными
//        данными); текстовая ячейка, начинающаяся с =+-@, экранируется
//        апострофом (CSV formula injection) — ЧИСЛОВЫЕ ячейки (отрицательные
//        значения) не трогаются, иначе Excel читал бы их текстом.
//   tblEnableSelection(wrap, cs, dataInfo?) → включить мышь+Ctrl-C для
//        таблицы внутри wrap (задача 2 «Интерактивность табличного движка»):
//        диапазон ячеек мышью (якорь на mousedown, растяжение на mousemove,
//        Shift+клик — расширение от якоря; порог сдвига 3px отличает клик от
//        протяжки — drill по строке в сигналах обязан продолжать открываться
//        кликом, signals-table.js:243), Ctrl/Cmd+C — буфер TSV первой строкой
//        с подписями выделенных колонок, строка состояния под таблицей —
//        сумма/среднее/количество непустых по числовым ячейкам диапазона.
//        Строка состояния — СЕСТРА обёртки, а не её ребёнок (правка владельца
//        16.08): .tblwrap владеет горизонтальным скроллом, и всё, что лежит
//        внутри, стоит НАД полосой прокрутки и уезжает вбок вместе с таблицей.
//        dataInfo:{cols, rows, getValue?, totalRow?} — ТА ЖЕ ФОРМА объекта,
//        что exportInfo у tblWrap, и cols/getValue намеренно переиспользуются
//        (буфер обязан строиться ТЕМ ЖЕ адаптером и правилом сырого значения,
//        что и CSV) — но rows ОБЯЗАН быть отдельным объектом при пейджинге:
//        координаты выделения — индексы в ПЕРЕДАННОМ массиве (DOM-строка
//        отрисованной страницы, _tblCellPos ниже), а не в общем наборе;
//        подробности и ловушка (task-main-194) — у комментария tblWrap.
//        Только на устройствах с mouse-hover И шириной окна ≥768px
//        (_tblSelectionAllowed) — на тач-экране/узком окне drag остаётся
//        скроллом (AC8); гейт живой — реагирует на resize без перезагрузки,
//        класс .tblsel-on на wrap держит user-select:none в CSS (голый
//        .tblwrap table бил бы по чужим потребителям .tblwrap — flat-table.js,
//        matrix-table.js, — которые tblEnableSelection не зовут, находка
//        ревью общего шва). Несмежные диапазоны (Ctrl+клик) — вне скоупа
//        задачи 2, не заложены.
//   tblMarkIssue(cell, reason)         → пометить <td>/<th> универсальной
//        сущностью «в этой ячейке есть проблемы/ошибки вычислений» (задача 3
//        доводки движка, П3, владелец 18.08): класс .tblissue (подчёркивание,
//        БЕЗ «!» — прежний псевдоэлемент-«!» не измерялся движком вовсе,
//        снятие заодно закрыло это слепое пятно) + cell.title = reason.
//        Движок не знает СМЫСЛОВ — ЧТО именно пошло не так, формулирует
//        домен строкой-причиной (markGap в gama-daily.js — два смысла: доля
//        заказов в валюте покупателя вне МРЦ/СПП и величина известна не по
//        всем проданным SKU). Тело таблицы строит домен (движок владеет
//        только <th>), поэтому это функция-навешиватель на готовую ячейку, а
//        не декларация колонки. Раньше жила частной вёрсткой витрины GA.MA
//        (.warn-gap, gama-daily.css) — стала сущностью движка под
//        платформенным именем; второго потребителя в этом срезе нет.
//
// От чего зависит: el() из core.js. CSS-классы (.thx/.thlab/.thhide/.thgrip/
// .thfilt/.tblwrap/.tbleng/.tblcap/.colrestore/.tbltools/.tblexport/.tblissue/
// .tblsel-on/.tblsel/.tblselbar/.tblfmenu/.tblsearch/.sorted-*) — в styles.css,
// общие с блоком сигналов.

// Состояние колонок таблицы (внутри-сессия, без персиста). anchor/focus —
// выделение диапазона (задача 2): {row, col} координаты ячейки либо null,
// когда ничего не выделено. Несмежные диапазоны — вне скоупа, не заложены.
// filters/search — фильтры задачи 3: filters[key] — состояние фильтра
// колонки ({q} | {value}|{values} | {min,max} | {tiers:{ключ:k}}), search —
// кросс-колоночный запрос строки поиска НАД таблицей (он не принадлежит ни
// одной колонке). Отсутствующий ключ внутри tiers = «все» (нет ограничения);
// k = 0 читается как «ровно ноль», k ≥ 1 — как «не менее k». {value}|{values}
// (task-main-197) — мультивыбор колонки: {values:[...]} пишет меню, {value:
// "…"} — унаследованная форма (drill), читаются ОБЕ через _tblFilterValuesOf.
function tblColState() {
  return { hidden: new Set(), sortKey: null, sortDir: null, widths: {},
    anchor: null, focus: null, filters: {}, search: "" };
}

// ===== Задача 3: фильтры колонок и кросс-колоночный поиск =====
//
// Домен объявляет НА КОЛОНКЕ col.filter = "text" | "values" | "range" —
// движок сам рисует воронку в шапке, собирает список уникальных значений и
// режет строки. Колонка без col.filter воронки не получает НИКОГДА.

// Ключ значения для фильтра значений: пропуск и пустая строка — одно и то же
// «нет значения», всё прочее сравнивается текстом (селект отдаёт строку).
function _tblValueKey(v) { return v === null || v === undefined ? "" : String(v); }

// _tblFilterValuesOf(st) → список выбранных значений фильтра "values" —
// ЕДИНСТВЕННАЯ точка разбора формы состояния (task-main-197, П5 спеки
// 2026-08-18, владелец 18.08: единый механизм, а не аддитивный тип). Меню
// движка теперь ПИШЕТ {values:[...]} (мультивыбор), но {value:"…"} остаётся
// ВЕЧНО поддерживаемым входом, а не переходным костылём — единственный
// внешний писатель этой формы, drill по категории (signals-table.js), не
// переписывается и не обязан переписываться. Пустой/отсутствующий value и
// пустой массив values — ОДНО и то же «нет ограничения».
function _tblFilterValuesOf(st) {
  if (!st) return [];
  if (Array.isArray(st.values)) return st.values;
  return st.value === null || st.value === undefined || st.value === "" ? [] : [String(st.value)];
}

// Фильтр колонки «активен», если в нём есть чем резать. Пустой список («Все»),
// пустая строка поиска и пустой диапазон — это отсутствие фильтра, а не фильтр
// «ничего не показывать».
function _tblFilterActive(st) {
  if (!st) return false;
  if (st.q) return true;
  // "tiers": активен, если задано хоть одно ограничение. Ноль — ПОЛНОПРАВНОЕ
  // ограничение («нет»), поэтому смотрим на наличие ключа, а не на значение.
  if (st.tiers && Object.keys(st.tiers).length) return true;
  if (_tblFilterValuesOf(st).length) return true;
  return st.min !== null && st.min !== undefined
    || st.max !== null && st.max !== undefined;
}

function _tblRowPasses(col, st, v) {
  // "values" — теперь МНОЖЕСТВЕННЫЙ выбор (task-main-197): строка проходит,
  // если её значение входит в список выбранных — читается через
  // _tblFilterValuesOf, одинаково для новой формы {values:[...]} и старой
  // {value:"…"} (drill).
  if (col.filter === "values") return _tblFilterValuesOf(st).includes(_tblValueKey(v));
  if (col.filter === "tiers") {
    // Значение строки — карта «ключ тира → число». Каждое ограничение читается
    // как «НЕ МЕНЕЕ k» (решение владельца 18.08), а k = 0 — как «ровно ноль»:
    // самое частое намерение «покажи, где есть критические» при буквальном
    // «ровно k» было бы невыразимо. Ограничения комбинируются КОНЪЮНКЦИЕЙ —
    // согласовано и с tblFilterRows («И, не ИЛИ»), и со смыслом: «крит ≥ 1 И
    // ок нет» — осмысленный запрос, через ИЛИ — нет.
    const want = st.tiers || {};
    const counts = v && typeof v === "object" ? v : {};
    for (const k of Object.keys(want)) {
      const need = Number(want[k]);
      const cnt = Number(counts[k]) || 0;
      if (need === 0 ? cnt !== 0 : cnt < need) return false;
    }
    return true;
  }
  if (col.filter === "range") {
    // Нечисловая/пустая ячейка под числовым фильтром не проходит: «больше N»
    // о прочерке не высказывается, и показывать его среди прошедших — врать.
    if (typeof v !== "number" || !Number.isFinite(v)) return false;
    if (st.min !== null && st.min !== undefined && v < st.min) return false;
    if (st.max !== null && st.max !== undefined && v > st.max) return false;
    return true;
  }
  return _tblValueKey(v).toLowerCase().includes(String(st.q).toLowerCase());
}

// _tblFilterKey(col) → ключ, по которому фильтр читает значение строки И под
// которым хранит своё состояние в cs.filters. Один хелпер, четыре точки
// применения (tblFilterRows/tblFilterValues/_tblFilterMenu/tblHeadCell) —
// см. контракт в шапке файла (col.filterKey).
function _tblFilterKey(col) { return col.filterKey || col.key; }

// tblFilterRows(cols, rows, cs, opts) → строки, прошедшие ВСЕ активные фильтры
// колонок (И, не ИЛИ). opts.getValue(row, key) — тот же опциональный адаптер
// доступа к значению, что у сортировки/экспорта.
function tblFilterRows(cols, rows, cs, opts) {
  const o = opts || {};
  const getVal = o.getValue || ((r, k) => r[k]);
  const filters = (cs && cs.filters) || {};
  const active = cols.filter((c) => c.filter && _tblFilterActive(filters[_tblFilterKey(c)]));
  if (!active.length) return rows;
  return rows.filter((row) =>
    active.every((c) => _tblRowPasses(c, filters[_tblFilterKey(c)], getVal(row, _tblFilterKey(c)))));
}

// tblSearchRows(rows, cs, opts) → строки, где cs.search встречается ХОТЬ В
// ОДНОЙ из объявленных колонок (opts.keys). Регистронезависимо. Пустой запрос
// и пустой список колонок — полный набор.
function tblSearchRows(rows, cs, opts) {
  const q = String((cs && cs.search) || "").trim().toLowerCase();
  const o = opts || {};
  const keys = o.keys || [];
  if (!q || !keys.length) return rows;
  const getVal = o.getValue || ((r, k) => r[k]);
  return rows.filter((r) =>
    keys.some((k) => _tblValueKey(getVal(r, k)).toLowerCase().includes(q)));
}

// tblApplyFilters(cols, rows, cs, opts) — одна точка входа для домена: сперва
// кросс-колоночный поиск (opts.searchKeys), затем фильтры колонок. Порядок
// безразличен для результата (оба — конъюнкция), зафиксирован ради
// предсказуемости. Домен передаёт ПОЛНЫЙ список объявленных колонок, не
// «видимые»: фильтр скрытой колонки продолжал бы резать молча — поэтому
// tblHeadCell и не даёт скрыть колонку с активным фильтром.
function tblApplyFilters(cols, rows, cs, opts) {
  const o = opts || {};
  const searched = tblSearchRows(rows, cs, { keys: o.searchKeys, getValue: o.getValue });
  return tblFilterRows(cols, searched, cs, o);
}

// tblFilterValues(rows, col, getValue) → отсортированный список уникальных
// НЕПУСТЫХ значений колонки (список для фильтра "values"; для "tiers" НЕ
// вызывается — там значение строки не скаляр, а карта счётчиков, и Set собрал
// бы строковые представления объектов). Порядок — русская
// локаль по умолчанию, как у прежнего селекта категорий блока сигналов;
// col.filterOrder (task-main-191) переопределяет его явным списком — воронка
// тяжести обязана идти «крит»→«вним»→«ок», а не по алфавиту («вним» < «крит»
// < «ок» по ru-локали дало бы неверный порядок). Значения, не перечисленные в
// filterOrder, идут ПОСЛЕ перечисленных, между собой — снова русской локалью
// (не «должно не встретиться» — открытый список, а не белый).
function tblFilterValues(rows, col, getValue) {
  const getVal = getValue || ((r, k) => r[k]);
  const fkey = _tblFilterKey(col);
  const seen = new Set();
  for (const r of rows || []) {
    const key = _tblValueKey(getVal(r, fkey));
    if (key !== "") seen.add(key);
  }
  const values = Array.from(seen);
  const order = col.filterOrder;
  if (!order || !order.length) return values.sort((a, b) => a.localeCompare(b, "ru"));
  const rank = new Map(order.map((v, i) => [v, i]));
  return values.sort((a, b) => {
    const ra = rank.has(a) ? rank.get(a) : order.length;
    const rb = rank.has(b) ? rank.get(b) : order.length;
    return ra !== rb ? ra - rb : a.localeCompare(b, "ru");
  });
}

// _tblTierMax(rows, col, getValue, tierKey) → максимум счётчика тира по
// строкам — верхняя граница списка «≥ k». База — строки ДО фильтрации
// (o.rows = filterRows, контракт в шапке файла): иначе список «1..n»
// схлопывался бы под рукой пользователя после первого применения — та же
// ловушка, от которой уже защищён список значений фильтра "values".
// tblFilterValues для этого типа не вызывается ВОВСЕ: там получился бы Set из
// строковых представлений объектов-карт.
function _tblTierMax(rows, col, getValue, tierKey) {
  const getVal = getValue || ((r, k) => r[k]);
  const fkey = _tblFilterKey(col);
  let n = 0;
  for (const r of rows || []) {
    const m = getVal(r, fkey);
    const v = m && typeof m === "object" ? Number(m[tierKey]) || 0 : 0;
    if (v > n) n = v;
  }
  return n;
}

// Пункты списка одного тира. При n > 1 — «все / ≥ 1 / … / ≥ n / нет»; при
// n = 1 число не несёт информации, поэтому «все / есть / нет»; при n = 0
// «есть» не предлагается вовсе — оно не нашло бы ни одной строки. Активное
// ограничение показывается ВСЕГДА, даже если оно больше текущего n (набор мог
// смениться под уже поставленным фильтром): невидимое ограничение — это
// неснимаемое ограничение.
function _tblTierOptions(n, cur) {
  const has = cur !== null && cur !== undefined && cur !== "";
  const k = has ? Number(cur) : null;
  const top = Math.max(n, k || 0);
  const opt = (value, label, on) =>
    el("option", on ? { value, selected: "selected" } : { value }, label);
  const opts = [opt("", "все", !has)];
  if (top > 1) {
    for (let i = 1; i <= top; i++) opts.push(opt(String(i), "≥ " + i, k === i));
  } else if (top === 1) {
    opts.push(opt("1", "есть", k === 1));
  }
  opts.push(opt("0", "нет", k === 0));
  return opts;
}

// Выпадающее меню фильтра. Живёт в document.body с position:fixed, НЕ внутри
// .tblwrap: обёртка ленты режет и по горизонтали (overflow-x), и по вертикали
// (gama-daily.css ограничивает высоту по --tbl-max) — меню внутри неё
// обрезалось бы ровно так же, как обрезался абсолютный тулбар в задаче 1.
const _tblInteractionObservers = new WeakMap();
const _tblInteractionActive = new WeakMap();
const _tblGestureCleanup = new WeakMap();
function tblObserveInteractions(wrap, onChange) {
  let callbacks=_tblInteractionObservers.get(wrap);
  if(!callbacks){callbacks=new Set();_tblInteractionObservers.set(wrap,callbacks);}
  callbacks.add(onChange);
  return ()=>callbacks.delete(onChange);
}
function _tblInteraction(wrap, token, active) {
  if(!wrap)return;
  let tokens=_tblInteractionActive.get(wrap);if(!tokens){tokens=new Set();_tblInteractionActive.set(wrap,tokens);}
  if(active)tokens.add(token);else tokens.delete(token);
  for(const cb of _tblInteractionObservers.get(wrap)||[])cb({token,active});
}
function _tblRememberGesture(wrap, cleanup) {
  if(!wrap)return;
  let set=_tblGestureCleanup.get(wrap);if(!set){set=new Set();_tblGestureCleanup.set(wrap,set);}set.add(cleanup);
}

let _tblOpenMenuNode = null;
let _tblMenuDismissBound = false;

function _tblCloseFilterMenu() {
  if (_tblOpenMenuNode) { const wrap=_tblOpenMenuNode._ownerWrap; _tblOpenMenuNode.remove(); _tblOpenMenuNode = null; _tblInteraction(wrap,"menu",false); }
}

function _tblBindMenuDismissOnce() {
  if (_tblMenuDismissBound || typeof document === "undefined") return;
  _tblMenuDismissBound = true;
  // Capture: успеть закрыть меню ДО того, как mousedown по ячейке заведёт
  // выделение диапазона. Клик по самой воронке пропускаем — её обработчик
  // сам решает, открыть или закрыть (повторный клик = закрыть).
  document.addEventListener("mousedown", (e) => {
    if (!_tblOpenMenuNode) return;
    const t = e.target;
    if (_tblOpenMenuNode.contains(t)) return;
    if (t && t.closest && t.closest(".thfilt")) return;
    _tblCloseFilterMenu();
  }, true);
  document.addEventListener("keydown", (e) => {
    if (_tblOpenMenuNode && e.key === "Escape") _tblCloseFilterMenu();
  });
  // Прокрутка любого ПРЕДКА (лента таблицы, страница) увела бы шапку из-под
  // меню, а fixed-меню осталось бы висеть в пустоте — закрываем. Слушатель
  // на window с capture:true ловит вообще любой scroll в документе, включая
  // прокрутку ВНУТРИ самого меню (task-main-195, регресс, владелец 18.08:
  // "при попытке скролла любым способом она закрывается") — e.target даёт
  // отличить своё от чужого: contains() true только для скролла, рождённого
  // внутри открытого меню (или его будущего прокручиваемого списка).
  if (typeof window !== "undefined") {
    window.addEventListener("scroll", (e) => {
      const t = e.target;
      if (_tblOpenMenuNode && t instanceof Node && _tblOpenMenuNode.contains(t)) return;
      _tblCloseFilterMenu();
    }, true);
  }
}

function _tblMenuButtons(onApply, onReset) {
  const ap = el("button", { class: "tblfbtn", type: "button" }, "Применить");
  ap.addEventListener("click", onApply);
  const rs = el("button", { class: "tblfbtn ghost", type: "button" }, "Сбросить");
  rs.addEventListener("click", onReset);
  return el("div", { class: "tblfrow" }, [ap, rs]);
}

function _tblEnterCommits(inputs, commit) {
  for (const inp of inputs) {
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); commit(); }
    });
  }
}

// Содержимое меню по объявленному типу фильтра. Применение фильтра ВСЕГДА
// идёт через полный rerender домена (o.rerender("filter")): выделение
// диапазона хранит координаты как ИНДЕКСЫ в массиве rows, а фильтр меняет сам
// массив — только полный перерендер со свежим tblEnableSelection сбрасывает
// anchor/focus, иначе Ctrl+C прочитал бы старые координаты по новым данным и
// молча отдал бы чужие значения (требование ревью общего шва задачи 2).
function _tblFilterMenu(col, cs, o) {
  const fkey = _tblFilterKey(col);
  const st = (cs.filters && cs.filters[fkey]) || {};
  const menu = el("div", { class: "tblfmenu" });
  const apply = (next) => {
    if (!cs.filters) cs.filters = {};
    if (next) cs.filters[fkey] = next; else delete cs.filters[fkey];
    o.rerender("filter");
    _tblCloseFilterMenu();
  };
  menu.append(el("div", { class: "tblfmenu-t" }, col.filterLabel || col.label));
  if (col.filter === "values") {
    // Мультивыбор (task-main-197, П5 спеки 2026-08-18, владелец 18.08 —
    // единый механизм: сам тип "values" становится множественным, параллельный
    // "values-multi" не заводится). Список чекбоксов вместо одиночного
    // <select>: мгновенное применение на каждой галке физически невозможно —
    // apply() закрывает меню (см. ниже), первая же галка захлопнула бы
    // всплывашку, не дав отметить вторую — поэтому "Применить"/"Сбросить"
    // (тот же _tblMenuButtons, что уже несут text/range/tiers).
    const vals = tblFilterValues(o.rows, col, o.getValue);
    const active = _tblFilterValuesOf(st).map(String);
    // Активные значения обязаны быть видны, даже если их нет в текущих
    // строках: иначе фильтр, поставленный извне (drill по категории в блоке
    // сигналов, старая форма {value}), выглядел бы в меню как «ничего не
    // выбрано» — и был бы неснимаем штатным способом (тот же класс дыры,
    // что закрывает debt-main-187).
    for (const v of active) if (!vals.includes(v)) vals.unshift(v);
    const cur = new Set(active);
    // .tblpick — общий ВИД со страничным селектором категорий (app.js,
    // styles.css): ЕДИНСТВЕННАЯ прокручиваемая область меню — "Применить"/
    // "Сбросить" остаются СНАРУЖИ скролла, всегда видны. Ради именно этого
    // списка чинился баг закрытия по собственному скроллу (task-main-195) —
    // без починки функция была бы неработоспособна с первого дня.
    const list = el("div", { class: "tblpick" });
    for (const v of vals) {
      const cb = el("input", { type: "checkbox" });
      cb.checked = cur.has(v);
      cb.addEventListener("change", () => { if (cb.checked) cur.add(v); else cur.delete(v); });
      list.append(el("label", { class: "tblpick-option" }, [cb, v]));
    }
    menu.append(list);
    menu.append(_tblMenuButtons(
      () => apply(cur.size ? { values: Array.from(cur) } : null),
      () => apply(null)));
  } else if (col.filter === "tiers") {
    // Воронка тиров: по строке на каждый ОБЪЯВЛЕННЫЙ доменом тир. Кружок —
    // ПОДПИСЬ строки (визуальный словарь ячеек), а не второй переключатель:
    // управляет строкой её список, «все» — нейтральный дефолт. Вариант «кружок
    // как тумблер, список уточняет число» отклонён — два контрола на строку, а
    // состояния «выключен» и «все» дублировали бы друг друга.
    // Строки рисуются ВСЕ и ВСЕГДА, даже при n = 0: тир, исчезнувший из меню
    // вместе с сузившимся набором, делает поставленное ограничение
    // неснимаемым — это ровно та дыра, ради которой конструкция и менялась.
    const cur = Object.assign({}, st.tiers || {});
    for (const t of col.filterTiers || []) {
      const n = _tblTierMax(o.rows, col, o.getValue, t.key);
      const dot = el("span", { class: "tblfdot" + (t.color ? "" : " hollow"),
        style: t.color ? "background:" + t.color : null });
      const sel = el("select", { class: "tblfval" }, _tblTierOptions(n, cur[t.key]));
      sel.addEventListener("change", () => {
        if (sel.value === "") delete cur[t.key]; else cur[t.key] = Number(sel.value);
      });
      const row = el("div", { class: "tblfrow tblftier" },
        [dot, el("span", { class: "tblftlab" }, t.label), sel]);
      row.dataset.tier = t.key;
      menu.append(row);
    }
    // «Применить»/«Сбросить» здесь ОБЯЗАТЕЛЬНЫ, а не единообразия ради:
    // apply() закрывает меню, и применение на каждом change захлопнуло бы
    // всплывашку на первом же тире, не дав задать второй.
    menu.append(_tblMenuButtons(
      () => apply(Object.keys(cur).length ? { tiers: cur } : null),
      () => apply(null)));
  } else if (col.filter === "range") {
    const min = el("input", { class: "tblfnum", type: "number", placeholder: "≥",
      title: "Не меньше", value: st.min === null || st.min === undefined ? "" : String(st.min) });
    const max = el("input", { class: "tblfnum", type: "number", placeholder: "≤",
      title: "Не больше", value: st.max === null || st.max === undefined ? "" : String(st.max) });
    min.step="any";max.step="any";
    if(Number.isFinite(col.filterMin)){min.min=String(col.filterMin);max.min=String(col.filterMin);}
    if(Number.isFinite(col.filterMax)){min.max=String(col.filterMax);max.max=String(col.filterMax);}
    const commit = () => {
      min.setCustomValidity("");max.setCustomValidity("");
      if(!min.reportValidity()||!max.reportValidity())return;
      if(min.value!==""&&max.value!==""&&Number(min.value)>Number(max.value)){min.setCustomValidity("Минимум больше максимума");min.reportValidity();return;}
      const num = (s) => (s === "" || !Number.isFinite(Number(s)) ? null : Number(s));
      const next = { min: num(min.value), max: num(max.value) };
      apply(next.min === null && next.max === null ? null : next);
    };
    menu.append(el("div", { class: "tblfrow" }, [min, max]));
    menu.append(_tblMenuButtons(commit, () => apply(null)));
    _tblEnterCommits([min, max], commit);
  } else {
    const inp = el("input", { class: "tblftext", type: "search",
      placeholder: "содержит…", value: st.q || "" });
    if(Number.isInteger(col.filterMaxLength))inp.maxLength=col.filterMaxLength;
    const commit = () => apply(inp.value.trim() ? { q: inp.value.trim() } : null);
    menu.append(inp);
    menu.append(_tblMenuButtons(commit, () => apply(null)));
    _tblEnterCommits([inp], commit);
  }
  return menu;
}

function _tblOpenFilterMenu(anchor, col, cs, o) {
  if (typeof document === "undefined") return;
  const wasSame = _tblOpenMenuNode && _tblOpenMenuNode.dataset.key === col.key;
  _tblCloseFilterMenu();
  if (wasSame) return;                          // повторный клик по воронке — закрыть
  const menu = _tblFilterMenu(col, cs, o);
  menu.dataset.key = col.key;
  document.body.append(menu);
  const r = anchor.getBoundingClientRect();
  const mr = menu.getBoundingClientRect();
  const w = mr.width, h = mr.height;
  const vw = typeof window !== "undefined" ? window.innerWidth : w + 8;
  const vh = typeof window !== "undefined" ? window.innerHeight : r.bottom + h + 8;
  const maxLeft = vw - w - 4;
  menu.style.left = Math.round(Math.max(4, Math.min(r.left, maxLeft))) + "px";
  // Нижняя кромка (task-main-195, критерий 18): top раньше ставился
  // безусловно как r.bottom+4 — высокое меню у нижней строки шапки уезжало
  // за нижний край окна. Не помещается снизу — переворачиваем вверх; не
  // помещается и там (меню выше всей доступной высоты) — прижимаем к
  // верхней кромке тем же отступом, что и по горизонтали. Симметрично
  // positionCategoryPicker в app.js (Ось 4, одна причина, два потребителя).
  const fitsBelow = r.bottom + 4 + h <= vh - 4;
  menu.style.top = Math.round(fitsBelow ? r.bottom + 4 : Math.max(4, r.top - h - 4)) + "px";
  menu._ownerWrap=anchor.closest(".tblwrap");
  _tblOpenMenuNode = menu;
  _tblInteraction(menu._ownerWrap,"menu",true);
  _tblBindMenuDismissOnce();
  const first = menu.querySelector("select, input");
  if (first) first.focus();
}

// tblSearchBar(cs, rerender, opts) → строка поиска НАД таблицей. Поиск
// кросс-колоночный и потому НЕ принадлежит колонке — он не воронка в шапке, а
// отдельный элемент управления (решение владельца, спека задачи 3).
// opts.root — узел, внутри которого домен перерисует бар: после rerender это
// уже ДРУГОЙ инпут, и без явного возврата фокуса набирать было бы невозможно
// (панель пересоздаётся на каждое нажатие клавиши).
function tblSearchBar(cs, rerender, opts) {
  const o = opts || {};
  const inp = el("input", { class: "tblsearch", type: "search",
    placeholder: o.placeholder || "Поиск…", value: cs.search || "" });
  inp.addEventListener("input", () => {
    cs.search = inp.value;
    rerender("search");
    const fresh = (o.root || document).querySelector("input.tblsearch");
    if (fresh) { fresh.focus(); fresh.setSelectionRange(fresh.value.length, fresh.value.length); }
  });
  return inp;
}

// Применить ручные ширины к <col> текущей таблицы (живой апдейт при перетаскивании).
// root обязателен: на странице может быть больше одной таблицы, и глобальный
// селектор попал бы в чужую.
function tblApplyWidths(root, cs) {
  if (!root) return;
  for (const [k, w] of Object.entries(cs.widths)) {
    const col = root.querySelector('col[data-key="' + k + '"]');
    if (col) col.style.width = w + "px";
  }
}

function tblColgroup(cols, cs) {
  return el("colgroup", {}, cols.map((c) => {
    const a = { "data-key": c.key };
    if (cs.widths[c.key]) a.style = "width:" + cs.widths[c.key] + "px";
    return el("col", a);
  }));
}

// ===== task-main-183: отстройка ширин колонок =====
//
// Зачем. До этого среза ширину колонки не считал НИКТО: `table{width:100%}`
// без `table-layout` отдавал делёж места браузеру, и 7 из 13 таблиц
// платформы уезжали горизонтально при широком окне. Правило ниже возвращает
// решение движку: ширина колонки определяется её подписью и содержимым.
//
// Домен не объявляет НИЧЕГО нового (ось 2 доктрины унификации): и подпись, и
// отображаемый текст ячеек движок читает из уже отрисованного DOM. Читать
// сырые значения (row[key]) он не имеет права — доля 0,268 показана как
// «26,8», ISO-дата как «01.08», и мерить пришлось бы не то, что видит глаз.

// tblP90(widths) → 90-й процентиль массива. Метод интерполяции зафиксирован
// явно — линейная по рангу (`idx = 0.9*(n-1)`, тот же метод, что у numpy по
// умолчанию): без фиксации раскладка была бы «примерно такой», и написать на
// неё тест было бы нечем. Пустой массив — 0, а не NaN: таблица без строк
// законна, её колонки просто встают в ширину подписей.
function tblP90(widths) {
  if (!widths || !widths.length) return 0;
  const s = widths.slice().sort((a, b) => a - b);
  const idx = 0.9 * (s.length - 1);
  const lo = Math.floor(idx), hi = Math.ceil(idx);
  if (lo === hi) return s[lo];
  return s[lo] + (idx - lo) * (s[hi] - s[lo]);
}

// tblColumnWidths(cols, measured, container, opts) → {ключ: ширина в px}.
//
//   cols     — [{key, numeric}] в порядке отрисовки;
//   measured — {ключ: {name, p90}}: name — ширина шапки КАК ЕСТЬ (подпись +
//              зарезервированное место под «×», воронку, ручку и стрелку
//              сортировки), p90 — 90-й процентиль ширин содержимого;
//   container — доступная ширина;
//   opts.pinned — {ключ: ширина} колонок, которые пользователь потянул мышью.
//
// Правило (спека 2026-08-16):
//   base = max(name, min(p90, 3 × name)), для числовой колонки потолка нет:
//   base = max(name, p90). Потолок ×3 держит текстовую колонку от захвата
//   всей таблицы, а числовую резать нельзя вовсе — обрезанное многоточием
//   число читается как ДРУГОЕ число (решение агента, заявлено владельцу).
//
// Дальше три ветки по соотношению Σbase и контейнера:
//   1. запас   — зажатые потолком добирают до своего p90 ПЕРВЫМИ, остаток
//                делится пропорционально base между всеми;
//   2. нехватка — сжимается ИЗЛИШЕК над минимумом, пропорционально ему;
//   3. переполнение по минимумам — сжимать нечего, подписи не режутся,
//      горизонтальный скролл остаётся (решение владельца 6).
//
// Минимум колонки при сжатии разный по природе: у текстовой это name (подпись
// обязана остаться читаемой, содержимое уйдёт под многоточие), у числовой —
// её base (число под многоточие не уходит НИКОГДА). Оттого числовая колонка
// сжимается лишь тогда, когда её p90 меньше подписи — то есть в замерах
// платформы не сжимается вовсе, и отдельной оговорки в коде не требует.
//
// Закреплённая мышью колонка выходит из результата как есть и забирает своё
// место из контейнера ДО расчёта: правило её больше не трогает (приёмка 8).
function tblColumnWidths(cols, measured, container, opts) {
  const o = opts || {};
  const pinned = o.pinned || {};
  const out = {};
  if (!cols || !cols.length) return out;
  const m = measured || {};
  let avail = container;
  const live = [];
  for (const c of cols) {
    const fixedW = pinned[c.key];
    if (fixedW !== undefined && fixedW !== null) {
      out[c.key] = fixedW;
      avail -= fixedW;
      continue;
    }
    const cm = m[c.key] || {};
    // Минимум 1px: колонка с нулевой измеренной подписью (шапка ещё не
    // разложена) не имеет права стать нулевой долей в пропорции.
    const name = Math.max(1, cm.name || 0);
    const p90 = cm.p90 || 0;
    const base = c.numeric
      ? Math.max(name, p90)
      : Math.max(name, Math.min(p90, 3 * name));
    live.push({ key: c.key, name, p90, base, numeric: !!c.numeric,
      min: c.numeric ? base : name, w: base });
  }
  if (!live.length) return out;
  const S = live.reduce((s, c) => s + c.base, 0);
  const minSum = live.reduce((s, c) => s + c.min, 0);

  if (S < avail) {
    // Ветка 1. Зажатые потолком — вперёд: именно они теряют содержимое, пока
    // рядом стоит свободное место. Если запаса на всех зажатых не хватает,
    // он делится между ними пропорционально нехватке, а не по порядку колонок
    // (порядок колонок — не приоритет).
    const capped = live.filter((c) => !c.numeric && c.p90 > c.base);
    const need = capped.reduce((s, c) => s + (c.p90 - c.base), 0);
    const share = need > 0 ? Math.min(1, (avail - S) / need) : 0;
    for (const c of capped) c.w = c.base + (c.p90 - c.base) * share;
    const rest = avail - live.reduce((s, c) => s + c.w, 0);
    if (rest > 0 && S > 0) for (const c of live) c.w += rest * (c.base / S);
  } else if (minSum <= avail) {
    // Ветка 2. Сжимается только излишек над минимумом — колонка без излишка
    // (числовая, текстовая ровно по подписи) не двигается вовсе.
    const surplus = S - minSum;
    const k = surplus > 0 ? (avail - minSum) / surplus : 0;
    for (const c of live) c.w = c.min + (c.base - c.min) * k;
  }
  // Ветка 3 (minSum > avail) — w остаётся base, заданным при сборе live.

  for (const c of live) out[c.key] = c.w;
  return out;
}

// ----- Измеритель текста -----
//
// Canvas, а не вставка узлов в DOM: на ленте в 805 строк × 7 колонок вставка
// мерных узлов означала бы тысячи принудительных пересчётов вёрстки. Кэш по
// паре «шрифт + строка» — повторов в ленте много (категории, даты, коды).
let _tblCanvasCtx = null;
const _tblTextCache = new Map();

function _tblMeasureText(text, font) {
  // Разделитель ключа — явная escape-последовательность \u0000, не сырой
  // байт в исходнике (тем же соображением, что и BOM у CSV ниже: чистящий
  // проход редактора снял бы невидимый символ, не тронув видимый текст).
  // Ноль-символ, а не пробел: пробел встречается и в имени шрифта, и в
  // тексте ячейки, и два разных ключа могли бы слиться в один.
  const key = font + "\u0000" + text;
  const hit = _tblTextCache.get(key);
  if (hit !== undefined) return hit;
  if (!_tblCanvasCtx) {
    if (typeof document === "undefined") return 0;
    _tblCanvasCtx = document.createElement("canvas").getContext("2d");
  }
  _tblCanvasCtx.font = font;
  const w = _tblCanvasCtx.measureText(text).width;
  // Кэш живёт всю сессию: строки таблиц повторяются между рендерами, но
  // безграничным ему быть незачем — при переполнении чистится целиком
  // (дешевле и предсказуемее LRU, промах стоит один measureText).
  if (_tblTextCache.size > 20000) _tblTextCache.clear();
  _tblTextCache.set(key, w);
  return w;
}

// Шрифт узла одной строкой для canvas. Сокращение `font` в getComputedStyle
// возвращает пустую строку, когда семейство задано наследованием — тогда
// собираем из частей сами, иначе canvas молча мерил бы дефолтным шрифтом и
// все ширины оказались бы систематически неверными.
function _tblFontOf(style) {
  if (style.font) return style.font;
  return (style.fontStyle || "normal") + " " + (style.fontWeight || "400") + " "
    + style.fontSize + " " + style.fontFamily;
}

// ----- Снятие мерок с уже отрисованной таблицы -----
//
// Источник и подписи, и содержимого — DOM: домен не объявляет НИЧЕГО нового
// (ось 2 доктрины унификации), а сырые значения (row[key]) для измерения не
// годятся — доля 0,268 показана как «26,8», ISO-дата как «01.08».

// Ширина шапки — это ПОДПИСЬ с отступами, и только она. Кнопки управления
// колонкой («⇅» сортировка, воронка, «×») живут на подложке .thtools, которая
// выведена из потока целиком, — поэтому их вклад здесь равен нулю без единой
// строки про них. Так было не всегда: пока кнопки стояли в потоке и прятались
// через opacity:0, они занимали место ВСЕГДА — 27px в каждой колонке, 252px из
// 893 у GA.MA, то есть 28% ширины таблицы. Именно в это упирались три круга
// попыток убрать горизонтальный скролл сокращением подписей.
//
// Узлы ВНЕ потока (position:absolute) не прибавляются, и это не упрощение.
// Спека просила «+5px под ручку ресайза», но `.thgrip` лежит внутри уже
// объявленного padding-right заголовка (14px) — прибавлять её значило бы
// считать одно и то же место дважды. Там же, в этом padding-е, живёт и
// стрелка сортировки. Разница не косметическая: у GA.MA десять колонок, и
// двойной счёт раздувал таблицу до 1083px при контейнере 902 — срез добивался
// ровно обратного (поймано чужим тестом буфера обмена: последняя ячейка
// «Итого» уезжала за край ленты, и клик по ней переставал в неё попадать).
function _tblHeadWidth(th) {
  const style = getComputedStyle(th);
  let w = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
  for (const child of th.children) {
    const cstyle = getComputedStyle(child);
    if (cstyle.position === "absolute") continue;
    w += child.getBoundingClientRect().width
      + parseFloat(cstyle.marginLeft) + parseFloat(cstyle.marginRight);
  }
  return w;
}

// Ширина содержимого ячейки. Голый текст меряется canvas'ом; ячейка с
// ЭЛЕМЕНТАМИ внутри (полоска балла, кружки правил в блоке сигналов) — живым
// Range: canvas о ней ничего сказать не может, а занизить такую колонку
// значит обрезать индикатор, по которому таблицу и читают.
function _tblCellWidth(td, font, pad) {
  if (td.childElementCount) {
    const range = document.createRange();
    range.selectNodeContents(td);
    return range.getBoundingClientRect().width + pad;
  }
  return _tblMeasureText(td.textContent, font) + pad;
}

function _tblScanTable(table) {
  const colEls = table.querySelectorAll("colgroup > col");
  const headRow = table.tHead && table.tHead.rows.length ? table.tHead.rows[0] : null;
  // Строка «Итого» меряется НАРАВНЕ со строками тела, где бы она ни стояла
  // (`tr.totals > th`, gama-daily.js — с 16.08 в подвале таблицы, до того была
  // второй строкой шапки): она несёт суммы периода, то есть самые широкие
  // числа таблицы. Не измерить их значило бы назначить колонке ширину, в
  // которую итог не влезает, — а число обрезать нельзя, и оно вышло бы за
  // клетку поверх соседней (находка ревью общего шва). Ищем в ОБЕИХ секциях:
  // движок не решает за домен, куда тот поставит итог, — он мерит то, что
  // помечено классом.
  const totalsRows = [];
  for (const section of [table.tHead, table.tFoot]) {
    if (!section) continue;
    for (const r of section.rows) if (r.classList.contains("totals")) totalsRows.push(r);
  }
  const bodyRows = Array.from(table.tBodies.length ? table.tBodies[0].rows : []);
  const cols = [], measured = {};
  if (!headRow) return { cols, measured };
  // Шрифт и паддинги снимаются с ПЕРВОЙ ячейки группы и применяются ко всей
  // группе: паддинг колонки в пределах группы один и тот же (первую колонку
  // красит платформенное `th/td:first-child` из `.tblwrap.tbleng table`,
  // styles.css, task-main-192 П2 — а не JS-класс `.lead`: с того среза он
  // padding-left не несёт вовсе), а getComputedStyle на каждую из сотен
  // ячеек стоил бы дороже всего остального измерения вместе. Групп две,
  // потому что «Итого» — это `th` со своим шрифтом, а не `td` тела.
  const styleOf = (cell) => {
    if (!cell) return { font: "", pad: 0 };
    const style = getComputedStyle(cell);
    return { font: _tblFontOf(style),
      pad: parseFloat(style.paddingLeft) + parseFloat(style.paddingRight) };
  };
  for (let i = 0; i < colEls.length; i++) {
    const key = colEls[i].dataset.key;
    const th = headRow.cells[i];
    if (!key || !th) continue;
    const first = bodyRows.length ? bodyRows[0].cells[i] : null;
    // Числовая колонка — по классу выравнивания `r`: обе витрины платформы
    // метят им ровно числовые ячейки (signals-table.js, gama-daily.js), и
    // движку не нужно ни нового объявления от домена, ни разбора текста.
    const numeric = first ? first.classList.contains("r")
      : (totalsRows.length && totalsRows[0].cells[i]
        ? totalsRows[0].cells[i].classList.contains("r") : th.classList.contains("r"));
    const body = styleOf(first);
    const totals = styleOf(totalsRows.length ? totalsRows[0].cells[i] : null);
    const widths = [];
    for (const tr of bodyRows) {
      const td = tr.cells[i];
      if (td) widths.push(_tblCellWidth(td, body.font, body.pad));
    }
    // Итог не участвует в процентиле как «ещё одна строка» — он ОДИН, и
    // девяностый процентиль его бы попросту отбросил. Он задаёт нижнюю
    // границу: колонка обязана вместить его целиком.
    let floor = 0;
    for (const tr of totalsRows) {
      const cell = tr.cells[i];
      if (cell) floor = Math.max(floor, _tblCellWidth(cell, totals.font, totals.pad));
    }
    cols.push({ key, numeric });
    measured[key] = { name: _tblHeadWidth(th), p90: Math.max(tblP90(widths), floor) };
  }
  return { cols, measured };
}

// ----- Применение раскладки и её жизненный цикл -----

// Многоточие вешается ТОЛЬКО на текстовые ячейки и только там, где содержимое
// действительно не влезло; полный текст уходит в подсказку. Свой title
// помечается data-атрибутом, чтобы не затереть доменный (блок сигналов ставит
// свой на колонках с col.clip) и чтобы уметь снять только собственный, когда
// колонка расширилась.
function _tblMarkClipped(table, cols) {
  const bodyRows = table.tBodies.length ? table.tBodies[0].rows : [];
  for (let i = 0; i < cols.length; i++) {
    if (cols[i].numeric) continue;
    for (const tr of bodyRows) {
      const td = tr.cells[i];
      if (!td || !td.textContent) continue;
      // Маркер СВОЙ и намеренно НЕ `data-tblclip`: тем атрибутом помечен
      // скрытый носитель копирования, и по нему `_tblForeignFocus` отличает
      // собственное выделение от чужого. Общее имя означало бы, что обрезанная
      // ячейка выдаёт себя за носитель буфера, и Ctrl+C подменял бы содержимое
      // там, где обязан уступить полю ввода (находка ревью общего шва).
      if (td.scrollWidth > td.clientWidth + 1) {
        if (!td.title) { td.title = td.textContent; td.dataset.tblellipsis = "1"; }
      } else if (td.dataset.tblellipsis) {
        td.removeAttribute("title");
        delete td.dataset.tblellipsis;
      }
    }
  }
}

// Ширины ЗАМОРОЖЕНЫ на данных (решение владельца 5): считаются один раз и
// живут, пока не изменится сигнатура — набор ключей колонок либо ширина
// КОНТЕЙНЕРА (не окна: замер показал, что контейнер по ширине окна не
// монотонен — 842px при окне 1280 и 886px при 1024). Поиск, фильтр,
// сортировка и перелистывание сигнатуру не меняют и пересчёта не вызывают:
// блок сигналов перерисовывается на КАЖДОЕ нажатие клавиши в поиске, и
// пересчёт там означал бы дрожание колонок при печати.
//
// Смена уровня пересчёт даёт бесплатно: обе витрины держат состояние колонок
// на уровень (`colStateFor(level.key)`), то есть приходят с другим cs.
function _tblAutoLayout(wrap, cs, _recheck) {
  const table = wrap.querySelector("table");
  // Нет <colgroup> — таблица собрана без движковых <col> (неинтерактивный
  // режим блока сигналов): разливать ширины некуда, и это не ошибка.
  if (!table || !table.querySelector("colgroup > col")) return;
  const box = Math.round(wrap.clientWidth);
  if (!box) return;                       // ещё не в документе либо скрыт
  const keys = Array.from(table.querySelectorAll("colgroup > col"))
    .map((c) => c.dataset.key || "").join(",");
  // Ручные ширины входят в сигнатуру: колонка, которую пользователь потянул,
  // из расчёта выходит, и остальным полагается переразложиться по оставшемуся
  // месту при следующей перерисовке — иначе сумма ширин разошлась бы с
  // контейнером и таблица уехала бы после ресайза.
  // В сигнатуру входит и ОБЪЁМ данных — но только как максимум когда-либо
  // виденного, не как текущее число строк. Разница принципиальная и разводит
  // два требования, которые иначе противоречат друг другу:
  //   • строк стало БОЛЬШЕ, чем движок когда-либо мерил, — он видит содержимое,
  //     которого раньше не было, и обязан пересчитать. Блок сигналов
  //     открывается в кратком режиме (восемь строк), и без этого раскладка
  //     навсегда оставалась бы посчитанной по ним: «Раскрыть все» приносит
  //     полсотни строк при том же наборе колонок и том же контейнере (находка
  //     ревью общего шва — колонка выходила 138px вместо честных 211);
  //   • строк стало МЕНЬШЕ — это поиск, фильтр или последняя страница, и
  //     пересчитывать нельзя: панель перерисовывается на каждое нажатие
  //     клавиши, колонки дрожали бы при печати (приёмка 5).
  // Итог: раскладка расширяется по мере того, как движок узнаёт данные, и
  // никогда не сужается вслед за отбором.
  const bodyCount = table.tBodies.length ? table.tBodies[0].rows.length : 0;
  const seenRows = Math.max(cs._autoRows || 0, bodyCount);
  const sig = box + "|" + keys + "|" + JSON.stringify(cs.widths || {}) + "|" + seenRows;
  // Заморожены ЧИСЛА, а не факт расчёта. Каждая перерисовка домена приносит
  // свежий <colgroup> — его надо заполнить теми же ширинами, что и в прошлый
  // раз. Ранний выход «сигнатура та же — уходим» оставлял бы новые <col>
  // пустыми, и таблица возвращалась бы к браузерной авто-раскладке при первом
  // же перелистывании страницы (найдено собственным тестом приёмки 6, глазами
  // на экране это выглядело бы просто как «иногда колонки другие»).
  let widths = cs._autoWidths;
  let cols = cs._autoCols;
  if (cs._autoSig !== sig || !widths) {
    const scan = _tblScanTable(table);
    if (!scan.cols.length) return;
    widths = tblColumnWidths(scan.cols, scan.measured, box, { pinned: cs.widths });
    cols = scan.cols;
    cs._autoSig = sig;
    cs._autoWidths = widths;
    cs._autoCols = cols;
    cs._autoRows = seenRows;
  }
  // Округление — с раздачей остатка ПОСЛЕДНЕЙ колонке, а не поколоночное.
  // Расчёт сходится с контейнером точно, но сумма независимо округлённых
  // ширин — нет: на десяти колонках накапливался лишний пиксель, и таблица
  // получала горизонтальный скролл ровно на 1px при выполненном расчёте
  // (замер ревью общего шва: 903 при контейнере 902). Приёмка 1 требует
  // равенства, а не «почти».
  const colEls = Array.from(table.querySelectorAll("colgroup > col"));
  const known = colEls.filter((c) => widths[c.dataset.key]);
  let assigned = 0;
  known.forEach((col, i) => {
    const raw = widths[col.dataset.key];
    const w = i === known.length - 1
      ? Math.round(Object.values(widths).reduce((s, v) => s + v, 0)) - assigned
      : Math.round(raw);
    assigned += w;
    col.style.width = w + "px";
  });
  wrap.classList.add("tblw-auto");
  // ЯВНАЯ ширина таблицы вместо процентной. Платформенный `table{width:100%}`
  // растягивает <table> до 100% контейнера НЕЗАВИСИМО от суммы <col> —
  // проверено эмпирически: колонки суммировались в число меньше контейнера,
  // а отрисованная таблица всё равно занимала контейнер целиком (замер
  // ревью общего шва: при дробном масштабе страницы `table.getBoundingClientRect().width`
  // расходится с суммой <col> на доли пикселя именно из-за этого растяжения).
  // Ширина таблицы теперь равна СУММЕ <col> буквально, одним и тем же
  // JS-числом, а не двум независимо резолвящимся величинам.
  //
  // Запас против гипотетического субпиксельного дрейфа (было здесь) снят:
  // ревью общего шва не нашло НИ ОДНОГО фантомного скролла на 1806 замерах
  // (масштабы 1/1.25/1.5/1.75 × сотни ширин контейнера) даже без запаса, а
  // сам запас, наоборот, ДЕТЕРМИНИРОВАННО создавал скролл — сдвигал часть
  // раскладок из ветки 2 правила (сжатие излишка, точное совпадение с
  // контейнером) в ветку 3 (переполнение по минимумам, без сжатия): широта
  // окна, где это происходило, оказалась узкой полосой в 1-3px, но детская
  // ошибка была системной, не краевым случаем (замер ревью: контейнер 600 —
  // 0px до правки, 3px после).
  table.style.width = assigned + "px";
  // Остаточный горизонтальный скролл — СУБПИКСЕЛЬНЫЙ артефакт дробного
  // devicePixelRatio, и мерить его целочисленными scrollWidth/clientWidth
  // НЕЛЬЗЯ (живой замер владельца 17.08, третий раунд: полоса на экране
  // ЕСТЬ, а scrollWidth === clientWidth === 893 — оба свойства по спеке
  // округлены до целых, и переполнение в 0.3-0.7px в них не видно вовсе;
  // проверка через них молча читает «переполнения нет» и не делает ничего).
  // Механика: clientWidth округляется ВВЕРХ от дробной ширины контейнера
  // (892.667 → 893), таблица получает эти 893 целых CSS-px, браузер рендерит
  // её на сетке device-пикселей — и она вылезает за дробный контейнер на
  // доли пикселя, чего хватает для полосы прокрутки.
  // Правка: потолок из ДРОБНОЙ ширины контейнера (getBoundingClientRect,
  // за вычетом целочисленного хрома offsetWidth-clientWidth — рамки и
  // вертикальная полоса), floor + запас 2px на два источника погрешности
  // (целочисленное округление хрома до 1px + снап таблицы на сетку
  // device-пикселей до 1/dPR). Урезается ПОСЛЕДНЯЯ колонка на 1-3px —
  // невидимо. ТОЛЬКО в ветках 1/2 (assigned <= box — алгоритм посчитал
  // точное совпадение): ветка 3 (подписи не влезают, решение владельца 6)
  // не трогается ни при какой ширине — там скролл легитимный. Отличие от
  // снятого ревью фиксированного запаса (task-main-183): тот вычитался ИЗ
  // box ДО расчёта и сдвигал раскладки между ветками; этот применяется
  // ПОСЛЕ выбора ветки и на выбор ветки повлиять не может.
  if (assigned <= box && known.length) {
    const chrome = wrap.offsetWidth - wrap.clientWidth;
    const target = Math.floor(wrap.getBoundingClientRect().width - chrome) - 2;
    if (target > 0 && assigned > target) {
      const cut = assigned - target;
      const last = known[known.length - 1];
      const lastW = Math.max(1, (parseFloat(last.style.width) || 0) - cut);
      last.style.width = lastW + "px";
      table.style.width = target + "px";
    }
  }
  _tblMarkClipped(table, cols);
  // Высота закреплённой ленты (--tbl-max, tblCapRows) обязана
  // пересчитываться В ТОМ ЖЕ цикле, что и ширины: если её посчитать только
  // однажды при первом вызове домена (как было), она замирает по мерке ДО
  // table-layout:fixed и ДО подстановки веб-шрифта, а на смену масштаба
  // страницы (без перезагрузки) вообще не реагирует — window.resize сюда её
  // не приносит. Мелкая дробная нестыковка высоты строки/шапки/подвала при
  // этом накапливается и красится щелью под подвалом или прыжком шапки при
  // скролле (найдено ревью общего шва 17.08). _tblAutoLayout уже вызывается
  // на каждый из этих поводов (первый такт, fonts.ready, ResizeObserver,
  // window.resize) — переиспользуем тот же цикл, а не завели новый.
  _tblReapplyCap(wrap);
  // Кап МЕНЯЕТ ширину контейнера, которой мы уже воспользовались строчкой
  // «box = …» в начале функции: box снят ДО этого вызова, ширины колонок и
  // <table> разложены по НЕЙ. Если _tblReapplyCap только что включил
  // класс `tblcap` (overflow-y:auto + max-height) — строк больше
  // TBL_VISIBLE_ROWS, лента раньше не была капнута, — на wrap только сейчас
  // появляется вертикальная полоса прокрутки, и wrap.clientWidth сжимается
  // на её ширину УЖЕ ПОСЛЕ того, как таблица разложена по старой, более
  // широкой мерке. Итог без правки — ПОСТОЯННОЕ (не мимолётное) переполнение
  // ровно на ширину полосы: box=902 без полосы → table.style.width=900 →
  // кап → полоса → clientWidth=892 факт → 900 vs 892 = 8px (замер ревью
  // общего шва 18.08, живой замер headless БЕЗ --hide-scrollbars, лента
  // построена ПОСЛЕ document.fonts.ready — сценарий обычного отчёта на
  // живой странице, не транзиентный кадр). fonts.ready/ResizeObserver/
  // window.resize это не лечат — задокументированно ненадёжны (см. их
  // комментарии выше) и на живой странице МОГУТ не прийти ни разу: единая
  // надёжная страховка — однократный контрольный проход ПРЯМО ЗДЕСЬ.
  // Флаг `_recheck` не даёт этому проходу породить третий: кап переключает
  // класс `tblcap` по числу строк, а не по ширине, и число строк между
  // проходом 1 и проходом 2 не меняется — значит clientWidth стабилизируется
  // ровно за один дополнительный проход, рекурсия не размножается.
  if (!_recheck && Math.round(wrap.clientWidth) !== box) {
    _tblAutoLayout(wrap, cs, true);
  }
}

// Домен объявляет высоту ленты (в строках) ОДНАЖДЫ через публичный
// tblCapRows(wrap, visibleRows) — здесь она запоминается, чтобы каждый
// следующий проход _tblAutoLayout мог пересчитать --tbl-max по СВЕЖИМ
// меркам без повторного участия домена.
const _tblCapRows = new WeakMap();

function _tblReapplyCap(wrap) {
  if (_tblCapRows.has(wrap)) tblCapRows(wrap, _tblCapRows.get(wrap));
}

// Запуск расчёта. Домен для этого ничего не зовёт и не объявляет — обёртка
// есть у каждой таблицы общего движка, дальше движок справляется сам.
//
// Два независимых механизма, и это не подстраховка ради подстраховки:
//   • ПЕРВЫЙ расчёт — ближайшим таймером. В момент вызова tblWrap таблица ещё
//     не собрана и обёртка не в документе; обе витрины делают и то, и другое
//     синхронно, поэтому к ближайшему такту всё на месте. Опираться здесь на
//     ResizeObserver было бы ошибкой: он доставляет колбэк в цикле отрисовки,
//     а тот в headless-браузере (наш DOM-харнесс) отрабатывает ровно один раз
//     на старте — таблица, построенная позже, расчёта не получала бы вовсе,
//     и ни один поведенческий тест раскладки написать было бы нельзя.
//   • ПОСЛЕДУЮЩИЕ — ResizeObserver на самой обёртке: ширина контейнера
//     меняется и без перерисовки домена (правая панель перестраивается,
//     пользователь тянет окно), а следить за окном нельзя — контейнер по
//     ширине окна не монотонен (замер: 842px при окне 1280 и 886px при 1024).
// Повторный расчёт с той же сигнатурой — дешёвый выход по сравнению, так что
// перекрытие механизмов лишней работы не создаёт.
// Живых наблюдателей ровно столько, сколько таблиц на экране: предыдущий
// отключается ЗДЕСЬ, при подключении следующего, а не «когда-нибудь сам».
// Полагаться на колбэк отсоединения нельзя — он приходит не во всех
// браузерах и не в headless-харнессе, а рендеров тут сотни: блок сигналов
// перерисовывается на КАЖДОЕ нажатие клавиши в поиске, и каждый брошенный
// наблюдатель держал бы отсоединённую таблицу целиком. Ровно эта утечка уже
// случалась в этом файле с записями выделения (см. _tblSweepSelectionWraps).
// Состояние колонок (cs) переживает перерисовку и на уровень одно — поэтому
// именно оно и хранит текущего наблюдателя.
let _tblAutoObservers = 0;

// Диагностическое окно (не часть контракта потребителей): утечка наблюдателей
// поведенчески невидима — без счётчика её нечем измерить ни в тесте, ни в
// консоли.
function _tblAutoObserverCount() { return _tblAutoObservers; }

// Резервный путь пересчёта — `window.resize`, ОТДЕЛЬНО от ResizeObserver, не
// взамен него. Живой замер владельца (16.08, «скролл на месте» — таблица не
// уезжает, полоса есть, но тянуть некуда) и собственная проверка CDP-ресайзом
// показали: чистое сужение окна БЕЗ перерисовки домена не всегда доводит
// колбэк ResizeObserver до вызывающего — тот же дефект, ради которого сосед
// (`test_container_resize_recalculates_widths`) честно обходит ожидание
// колбэка через ручной `rebuild()`, а не доверяет ему. `window.resize`
// работает независимым путём (не через RO) и не может унести с собой ту же
// причину отказа.
// Один слушатель на страницу, не по одному на таблицу: `resize` летит
// глобально, и N отдельных подписчиков означали бы N синхронных пересчётов
// на одно и то же событие — приём тот же, что у `_tblBindResizeGateOnce`
// (гейт выделения) и `_tblSelectionWraps` чуть ниже по файлу. Мёртвые записи
// (таблица уже не в документе) подметаются на каждом резайзе, а не «когда-
// нибудь сам»: колбэк отсоединения ненадёжен в headless и не во всех
// браузерах (тот же довод, что и у ResizeObserver выше).
const _tblAutoWraps = new Set();
let _tblWindowResizeBound = false;

function _tblAutoWrapCount() { return _tblAutoWraps.size; }

function _tblBindWindowResizeOnce() {
  if (_tblWindowResizeBound || typeof window === "undefined") return;
  _tblWindowResizeBound = true;
  window.addEventListener("resize", () => {
    for (const entry of Array.from(_tblAutoWraps)) {
      if (!entry.wrap.isConnected) { _tblAutoWraps.delete(entry); continue; }
      _tblAutoLayout(entry.wrap, entry.cs);
    }
  });
}

function _tblObserveAuto(wrap, cs) {
  setTimeout(() => _tblAutoLayout(wrap, cs), 0);
  // Веб-шрифт применяется ПОЗЖЕ первого кадра, и мерки, снятые до него,
  // занижены: страница считает в Golos Text, а измеритель успевает померить
  // подставным системным шрифтом. Разница небольшая, но раскладка заморожена —
  // и колонка «День» на витрине GA.MA получала 55px при собственной подписи
  // 63px, то есть заголовок уходил под многоточие вопреки решению владельца 6
  // (найдено замером живого Теста после деплоя, тестами не ловилось: в
  // headless-харнессе веб-шрифтов нет вовсе). Сигнатура сбрасывается явно —
  // иначе пересчёт увидел бы прежнюю и вышел бы ни с чем.
  // Условие проверяется СИНХРОННО и именно по status: шрифты грузятся один раз
  // за жизнь страницы, и таблица, построенная после этого, меряется уже
  // правильно. Безусловный хук на `fonts.ready` сбрасывал бы заморозку на
  // КАЖДОЙ перерисовке (промис давно разрешён и срабатывает мгновенно) — то
  // есть возвращал бы ровно то дрожание колонок при печати в поиске, ради
  // которого заморозка и вводилась.
  if (typeof document !== "undefined" && document.fonts
      && document.fonts.status !== "loaded" && document.fonts.ready) {
    document.fonts.ready.then(() => {
      if (!wrap.isConnected) return;
      cs._autoSig = null;
      _tblAutoLayout(wrap, cs);
    });
  }
  // Регистрация в резервном путём — ДО раннего выхода по отсутствию
  // ResizeObserver: это независимый механизм, а не довесок к основному.
  // Прежняя запись ТОЙ ЖЕ cs (колонки живут на уровень, см. шапку файла)
  // снимается — иначе перерисовка домена копила бы по записи на рендер, та
  // же утечка, что уже случалась в файле с записями выделения.
  if (cs._autoWrapEntry) _tblAutoWraps.delete(cs._autoWrapEntry);
  const entry = { wrap, cs };
  _tblAutoWraps.add(entry);
  cs._autoWrapEntry = entry;
  _tblBindWindowResizeOnce();

  if (typeof ResizeObserver === "undefined") return;
  if (cs._autoRO) { cs._autoRO.disconnect(); _tblAutoObservers--; }
  const ro = new ResizeObserver(() => {
    if (!wrap.isConnected) {
      ro.disconnect();
      if (cs._autoRO === ro) { cs._autoRO = null; _tblAutoObservers--; }
      return;
    }
    _tblAutoLayout(wrap, cs);
  });
  ro.observe(wrap);
  cs._autoRO = ro;
  _tblAutoObservers++;
}

// Клик по заголовку: убыв → возр → дефолт вызывающего.
function tblCycleSort(cs, key) {
  if (cs.sortKey !== key) { cs.sortKey = key; cs.sortDir = "desc"; }
  else if (cs.sortDir === "desc") { cs.sortDir = "asc"; }
  else { cs.sortKey = null; cs.sortDir = null; }
}

// Ручка на правом крае заголовка: тянуть — задать ширину колонки (мин. 48px).
function tblAttachResize(grip, th, col, cs, root) {
  grip.addEventListener("pointerdown", (e) => {
    e.preventDefault(); e.stopPropagation();
    const wrap=grip.closest(".tblwrap");
    _tblInteraction(wrap,"resize",true);
    const startX = e.clientX, startW = th.getBoundingClientRect().width;
    const move = (ev) => {
      cs.widths[col.key] = Math.max(48, Math.round(startW + (ev.clientX - startX)));
      tblApplyWidths(root, cs);
    };
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", up);
      const set=_tblGestureCleanup.get(wrap);if(set)set.delete(up);
      _tblInteraction(wrap,"resize",false);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", up);
    _tblRememberGesture(wrap,up);
  });
}

// Универсальная пометка «в этой ячейке есть проблемы/ошибки вычислений»
// (задача 3 доводки табличного движка, П3, владелец 18.08). Раньше жила
// частной вёрсткой витрины GA.MA (.warn-gap + псевдоэлемент «!»,
// gama-daily.css) — стала сущностью движка под платформенным именем.
// Движок красит и подсказывает; ЧТО именно пошло не так — решает домен
// строкой-причиной, ноль знания о смыслах на стороне движка.
function tblMarkIssue(cell, reason) {
  cell.classList.add("tblissue");
  cell.title = reason;
}

// Интерактивный заголовок: клик по метке — сортировка, × — скрыть колонку,
// правый край — ширина. Аффордансы скрыты до наведения (CSS).
function tblHeadCell(col, cs, opts) {
  const o = opts || {};
  const rerender = o.rerender || function () {};
  const th = el("th", { class: ((o.cls ? o.cls + " " : "") + "thx").trim() });
  const lab = el("span", { class: "thlab" }, o.label != null ? o.label : col.label);
  th.append(lab);
  const sortable = col.sortable !== false;
  if (sortable) th.classList.add("sortable");
  const sorted = sortable && cs.sortKey === col.key;
  if (sorted) th.classList.add("sorted-" + cs.sortDir);
  if (sortable) lab.addEventListener("click", () => { tblCycleSort(cs, col.key); rerender("sort"); });
  // Подложка с кнопками управления колонкой (конструкция владельца 16.08).
  // Кнопки живут НА НЕЙ и потому целиком вне потока — именно это снимает
  // ограничение, в которое упёрлись три предыдущих круга: невидимые «×» и
  // воронка занимали 27px в КАЖДОЙ колонке, 252px из 893 у GA.MA. Теперь
  // ширину колонки определяет только подпись, а кнопкам место не нужно —
  // подложка при наведении ложится поверх правого края и, если подпись
  // длинная, перекрывает её хвост. Резким обрывом это не выглядит: левый край
  // подложки гаснет градиентом в прозрачность (CSS), поэтому текст под ней
  // уходит плавно, а не упирается в кнопку.
  const tools = el("div", { class: "thtools" });
  // Кнопка сортировки — первая на подложке. Прежде состояние сортировки нёс
  // невидимый псевдоэлемент `::after`: у неотсортированной колонки не было
  // НИКАКОГО признака, что её вообще можно сортировать, — жест держался на
  // догадке «кликну по подписи и посмотрю». Теперь у покоя есть свой знак «⇅»
  // (две противоположные стрелки), у активной — стрелка направления.
  if (sortable) {
    const sortBtn = el("button", { class: "thsort" + (sorted ? " on" : ""), type: "button",
      title: sorted ? (cs.sortDir === "asc" ? "Сортировка: по возрастанию"
        : "Сортировка: по убыванию") : "Сортировать" },
      sorted ? (cs.sortDir === "asc" ? "↑" : "↓") : "⇅");
    sortBtn.addEventListener("click", (e) => {
      e.stopPropagation(); tblCycleSort(cs, col.key); rerender("sort");
    });
    tools.append(sortBtn);
  }
  // Воронка фильтра — ТОЛЬКО у колонки, которую домен объявил фильтруемой
  // (col.filter). Не объявлена — воронки нет никогда. Аффорданс скрыт до
  // наведения, но при АКТИВНОМ фильтре виден постоянно: иначе применённый
  // фильтр был бы невидим, и пользователь читал бы урезанную таблицу как
  // полную. То же теперь верно и для сортировки — подложка целиком остаётся
  // видимой, пока у колонки есть состояние (класс `on` ниже).
  const filterOn = !!col.filter && _tblFilterActive((cs.filters || {})[_tblFilterKey(col)]);
  if (col.filter) {
    // Подсказка несёт col.filterLabel (task-main-191, П5) — единственная
    // компенсация за уход видимых кнопок тяжести домена сигналов: на
    // виртуальных колонках («Правила») сама подпись не сказала бы, ЧТО
    // фильтруется, тогда как «Фильтр: Тяжесть» — сказала. Обычные колонки без
    // filterLabel не меняют поведения (fallback на col.label). Движок при
    // этом ничего не знает про домен сигналов или его правила — filterLabel
    // такая же декларация домена, как col.label.
    const flabel = col.filterLabel || col.label;
    const fb = el("button", { class: "thfilt" + (filterOn ? " on" : ""), type: "button",
      title: filterOn ? "Фильтр активен: " + flabel : "Фильтр: " + flabel }, "▼");
    fb.addEventListener("click", (e) => {
      e.stopPropagation();
      _tblOpenFilterMenu(fb, col, cs, {
        rows: o.filterRows || [], getValue: o.getValue, rerender });
    });
    tools.append(fb);
  }
  // col.fixed — колонка-идентичность строки (день, SKU): скрывать её нечестно,
  // без неё остальные числа не к чему отнести. Кнопки «×» у такой колонки нет.
  // Колонка с АКТИВНЫМ фильтром тоже не скрывается: скрытая колонка продолжала
  // бы резать строки, а снять фильтр было бы негде — воронки на экране нет.
  if (!col.fixed && !filterOn) {
    const hide = el("button", { class: "thhide", type: "button", title: "Скрыть колонку" }, "×");
    hide.addEventListener("click", (e) => {
      e.stopPropagation(); cs.hidden.add(col.key); rerender("hide");
    });
    tools.append(hide);
  }
  // Подложка видна без наведения, пока колонка несёт состояние: иначе
  // отсортированная или отфильтрованная таблица читалась бы как исходная.
  if (sorted || filterOn) tools.classList.add("on");
  th.append(tools);
  const grip = el("span", { class: "thgrip", title: "Потянуть — ширина" });
  tblAttachResize(grip, th, col, cs, o.root);
  th.append(grip);
  return th;
}

// Сортировка по выбранной колонке; null/пусто — всегда в конец.
// null на выходе = колонка не выбрана, вызывающий применяет свой дефолт.
function tblSortByColumn(rows, cs, valueOf) {
  if (!cs.sortKey) return null;
  const dir = cs.sortDir === "asc" ? 1 : -1;
  const val = valueOf || ((r, k) => r[k]);
  return rows.slice().sort((a, b) => {
    const av = val(a, cs.sortKey), bv = val(b, cs.sortKey);
    const an = av === null || av === undefined, bn = bv === null || bv === undefined;
    if (an && bn) return 0;
    if (an) return 1;
    if (bn) return -1;
    const base = (typeof av === "number" && typeof bv === "number")
      ? av - bv : String(av).localeCompare(String(bv), "ru");
    return base * dir;
  });
}

// Обёртка таблицы: горизонтальный скролл при нехватке ширины + тулбар
// (возврат скрытых колонок + «Скачать») НАД лентой, в нормальном потоке —
// НЕ position:absolute внутри неё. Абсолютный якорь в углу обрезался
// overflow-y ленты (gama-daily.css ограничивает высоту по --tbl-max) и прятался
// под sticky-шапкой (тот же z-index, шапка позже в DOM-порядке) — находка
// ревью общего шва 2026-08-15: верхняя половина кнопки видна, нижняя закрыта
// заголовком колонки, клик по нижней половине сортирует колонку вместо
// скачивания. В нормальном потоке тулбар — обычная строка перед таблицей:
// не обрезается лентой, не спорит местом со sticky-шапкой (та цепляется за
// верх, только когда лента уже прокручена мимо этой строки).
// exportInfo: {cols, rows, filename, getValue?, totalRow?, toolsHost?} — rows
// уже без скрытых колонок (state.hidden внутри tblExportRows исключает их
// ПОВТОРНО как страховку, а не как основной механизм — это уже сделал
// вызывающий через cols). ГЛАВНОЕ (переписано task-main-194, критерий 14):
// rows — это набор, который ДОМЕН СЧИТАЕТ ВЫБОРКОЙ ПОЛЬЗОВАТЕЛЯ: уже
// отфильтрованный и отсортированный, но НЕ ОБЯЗАТЕЛЬНО совпадающий со
// строками текущей страницы на экране. Пейджинг и краткий режим — оптика
// просмотра, а не выборка (решение владельца 18.08): экспорт отдаёт всё
// выбранное, а не всё видимое. Расхождение «экран ≠ файл» компенсирует
// подсказка кнопки «Скачать» — она называет exportInfo.rows.length.
//
// ЛОВУШКА (Р-Д спеки 2026-08-18, П4 — самый вероятный способ сломать экспорт
// у потребителя с пейджингом). cols и getValue — ОБЩИЕ у exportInfo (здесь) и
// у dataInfo tblEnableSelection (задача 2) НАМЕРЕННО (буфер обязан строиться
// тем же адаптером и правилом сырого значения, что и CSV). НО rows у этих
// двух объектов РАЗНЫЕ ПО ПОСТРОЕНИЮ, не тот же объект: tblEnableSelection
// хранит координаты выделения как ИНДЕКСЫ В ПЕРЕДАННОМ ЕЙ МАССИВЕ
// (_tblCellPos ниже — это DOM-индекс строки внутри ОТРИСОВАННОЙ tbody),
// поэтому dataInfo.rows обязан быть строками ИМЕННО ОТРИСОВАННОЙ СТРАНИЦЫ
// (pageRows у потребителя с пейджингом, signals-table.js), а НЕ тем же
// exportInfo.rows. Наивная
// передача ОДНОГО объекта в оба вызова — тихий баг буфера обмена: индексы
// совпадут, но будут указывать в ДРУГОЙ массив, и Ctrl+C после выделения
// диапазона на странице >1 отдаст ЧУЖИЕ значения (см. регресс-страж
// test_dom_signals_ctrlc_on_page_two_copies_visible_page_not_full_export_set,
// tests/web/test_table_engine_interaction.py). У потребителя БЕЗ пейджинга
// (GA.MA — вся лента помещается на экран без страниц) объекты физически
// совпадают, и старая формулировка «тот же объект» была там неотличима от
// верной; у потребителя С пейджингом это перестаёт быть верным.
// Умолчание движка: 15 строк — единая высота капнутой ленты ВСЕХ таблиц
// движка (task-main-190, ранее — частная константа VISIBLE_ROWS витрины
// GA.MA). Домен волен переопределить явным вызовом tblCapRows(wrap, N) —
// но только с записанной причиной в спеке своего среза (О1 спеки
// 2026-08-17): молчаливый вызов из <d>.js — нарушение унификации, ловится
// ревью. Единственный регулятор на будущее — поднять ЭТО число; PAGE_SIZE
// блока сигналов им не связан и не трогается.
const TBL_VISIBLE_ROWS = 15;

function tblWrap(cs, rerender, exportInfo) {
  const wrap = el("div", { class: "tblwrap tbleng" });
  // Умолчание капа регистрируется ЗДЕСЬ, а не вызовом tblCapRows(wrap, N) —
  // в момент создания обёртки таблицы внутри ещё нет, и вызов сходил бы вхолостую.
  // Дальше работает уже существующий цикл авторазметки: _tblObserveAuto ниже →
  // _tblAutoLayout → _tblReapplyCap(wrap) → tblCapRows(wrap, N) — он
  // применит зарегистрированное число, когда таблица и её мерки уже на месте.
  _tblCapRows.set(wrap, TBL_VISIBLE_ROWS);
  const tools = [];
  if (cs.hidden.size) {
    const restore = el("button", { class: "colrestore", type: "button",
      title: "Показать все колонки (" + cs.hidden.size + ")" }, "⊞");
    restore.addEventListener("click", () => { cs.hidden.clear(); rerender(); });
    tools.push(restore);
  }
  if (exportInfo && exportInfo.cols && exportInfo.rows) {
    // Число в подсказке — компенсация за то, что rows (см. комментарий выше)
    // может не совпадать со страницей на экране (task-main-194, критерий 14):
    // движок ничего не знает про пейджер, только про длину переданного
    // набора — простая подстановка exportInfo.rows.length.
    const dl = el("button", { class: "tblexport", type: "button",
      title: "Скачать все " + exportInfo.rows.length + " строк (фильтры и сортировка учтены); CSV, ';', UTF-8" },
      "⭳ Скачать");
    dl.addEventListener("click", () => {
      if(exportInfo.canRead && !exportInfo.canRead())return;
      const csv = tblExportCsv(exportInfo.cols, exportInfo.rows, cs,
        { getValue: exportInfo.getValue, totalRow: exportInfo.totalRow });
      _tblDownloadText(csv, exportInfo.filename || "table.csv");
    });
    tools.push(dl);
  }
  // Место тулбара объявляет домен (exportInfo.toolsHost), содержимое —
  // по-прежнему движок. Прежние .tbltools из хозяина снимаются здесь же: узел
  // живёт ДОЛЬШЕ одного рендера (у GA.MA это строка табов уровней), и без
  // уборки каждая перерисовка добавляла бы вторую кнопку «Скачать».
  const host = exportInfo && exportInfo.toolsHost;
  if (host) host.querySelectorAll(":scope > .tbltools").forEach((n) => n.remove());
  if (tools.length) (host || wrap).append(el("div", { class: "tbltools" }, tools));
  // Отстройка ширин колонок (task-main-183) включается ЗДЕСЬ — движком, не
  // доменом: обёртка есть у каждой таблицы общего движка, и наблюдатель сам
  // дождётся момента, когда она получит ширину.
  _tblObserveAuto(wrap, cs);
  return wrap;
}

// _tblCellText(v, sep, guardFormula) — общая часть между файловым CSV-
// экспортом и TSV-буфером обмена (задача 2, ЖЁСТКОЕ ТРЕБОВАНИЕ ревью: не
// заводить вторую копию правил форматирования). sep — символ-разделитель
// текущего формата (";" у CSV, "\t" у TSV): наравне с кавычкой/переводом
// строки форсит обрамление ячейки в кавычки. guardFormula — апостроф против
// CSV formula injection: нужен у CSV (Excel исполняет формулу при ОТКРЫТИИ
// файла), не нужен и вреден у TSV — вставка из буфера обмена формулу не
// исполняет (решение владельца, задача 2 спеки).
function _tblCellText(v, sep, guardFormula) {
  let s;
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "";
    s = String(v).replace(".", ",");
  } else {
    s = v == null ? "" : String(v);
    if (guardFormula && /^[=+\-@]/.test(s)) s = "'" + s;
  }
  if (s.includes(sep) || /["\r\n]/.test(s)) s = '"' + s.replace(/"/g, '""') + '"';
  return s;
}
function _tblCsvCell(v) { return _tblCellText(v, ";", true); }
function _tblTsvCell(v) { return _tblCellText(v, "\t", false); }

// tblExportRows(cols, rows, state, opts) — контракт описан в шапке файла:
// значение сырое (через opts.getValue, если передан), пропуск — "", единица
// в шапке, скрытые колонки исключены, opts.totalRow дописан последней строкой.
// Хвост позиционных параметров (было: valueOf, totalRow) свёрнут в один
// объект-опций (находка ревью задачи 1); поле переименовано valueOf →
// getValue — свойство "valueOf" есть у ЛЮБОГО объекта (Object.prototype),
// потребитель без адаптера получал бы не undefined, а унаследованный метод,
// и движок принимал бы его за адаптер (TypeError внутри клика «Скачать»).
function tblExportRows(cols, rows, state, opts) {
  const o = opts || {};
  const hidden = (state && state.hidden) || new Set();
  const visible = cols.filter((c) => !hidden.has(c.key));
  const getVal = o.getValue || ((r, k) => r[k]);
  const header = visible.map((c) => (c.unit ? c.label + ", " + c.unit : c.label));
  const toRow = (r) => visible.map((c) => {
    const v = getVal(r, c.key);
    return (v === null || v === undefined) ? "" : v;
  });
  const body = rows.map(toRow);
  if (o.totalRow) body.push(toRow(o.totalRow));
  return [header].concat(body);
}

// tblExportCsv(cols, rows, state, opts) — CSV-строка поверх tblExportRows:
// разделитель ";", UTF-8 BOM первым символом, \r\n между строками (Excel-friendly).
function tblExportCsv(cols, rows, state, opts) {
  const table = tblExportRows(cols, rows, state, opts);
  const lines = table.map((row) => row.map(_tblCsvCell).join(";"));
  // UTF-8 BOM — явная escape-последовательность, не невидимый литерал U+FEFF в
  // исходнике: чистящий проход редактора/линтера тихо снял бы невидимый
  // символ, не тронув видимый текст (находка ревью общего шва 2026-08-15).
  // Excel опознаёт кодировку без мастера импорта только с этим байтом первым.
  return "\uFEFF" + lines.join("\r\n");
}

// Триггер скачивания текста как файла: Blob + временная ссылка-клик. Тот же
// приём, каким браузер сам качает файл по href в directive-form-engine.js —
// там сервер уже отдаёт готовый файл по прямой ссылке (empty.xlsx/actual.xlsx),
// здесь же CSV собран НА КЛИЕНТЕ (видимое состояние таблицы серверу не
// известно), поэтому вместо href на эндпоинт — Blob-URL на тот же <a>.
// revokeObjectURL — СЛЕДУЮЩИМ тиком (setTimeout), не синхронно после click():
// синхронный отзыв в том же тике — известная причина отменённой загрузки в
// Firefox (находка ревью общего шва).
function _tblDownloadText(text, filename) {
  const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = el("a", { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

// Капает ленту на visibleRows строк внутренним скроллом (класс `tblcap`) —
// закрепление ШАПКИ с task-main-190 больше не её работа: это чистый CSS
// (`.tbleng thead/tfoot th{position:sticky…}`, styles.css), навешанный на
// класс `tbleng`, который сама же tblWrap ставит на обёртку. Здесь остаётся
// одна забота — посчитать высоту ленты и решить, нужен ли ей вообще
// внутренний скролл. Высота — по измерению, не по константам: строка зависит
// от шрифта, переносов и набора колонок. Выставляет на wrap CSS-переменную
// --tbl-max (высота ленты); саму границу читает CSS-правило `.tblcap` —
// движок лишь ставит/снимает класс, не зная, каким селектором его прочтут.
// Тулбар (.tbltools, если есть) — НЕ sticky и НЕ часть шапки, но занимает
// реальное место в нормальном потоке НАД таблицей (см. комментарий у tblWrap)
// — его высота учтена в --tbl-max, иначе лента показывала бы на одну строку
// меньше заявленных visibleRows.
function tblCapRows(wrap, visibleRows) {
  // Запоминается ЗДЕСЬ, а не только там, где домен вызвал функцию впервые:
  // _tblReapplyCap читает эту запись на каждый проход _tblAutoLayout
  // (первый такт, fonts.ready, ResizeObserver, window.resize — в т.ч. смена
  // масштаба страницы), и без записи «здесь» повторные проходы не знали бы,
  // сколько строк показывать, до следующего явного вызова доменом.
  _tblCapRows.set(wrap, visibleRows);
  const table = wrap.querySelector("table");
  // Ранний выход БЕЗ таблицы/тела — капнутая лента не имеет права пережить
  // своё основание: класс снимается здесь тоже, а не только на выходах ниже
  // (до task-main-190 это был единственный выход, который его не снимал).
  if (!table || !table.tHead || !table.tBodies.length) {
    wrap.classList.remove("tblcap");
    return;
  }
  const headRows = table.tHead.rows;
  const bodyRows = table.tBodies[0].rows;
  if (!headRows.length) { wrap.classList.remove("tblcap"); return; }
  const tools = wrap.querySelector(".tbltools");
  const toolsH = tools ? tools.getBoundingClientRect().height : 0;
  const headH = Array.from(headRows)
    .reduce((s, r) => s + r.getBoundingClientRect().height, 0);
  // Подвал («Итого», приклеенное к низу ленты) занимает место внутри той же
  // прокручиваемой ленты: не прибавить его высоту значит съесть под него одну
  // строку данных — лента показывала бы N−1 вместо заявленных N.
  const footH = table.tFoot
    ? Array.from(table.tFoot.rows).reduce((s, r) => s + r.getBoundingClientRect().height, 0)
    : 0;
  const rowH = bodyRows.length ? bodyRows[0].getBoundingClientRect().height : 0;
  // Нулевые высоты — таблица ещё не разложена либо в ней не осталось видимых
  // колонок. Ограничить ленту нулём значит схлопнуть блок в полоску вместе с
  // кнопкой возврата колонок, то есть запереть пользователя без выхода: в таком
  // случае ограничение снимается.
  if (!visibleRows || bodyRows.length <= visibleRows || !rowH || !headH) {
    wrap.style.removeProperty("--tbl-max");
    wrap.classList.remove("tblcap");
    return;
  }
  // БЕЗ округления — ни floor, ни round (пятый раунд, 17.08). Высоты строк
  // на дробном devicePixelRatio дробные (замер владельца: rowH=37.667,
  // сумма ленты 627.5), и ЦЕЛАЯ лента физически не может быть кратна
  // ДРОБНОЙ строке: floor давал ленту на полпикселя НИЖЕ потоковой позиции
  // 15-й строки — прилипший к низу подвал вечно наезжал на живую,
  // прокручивающуюся строку, и у его кромки был виден движущийся срез
  // (это и была «щель, в которой видно таблицу»); round с остатком ≥0.5 —
  // зеркально, лента выше сетки и просвет над подвалом. Точная дробная
  // высота (CSS принимает дробные px) сажает прилипший подвал ровно на
  // потоковую позицию последней видимой строки — расхождение остаётся
  // только от снапа на сетку device-пикселей (< 1 device px) и прикрыто
  // box-shadow-подложкой подвала (gama-daily.css).
  //
  // Гуттер горизонтальной полосы — БЕЗУСЛОВНО, не только когда таблица шире
  // контейнера. Живой замер владельца (17.08, второй раунд) снял гипотезу
  // «резерв только при настоящем overflow-x»: на 100% масштабе
  // wrap.scrollWidth === wrap.clientWidth (переполнения по ширине нет вовсе),
  // но offsetHeight-clientHeight всё равно даёт 10px — на этом браузере/теме
  // резерв под горизонтальную полосу оказался постоянным спутником АКТИВНОГО
  // вертикального скролла (а он активен всегда — этот код исполняется только
  // когда bodyRows.length > visibleRows, строка 1173), независимо от того,
  // нужен ли горизонтальный скролл по факту. max-height без него делает
  // ленту не кратной высоте строки. offsetHeight-clientHeight не зависит от
  // того, что мы впишем в --tbl-max этим же вызовом (полоса — следствие
  // вертикального overflow, а не значения max-height), поэтому без риска
  // зацикливания.
  const gutter = Math.max(0, wrap.offsetHeight - wrap.clientHeight);
  wrap.style.setProperty("--tbl-max",
    (toolsH + headH + footH + visibleRows * rowH + gutter) + "px");
  wrap.classList.add("tblcap");
}

// ===== Задача 2 «Интерактивность табличного движка»: выделение диапазона ====
//
// Координаты ячейки — {row, col}: row — индекс строки ДАННЫХ (0..rows.length-1
// в теле таблицы; −1 — строка «Итого», если её объявил домен через
// dataInfo.totalRow: визуально она стоит ПЕРЕД телом, второй строкой шапки, и
// индекс обязан это отражать — иначе протяжка от неё вниз нормализуется в
// диапазон через всю таблицу), col — индекс колонки среди ВИДИМЫХ
// (совпадает с td.cellIndex/th.cellIndex — тело и строка «Итого» рисуют один
// и тот же набор видимых колонок в одном порядке, индексы сопоставимы напрямую).

// tblRangeCells(anchor, focus) → плоский список ключей ячеек прямоугольника
// "row:col" (включая границы). anchor/focus — в любом порядке углов (протяжка
// вверх-влево нормализуется по min/max). Несмежные диапазоны — вне скоупа.
function tblRangeCells(anchor, focus) {
  if (!anchor || !focus) return [];
  const r0 = Math.min(anchor.row, focus.row), r1 = Math.max(anchor.row, focus.row);
  const c0 = Math.min(anchor.col, focus.col), c1 = Math.max(anchor.col, focus.col);
  const cells = [];
  for (let r = r0; r <= r1; r++) {
    for (let c = c0; c <= c1; c++) cells.push(r + ":" + c);
  }
  return cells;
}

// tblRangeStats(values) → {sum, avg, count} ТОЛЬКО по числовым конечным
// значениям — та же граница «число», что у CSV/TSV-экспорта (NaN/±Infinity/
// текст/null/undefined не считаются). count=0 → avg null (делить не на что),
// sum остаётся нейтральным 0 (не «нет данных»).
function tblRangeStats(values) {
  const nums = values.filter((v) => typeof v === "number" && Number.isFinite(v));
  const sum = nums.reduce((s, v) => s + v, 0);
  return { sum, avg: nums.length ? sum / nums.length : null, count: nums.length };
}

// Координаты ячейки по её месту в DOM, либо null для ячеек шапки-сортировки
// (первая строка thead — свои клики: сортировка/скрытие/ресайз, не выделяемые).
// Индекс строки «Итого» (tr.totals) считается по её ВИЗУАЛЬНОМУ месту, а не по
// одному фиксированному правилу: в подвале (<tfoot>, где она живёт у GA.MA с
// 16.08) это число строк тела — она стоит ПОСЛЕ них; во второй строке шапки —
// −1, она стоит ПЕРЕД ними. Иначе протяжка от «Итого» в соседнюю строку
// нормализовалась бы в диапазон через ВСЮ таблицу вместо видимых двух строк
// (находка ревью общего шва, Важно 6 — она же и породила прежнюю −1).
function _tblCellPos(cell, table) {
  const tr = cell.parentElement;
  if (tr.classList.contains("totals")) {
    const inFoot = !!table.tFoot && tr.parentElement === table.tFoot;
    const bodyCount = table.tBodies[0] ? table.tBodies[0].rows.length : 0;
    return { row: inFoot ? bodyCount : -1, col: cell.cellIndex };
  }
  if (table.tBodies[0] && tr.parentElement === table.tBodies[0]) {
    return { row: tr.sectionRowIndex, col: cell.cellIndex };
  }
  return null;
}

// Значения выделенных ячеек как {row, value}: value — через sel.getValue (тот
// же адаптер, что CSV-экспорт); индекс ВНЕ диапазона строк данных (−1 у итога
// в шапке, rows.length у итога в подвале — оба варианта даёт _tblCellPos по
// визуальному месту) читает sel.totalRow — объявленную доменом строку «Итого»,
// а не текст DOM.
// tblHasSelection(anchor, focus) — есть ли ЗНАЧАЩЕЕ выделение. Одна ячейка им
// НЕ считается (правка владельца 2026-08-15): клик по ячейке — это жест
// «снять выделение», и подсвечивать/копировать по нему одну клетку значило бы
// отвечать действием на отмену. Геометрия `tblRangeCells` при этом не
// меняется — там одна ячейка законный прямоугольник; решение принимается
// здесь, уровнем выше, и его зовут ВСЕ потребители (подсветка, строка
// состояния, TSV/HTML буфера), иначе они разошлись бы в трактовке.
function tblHasSelection(anchor, focus) {
  if (!anchor || !focus) return false;
  return !(anchor.row === focus.row && anchor.col === focus.col);
}

function _tblSelectionValues(sel) {
  const anchor = sel.cs.anchor, focus = sel.cs.focus;
  if (!tblHasSelection(anchor, focus)) return [];
  const r0 = Math.min(anchor.row, focus.row), r1 = Math.max(anchor.row, focus.row);
  const c0 = Math.min(anchor.col, focus.col), c1 = Math.max(anchor.col, focus.col);
  const getVal = sel.getValue || ((r, k) => r[k]);
  const out = [];
  for (let r = r0; r <= r1; r++) {
    const rowObj = (r >= 0 && r < sel.rows.length) ? sel.rows[r] : sel.totalRow;
    if (!rowObj) continue;
    for (let c = c0; c <= c1; c++) {
      const col = sel.cols[c];
      if (!col) continue;
      out.push({ row: r, value: getVal(rowObj, col.key) });
    }
  }
  return out;
}

function _tblFmtNum(n) {
  return n === null ? "—" : n.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}

// Подсветка выделенных ячеек + строка состояния под таблицей: пересчитываются
// точечно на mousemove/Shift-клик БЕЗ полного rerender домена (тот перестроил
// бы всю таблицу и потерял бы протяжку на середине жеста). Строка состояния
// ОПУСТОШАЕТСЯ (bar.textContent = "") ТОЛЬКО когда нет выделения (anchor/focus
// пусты) — «0 непустых» (выделены только текстовые ячейки) законный ответ,
// который обязан быть виден: спрятать его при непустом выделении читается
// пользователем как «выделение не сработало» (находка ревью общего шва,
// Важно 3). НЕ display:none/bar.hidden (было до 17.08): гашение через
// display убирало строку из потока — первое же выделение раздвигало layout и
// толкало вниз всё, что стоит под таблицей (жалоба владельца 17.08). Пустой
// textContent + CSS .tblselbar:empty (styles.css) держат место в потоке
// ВСЕГДА, когда выделение подключено — резерв, а не появление/исчезновение.
function _tblRenderSelection(sel) {
  sel.wrap.querySelectorAll(".tblsel").forEach((n) => n.classList.remove("tblsel"));
  if (!tblHasSelection(sel.cs.anchor, sel.cs.focus)) { sel.bar.textContent = ""; _tblInteraction(sel.wrap,"selection",false); return; }
  const keys = new Set(tblRangeCells(sel.cs.anchor, sel.cs.focus));
  sel.table.querySelectorAll("td, tr.totals th").forEach((cell) => {
    const pos = _tblCellPos(cell, sel.table);
    if (pos && keys.has(pos.row + ":" + pos.col)) cell.classList.add("tblsel");
  });
  const stats = tblRangeStats(_tblSelectionValues(sel).map((v) => v.value));
  sel.bar.textContent = "Сумма: " + _tblFmtNum(stats.sum) + " · Среднее: "
    + _tblFmtNum(stats.avg) + " · " + stats.count + " непустых";
  _tblInteraction(sel.wrap,"selection",true);
}

// TSV для буфера обмена — первая строка подписи выделенных колонок (решение
// владельца), тем же правилом заголовка, что шапка CSV; значения — через тот
// же _tblSelectionValues/getValue, что и статистика/CSV (ЖЁСТКОЕ ТРЕБОВАНИЕ
// ревью задачи 2: буфер и CSV не расходятся в правилах форматирования).
function _tblSelectionTsv(sel) {
  const anchor = sel.cs.anchor, focus = sel.cs.focus;
  if (!tblHasSelection(anchor, focus)) return null;
  const c0 = Math.min(anchor.col, focus.col), c1 = Math.max(anchor.col, focus.col);
  const cols = sel.cols.slice(c0, c1 + 1);
  if (!cols.length) return null;
  const header = cols.map((c) => (c.unit ? c.label + ", " + c.unit : c.label));
  const byRow = new Map();
  for (const { row, value } of _tblSelectionValues(sel)) {
    if (!byRow.has(row)) byRow.set(row, []);
    byRow.get(row).push(value);
  }
  const lines = [header.map(_tblTsvCell).join("\t")];
  for (const vals of byRow.values()) lines.push(vals.map(_tblTsvCell).join("\t"));
  return lines.join("\r\n");
}

function _tblHtmlEscape(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// HTML-таблица того же выделения. Зачем второй формат рядом с TSV: plain-text
// с табами Excel разбирает по колонкам НЕ всегда — вставка приезжала одной
// ячейкой (жалоба владельца 2026-08-15), а Word и Google Sheets не разбирают
// его вовсе. `text/html` с настоящей <table> вставляется таблицей везде.
// Значения — те же, что в TSV (общий _tblSelectionValues/getValue): два
// формата одного выделения не имеют права разойтись содержимым.
function _tblSelectionHtml(sel) {
  const anchor = sel.cs.anchor, focus = sel.cs.focus;
  if (!tblHasSelection(anchor, focus)) return null;
  const c0 = Math.min(anchor.col, focus.col), c1 = Math.max(anchor.col, focus.col);
  const cols = sel.cols.slice(c0, c1 + 1);
  if (!cols.length) return null;
  const head = cols.map((c) => "<th>"
    + _tblHtmlEscape(c.unit ? c.label + ", " + c.unit : c.label) + "</th>").join("");
  const byRow = new Map();
  for (const { row, value } of _tblSelectionValues(sel)) {
    if (!byRow.has(row)) byRow.set(row, []);
    byRow.get(row).push(value);
  }
  const body = Array.from(byRow.values(), (vals) => "<tr>"
    + vals.map((v) => "<td>" + _tblHtmlEscape(_tblCellText(v, "\t", false)) + "</td>").join("")
    + "</tr>").join("");
  return "<table><thead><tr>" + head + "</tr></thead><tbody>" + body + "</tbody></table>";
}

let _tblActiveSel = null;
let _tblCopyBound = false;

// Копирование идёт ШТАТНЫМ путём браузера: слушатель события `copy`, который
// подменяет содержимое буфера через clipboardData.setData. Прежняя схема
// (keydown → execCommand/navigator.clipboard.write) отказывала молча — при
// неудачной записи в буфере оставалось ПРЕЖНЕЕ содержимое, и пользователь
// вставлял то, что копировал до этого (жалоба владельца 2026-08-16: «вставляет
// ссылку вместо таблицы»). У события `copy` этой дыры нет: данные кладёт сам
// браузер в рамках уже начатого им копирования, разрешений и защищённого
// контекста не требуется, и работает одинаково на http-Тесте и https-Проде.
//
// Носитель нужен, чтобы браузер вообще НАЧАЛ копирование: при user-select:none
// и пустом нативном выделении Ctrl+C события `copy` не порождает. Поэтому на
// keydown ставится скрытый носитель с выделенным содержимым — и НЕ гасится
// событие: дальше браузер сам шлёт `copy`, где данные и подменяются.
function _tblBindCopyOnce() {
  if (_tblCopyBound || typeof document === "undefined") return;
  _tblCopyBound = true;

  document.addEventListener("copy", (e) => {
    const sel = _tblActiveSel;
    if (!sel || !sel.wrap.isConnected) return;
    if(sel.canRead && !sel.canRead())return;
    if (!tblHasSelection(sel.cs.anchor, sel.cs.focus)) return;
    if (_tblForeignFocus()) return;
    const dt = e.clipboardData;
    if (!dt) return;
    const tsv = _tblSelectionTsv(sel);
    if (tsv == null) return;
    const html = _tblSelectionHtml(sel);
    dt.setData("text/plain", tsv);
    if (html) dt.setData("text/html", html);
    e.preventDefault();
    _tblFlashCopied(sel);
  }, true);

  document.addEventListener("keydown", (e) => {
    if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "c") return;
    if (_tblForeignFocus()) return;
    const sel = _tblActiveSel;
    if (!sel || !sel.wrap.isConnected) return;
    if(sel.canRead && !sel.canRead())return;
    if (!tblHasSelection(sel.cs.anchor, sel.cs.focus)) return;
    _tblArmCopyCarrier();
  });
}

// Фокус/выделение принадлежат не таблице: поле ввода (Ctrl+C там копирует
// текст поля) либо живое нативное выделение ВНЕ ленты таблицы (пользователь
// выделил абзац страницы). В обоих случаях движок молча уступает.
function _tblForeignFocus() {
  const tag = (document.activeElement && document.activeElement.tagName) || "";
  if (tag === "INPUT" || tag === "TEXTAREA") return true;
  const nativeSel = typeof window !== "undefined" && window.getSelection && window.getSelection();
  if (!nativeSel || nativeSel.isCollapsed || !nativeSel.toString()) return false;
  const node = nativeSel.anchorNode;
  const sel = _tblActiveSel;
  // Выделение внутри носителя копирования — наше собственное, не чужое.
  // anchorNode бывает и ЭЛЕМЕНТОМ (range.selectNodeContents ставит якорь на
  // сам узел, не на его текст), поэтому closest зовётся от элемента, а не от
  // parentElement: иначе носитель принимался за чужое выделение и движок
  // уступал сам себе — копирование не срабатывало ни разу (замер 2026-08-16:
  // prevented=false, plainLen=0 при девяти выделенных ячейках).
  const host = node && (node.nodeType === 1 ? node : node.parentElement);
  if (host && host.closest("[data-tblclip]")) return false;
  return !(sel && node && sel.wrap.contains(node));
}

// Скрытый носитель выделения: без него браузер не начинает копирование.
// Живёт до конца текущего такта — событие `copy` приходит синхронно следом.
function _tblArmCopyCarrier() {
  const host = document.createElement("div");
  host.setAttribute("data-tblclip", "");
  host.textContent = " ";
  host.style.position = "fixed";
  host.style.top = "-1000px";
  host.style.opacity = "0";
  host.style.userSelect = "text";
  document.body.append(host);
  const range = document.createRange();
  range.selectNodeContents(host);
  const winSel = window.getSelection();
  winSel.removeAllRanges();
  winSel.addRange(range);
  setTimeout(() => {
    const cur = window.getSelection();
    if (cur && cur.anchorNode && host.contains(cur.anchorNode)) cur.removeAllRanges();
    host.remove();
  }, 0);
}

// Короткий отклик в строке состояния: без него отказ копирования неотличим от
// успеха — ровно та слепота, из-за которой дефект «вставляется ссылка» дожил
// до жалобы владельца.
function _tblFlashCopied(sel) {
  if (!sel.bar) return;
  const prev = sel.bar.textContent;
  sel.bar.textContent = "Скопировано · " + prev;
  setTimeout(() => {
    if (sel.bar.textContent.startsWith("Скопировано · ")) sel.bar.textContent = prev;
  }, 1500);
}

// Гейт устройства: мышь с hover И ширина окна ≥768 (AC8 — на тач-экране И на
// узком окне drag остаётся скроллом). Не кэшируется — зовётся заново при
// каждом взаимодействии И на resize (см. ниже), поэтому переживает live-
// сужение/расширение окна без перезагрузки страницы (находка ревью общего
// шва, Важно 4: исходная версия проверяла только matchMedia("hover:hover") и
// ровно один раз, при подключении — окно 678px с мышью проходило гейт).
function _tblSelectionAllowed() {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(hover: hover)").matches && window.innerWidth >= 768;
}

// .tblsel-on — класс на wrap, ИМ (не голым .tblwrap) держится user-select:none
// в CSS: голый селектор .tblwrap table бил по ВСЕМ таблицам платформы
// (flat-table.js, matrix-table.js — P&L Взаиморасчётов), которые вообще не
// зовут tblEnableSelection — они теряли нативное выделение текста, не получая
// взамен ничего (своего копирования там нет), находка ревью общего шва,
// Блокер 2. Класс синхронизируется live: и при подключении, и на resize —
// сузил окно посреди выделения → класс снят, само выделение сброшено (иначе
// пользователь остался бы с «мёртвым» диапазоном на экране).
function _tblSyncSelectionGate(entry) {
  const allowed = _tblSelectionAllowed();
  entry.wrap.classList.toggle("tblsel-on", allowed);
  if (!allowed && (entry.cs.anchor || entry.cs.focus)) {
    entry.cs.anchor = null;
    entry.cs.focus = null;
    _tblRenderSelection(entry.sel);
  }
}

const _tblSelectionWraps = new Set();
let _tblResizeBound = false;

// Выбросить записи отсоединённых от DOM таблиц. Зовётся при КАЖДОМ
// подключении (tblEnableSelection) и на resize — не ТОЛЬКО на resize, как
// было (находка ревью задачи 2, шаг 0 задачи 3). Полный rerender домена
// подключает выделение заново на свежем wrap, а прежний wrap уже отсоединён;
// без уборки на подключении каждая перерисовка оставляла мёртвую запись,
// которая держит весь отсоединённый DOM таблицы (вместе с висящим
// mousedown-слушателем), colState и sel — а sel держит rows и cols, то есть
// ВЕСЬ массив данных рендера. Сценарий частый: renderPanel в блоке сигналов
// зовётся на каждое нажатие клавиши в поиске, на смену фильтра, на каждую
// страницу и сортировку (замер ревью: 30 rerender'ов без единого resize →
// 30 записей, 29 из них отсоединённые).
function _tblSweepSelectionWraps() {
  for (const entry of Array.from(_tblSelectionWraps)) {
    if (!entry.wrap.isConnected) _tblSelectionWraps.delete(entry);
  }
}

// Диагностическое окно (не часть контракта потребителей): сколько записей
// выделения движок держит СЕЙЧАС. Утечка отсоединённых записей поведенчески
// невидима — без этого счётчика её нечем измерить ни в тесте, ни в консоли.
function _tblSelectionWrapCount() { return _tblSelectionWraps.size; }

function _tblBindResizeGateOnce() {
  if (_tblResizeBound || typeof window === "undefined") return;
  _tblResizeBound = true;
  window.addEventListener("resize", () => {
    _tblSweepSelectionWraps();
    for (const entry of Array.from(_tblSelectionWraps)) _tblSyncSelectionGate(entry);
  });
}

function _tblArmClickGuard(sel) {
  sel.justInteracted = true;
  // Самоочистка через кадр — страховка на случай, если ни один click так и
  // не дойдёт до _tblBindClickGuardOnce (mouseup вне документа целиком:
  // курсор ушёл за пределы окна браузера). Обычный клик приходит СИНХРОННО
  // сразу за mouseup, в том же такте — успевает раньше rAF (находка ревью
  // общего шва, Блокер 1, вторая часть направления).
  if (typeof requestAnimationFrame === "function") {
    requestAnimationFrame(() => { sel.justInteracted = false; });
  }
}

let _tblClickGuardBound = false;

// Клик, следующий сразу за успешным drag-выделением/Shift-расширением,
// гасится ЗДЕСЬ — на document, в фазе capture, ОДИН слушатель на всю
// страницу (не по одному на wrap/рендер). Слушатель на wrap (было) НЕ видел
// click, если mousedown начался внутри таблицы, а mouseup — ЗА пределами
// .tblwrap (курсор увели за край ленты, обычный жест): в этом случае click
// достаётся общему предку mousedown/mouseup-целей, а wrap в путь
// распространения событий уже не попадает — флаг justInteracted оставался
// взведённым НАВСЕГДА, и следующий чистый клик по drill молча съедался
// (находка ревью общего шва, Блокер 1, замер: «протяжка, отпускание вне
// ленты -> drill=[]; следующий чистый клик -> drill=[]»). document — корень
// пути распространения ЛЮБОГО клика, независимо от того, где оказался target.
function _tblBindClickGuardOnce() {
  if (_tblClickGuardBound || typeof document === "undefined") return;
  _tblClickGuardBound = true;
  document.addEventListener("click", (e) => {
    const sel = _tblActiveSel;
    if (!sel || !sel.justInteracted) return;
    sel.justInteracted = false;
    e.stopPropagation();
    e.preventDefault();
  }, true);
}

// Строка состояния выделения ставится СЕСТРОЙ обёртки, сразу за ней (правка
// владельца 16.08). Внутри .tblwrap она лежала над полосой горизонтальной
// прокрутки и уезжала вбок вместе с таблицей — читать сумму диапазона
// приходилось, домотав ленту обратно влево.
// Отложенный перенос — для потребителя, который зовёт tblEnableSelection ДО
// вставки обёртки в документ (блок сигналов: buildTable подключает выделение,
// а панель добавляет её уже вызывающий). К ближайшему такту вставка сделана —
// тот же приём, каким движок ждёт разложенную таблицу в _tblObserveAuto.
function _tblPlaceSelBar(wrap, bar) {
  if (wrap.parentElement) { wrap.after(bar); return; }
  wrap.append(bar);
  setTimeout(() => {
    if (wrap.parentElement && bar.parentElement === wrap) wrap.after(bar);
  }, 0);
}

// tblEnableSelection(wrap, cs, dataInfo) — включить мышь+Ctrl-C для таблицы
// внутри wrap; звать ПОСЛЕ того, как <table> уже добавлена в wrap (тот же
// момент, что tblCapRows). dataInfo:{cols, rows, getValue?, totalRow?} — ТА
// ЖЕ ФОРМА объекта, что exportInfo у tblWrap, cols/getValue переиспользуются
// намеренно — но rows строится ОТДЕЛЬНО у потребителя с пейджингом (строки
// ОТРИСОВАННОЙ страницы, не весь выбранный набор) — см. предупреждение и
// разбор ловушки у комментария tblWrap. Гейт устройства/ширины —
// _tblSelectionAllowed(), проверяется на каждое взаимодействие и на resize
// (AC8), не кэшируется на момент подключения.
function tblEnableSelection(wrap, cs, dataInfo) {
  if (typeof window === "undefined" || typeof document === "undefined") return;
  const table = wrap.querySelector("table");
  if (!table) return;
  // Полный rerender домена (сортировка/скрытие/фильтр/страница/данные) зовёт
  // tblEnableSelection заново на СВЕЖЕМ wrap — cs (colState) при этом тот же
  // персистентный объект, и старые anchor/focus указывали бы на координаты
  // ПРЕЖНЕГО расклада строк/колонок. Не сбросить их значило бы, что Ctrl+C
  // сразу после пересортировки читает устаревшие индексы по свежим
  // rows/cols — неверные значения без единого throw (найдено при подготовке
  // живого доказательства к отчёту, не было в исходном плане задачи 2).
  cs.anchor = null;
  cs.focus = null;
  const di = dataInfo || {};
  const bar = el("div", { class: "tblselbar" });
  _tblPlaceSelBar(wrap, bar);
  const sel = { wrap, cs, table, bar,
    canRead:di.canRead, cols: di.cols || [], rows: di.rows || [], getValue: di.getValue, totalRow: di.totalRow };
  _tblActiveSel = sel;
  // Уборка мёртвых записей — ДО добавления новой (свой wrap в блоке сигналов
  // на этот момент ещё не в документе: signals-table.js подключает выделение
  // перед вставкой панели, и подмести его вместе с прошлыми было бы ошибкой).
  _tblSweepSelectionWraps();
  const entry = { wrap, cs, sel };
  _tblSelectionWraps.add(entry);
  _tblSyncSelectionGate(entry);
  _tblBindResizeGateOnce();

  wrap.addEventListener("mousedown", (e) => {
    if (!_tblSelectionAllowed()) return;
    if (e.button !== 0) return;
    const cell = e.target.closest("td, tr.totals th");
    if (!cell || !wrap.contains(cell)) return;
    const pos = _tblCellPos(cell, table);
    if (!pos) return;
    _tblActiveSel = sel;
    if (e.shiftKey) {
      // Shift+клик — расширение от якоря; без прежнего якоря клик заводит
      // выделение одной ячейкой (та же клетка становится и якорем, и фокусом).
      if (!cs.anchor) cs.anchor = pos;
      cs.focus = pos;
      _tblRenderSelection(sel);
      _tblArmClickGuard(sel);
      e.preventDefault();
      return;
    }
    _tblInteraction(wrap,"drag",true);
    const drag = { startX: e.clientX, startY: e.clientY, cell: pos, moved: false };
    const onMove = (ev) => {
      const dx = ev.clientX - drag.startX, dy = ev.clientY - drag.startY;
      // Порог сдвига 3px: меньше — это клик, событие уходит дальше (drill в
      // сигналах обязан продолжать открываться, signals-table.js:243).
      if (!drag.moved && Math.max(Math.abs(dx), Math.abs(dy)) < 3) return;
      const over = document.elementFromPoint(ev.clientX, ev.clientY);
      const overCell = over && over.closest("td, tr.totals th");
      if (!overCell || !wrap.contains(overCell)) return;
      const overPos = _tblCellPos(overCell, table);
      if (!overPos) return;
      if (!drag.moved) { drag.moved = true; cs.anchor = drag.cell; }
      cs.focus = overPos;
      _tblRenderSelection(sel);
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      const set=_tblGestureCleanup.get(wrap);if(set)set.delete(onUp);
      _tblInteraction(wrap,"drag",false);
      if (drag.moved) { _tblArmClickGuard(sel); return; }
      // Клик без протяжки — жест «снять выделение» (правка владельца
      // 2026-08-15). Гард НЕ взводится и событие не гасится: клик обязан
      // дойти до домена, иначе drill в блоке сигналов перестал бы
      // открываться — там снятие выделения и открытие карточки происходят
      // одним и тем же кликом.
      if (cs.anchor || cs.focus) {
        cs.anchor = null;
        cs.focus = null;
        _tblRenderSelection(sel);
      }
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    _tblRememberGesture(wrap,onUp);
  });

  _tblBindClickGuardOnce();
  _tblBindCopyOnce();
}

// Release per-table resources when a consumer removes a view. Existing consumers
// may continue to rely on the legacy sweep; portable mounts dispose explicitly.
function tblDispose(wrap, cs) {
  const callbacks=[...(_tblInteractionObservers.get(wrap)||[])],tokens=[...(_tblInteractionActive.get(wrap)||[])];
  _tblInteractionObservers.delete(wrap);_tblInteractionActive.delete(wrap);
  // Releasing may commit a pending report: finish this local redraw first.
  if(tokens.length)queueMicrotask(()=>{for(const token of tokens)for(const cb of callbacks)cb({token,active:false});});
  const cleanups=_tblGestureCleanup.get(wrap);if(cleanups){for(const cleanup of [...cleanups])cleanup();_tblGestureCleanup.delete(wrap);}
  if(_tblOpenMenuNode?._ownerWrap===wrap)_tblCloseFilterMenu();
  if (cs._autoWrapEntry && cs._autoWrapEntry.wrap === wrap) {
    _tblAutoWraps.delete(cs._autoWrapEntry);
    cs._autoWrapEntry = null;
    if (cs._autoRO) { cs._autoRO.disconnect(); cs._autoRO = null; _tblAutoObservers--; }
    cs._autoSig = null;
  }
  for (const entry of Array.from(_tblSelectionWraps)) {
    if (entry.wrap === wrap) { entry.sel.bar.remove(); _tblSelectionWraps.delete(entry); }
  }
  if (_tblActiveSel && _tblActiveSel.wrap === wrap) _tblActiveSel = null;
  _tblCapRows.delete(wrap);
}

if (typeof window !== "undefined") {
  Object.assign(window, { tblColState, tblApplyWidths, tblColgroup, tblCycleSort,
    tblP90, tblColumnWidths, _tblMeasureText, _tblFontOf, _tblAutoObserverCount, _tblAutoWrapCount,
    tblAttachResize, tblHeadCell, tblMarkIssue, tblSortByColumn, tblWrap, tblCapRows, TBL_VISIBLE_ROWS,
    tblExportRows, tblExportCsv, tblEnableSelection, tblRangeCells, tblRangeStats,
    tblHasSelection, tblDispose, tblObserveInteractions,
    tblFilterRows, tblSearchRows, tblApplyFilters, tblFilterValues, tblSearchBar,
    _tblSelectionWrapCount });
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = { tblColState, tblApplyWidths, tblColgroup, tblCycleSort,
    tblP90, tblColumnWidths, _tblMeasureText, _tblFontOf, _tblAutoObserverCount, _tblAutoWrapCount,
    tblAttachResize, tblHeadCell, tblMarkIssue, tblSortByColumn, tblWrap, tblCapRows, TBL_VISIBLE_ROWS,
    tblExportRows, tblExportCsv, tblEnableSelection, tblRangeCells, tblRangeStats,
    tblHasSelection, tblDispose, tblObserveInteractions,
    tblFilterRows, tblSearchRows, tblApplyFilters, tblFilterValues, tblSearchBar,
    _tblSelectionWrapCount };
}
