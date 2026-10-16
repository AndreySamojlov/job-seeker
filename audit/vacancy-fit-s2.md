# Vacancy Fit S2 — локальные evidence

Дата: 16 октября 2026. Статус: локальная Story реализована и проверена; production-доставка не выполнялась.

## Результат

- Миграция `0038_vacancy_fit_preparation.sql` фиксирует однократный снимок активных кандидатов на verified INSERT/первом переходе и сериализует его с изменениями `candidate.active`. Исторический backfill и внешние вызовы отсутствуют.
- Preparation worker получает ATS description/excerpt, формирует неизменяемые S1 inputs из claims/proof, Experience Cloud и только явно разрешённых locked answers, сохраняет текст/прогресс и поддерживает retry, block и resume.
- Auto pipeline ограниченно подбирает обе очереди каждый цикл между verify и triage. Ошибки этих стадий не останавливают последующие этапы; наружу не выводятся сырые исключения.
- Jev получает только существующий immutable S1 payload. Новые данные не направлялись на внешний API в ходе S2 проверки; использовались синтетические fixtures и mock transport.

## Проверки

- Baseline unit: **1322 passed, 496 deselected**.
- Baseline smoke: **87 passed**.
- Guarded recovery DB (`scripts/check_schema.py db`): **382 passed, 1435 deselected**. Включает direct verified INSERT/transition, uniqueness, empty snapshot, no backfill, advisory-lock ordering, lease/recovery, immutable input и точный каталог схемы.
- Schema regression (`scripts/check_schema.py regression`): **2 passed**.
- Объединённые unit для `tests/fit` и `tests/pipeline`: **106 passed, 38 deselected**; новые проверки privacy/proof/lease/permanent-fact отдельно прошли **5 passed** до полного прогона.
- `git diff --check`: passed.

## Исправления по Story review

Единственный независимый review собранной Story подтвердил четыре дефекта: сырые исключения fit stages могли попасть в traceback/summary; proof claims терялся; ошибки валидации canonical facts зацикливались как retry; допустимый ATS Retry-After мог превысить 60-секундный lease. Все четыре покрыты synthetic RED→GREEN тестами. Fit-stage errors теперь имеют фиксированный код; proof сохраняется; Pydantic validation errors блокируются; lease подготовки равен 360 секундам и продлевается перед обработкой каждого кандидата.

## Schema inventory и ограничения

`tests/db/local_schema_objects.txt` содержит точный каталог локальных дополнений после миграций: `fit_job` (0036), известный production marker `company_watchlist.ru` (0037), и локальные `fit_prepare`/`fit_prepare_candidate` (0038). Историческую не связанную с S2 миграцию 0037 не изменяли. Модельные score, условия хранения данных у Jev, production key/runtime и production schema не проверялись этим Story.

Исходный `.venv` указывает на отсутствующий base Python и был недоступен для ремонта в sandbox. Проверки выполнены в `.runtime/fit-s2-venv`, созданном через `uv sync --frozen --all-groups` с bundled Python 3.12.14; lock не менялся. Изменения не закоммичены: запись `.git/index.lock` запрещена текущими filesystem permissions.
