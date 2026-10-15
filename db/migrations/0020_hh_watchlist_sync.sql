-- Идемпотентность синка hh.ru-вакансий в company_watchlist (см. дизайн
-- docs/superpowers/specs/2026-07-17-hh-ru-sourcing-design.md §6). Не трогает
-- core vacancy-таблицу — отдельная маленькая таблица-отметка.

create table if not exists hh_watchlist_sync (
    vacancy_id  uuid primary key references vacancy(vacancy_id),
    synced_at   timestamptz not null default now()
);
