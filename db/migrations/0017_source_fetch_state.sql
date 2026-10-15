-- 0017_source_fetch_state.sql — межпроходный троттлинг для rate-limited источников
-- дискавери (Remotive, Jobicy и т.п.). Хранит давность последнего фетча по
-- source_key, чтобы discovery-воркер мог пропускать проход без ошибки, если
-- лимит частоты провайдера ещё не истёк. Интеграция в run_discovery_multi —
-- отдельная задача (Task 4), эта миграция — только инфраструктура.
CREATE TABLE source_fetch_state (
    source_key TEXT PRIMARY KEY,
    last_fetched_at TIMESTAMPTZ,
    last_status TEXT
);
