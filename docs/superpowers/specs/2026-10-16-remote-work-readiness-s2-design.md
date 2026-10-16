# RWR.S2 — отображение индекса в борде

Дата: 16 октября 2026. Уровень: Story technical design. Родитель: [Epic Intent](../../remote-work-readiness-intent.md); [Decomposition Map](../../decomposition-map.md). Статус: технический проект для реализации.

## Цель и граница

Добавить в существующую борду вакансий отдельную колонку международной удалёнки. Она показывает только сохранённый завершённый индекс, форматируя исходную Jev fraction `n` как `n × 100` с одним десятичным знаком и `%`. Отсутствующий результат показывается `—`, а валидный ноль — `0.0%`. Никакие версии/объяснения не выводятся.

Это read-only потребитель S1. Story не запускает Jev, не создаёт задания, не меняет triage, candidate fit, фильтры, очередь и действия с откликом. Колонка не должна инициировать или менять сортировку; для неё требуется generic presentation flag Cockpit Engine `sortable: false`. Серверный ключ сортировки и column filters остаются без RWR-поля.

## Факты и решение

- Board report строится в `job_machine.board.repository.load_greenhouse_snapshot` и `job_machine.board.greenhouse.build_greenhouse_report`; сортировка/таблица рендерятся Cockpit Engine.
- Таблица RWR хранит только сырой `value` 0–1 для `status='completed'`; другой статус и отсутствие строки должны давать SQL NULL.
- У текущего Engine нет процентного форматирования и флага несортируемой колонки. Эти возможности добавляются общими presentation-полями колонки, без RWR-specific логики в Engine.
- Контракт Engine: `format: "percent"` отображает конечное numeric значение как percentage с одним знаком после десятичной точки и локализованной запятой; JSON значение и числовое сравнение остаются исходными. `sortable: false` выводит статическую ячейку заголовка без кнопки/обработчика сортировки. Отсутствующие поля сохраняют старое поведение.
- Consumer хранит и отдаёт raw fraction. Для строки добавляется выделенный ключ, например `remote_work_readiness`; он не включается в `SORT_KEYS` или `TEXT_FIELDS`/numeric filters.
- Колонка называется «Международная удалёнка», тип number, format percent, sortable false, без filter. Другие показатели и дефолтная сортировка не меняются.

## Проверки

- Engine DOM/runtime tests доказывают `0 → 0,0%`, `0.314159… → 31,4%`, `1 → 100,0%`, NULL → dash, сохранение сортировки чисел по raw fraction и отсутствие интерактивной сортировки у `sortable:false`.
- Engine regression tests подтверждают неизменность старого поведения всех колонок без новых полей.
- Consumer unit и guarded PostgreSQL tests доказывают, что только completed строки читаются, NULL отличается от zero, значения не округляются в API payload, а версии и объяснения не публикуются.
- Board API/UI synthetic check подтверждает единственную отдельную колонку и отсутствие RWR в server sort/filter allowlists.

## Версии и интеграция

Изменение generic Engine поставляется новым immutable consumer wheel с provenance/hash по локальным правилам. До публикации consumer проверяется на точной версии этого wheel. Существующие board assets и клиентская сортировка сохраняются byte-identical, если они не входят в обоснованный generic patch.
