-- Срез control-layer: явная state machine (§5 спеки). Идемпотентно.
-- Канонический lifecycle-столбец; гранулярные *_status остаются деталью.

alter table vacancy     add column if not exists state text;
alter table application add column if not exists state text;

-- Консервативный backfill только для однозначных совпадений (на пустой БД no-op).
-- Неоднозначные строки оставляем NULL — контроллер трактует NULL как начальное
-- состояние сущности.
update application set state = 'package_ready'
    where state is null and package_status = 'package_ready';
update application set state = 'submitted'
    where state is null and submit_status = 'submitted';

-- Только lifecycle-совпадения. vacancy_status вроде 'stale'/'blocked'/'inaccessible'
-- — это dead/error-состояния, НЕ lifecycle (raw_lead..triaged|skipped); намеренно
-- остаются NULL, чтобы конвейер переоценил их, а не считал валидным состоянием.
-- Не добавлять им backfill в 0003 без явного маппинга в state machine.
update vacancy set state = 'discovered'
    where state is null and vacancy_status = 'discovered';
update vacancy set state = 'verified'
    where state is null and vacancy_status = 'verified';
