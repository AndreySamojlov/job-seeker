# Experience Cloud — runbook

## Назначение

Experience Cloud — единственный источник опыта и скиллов для будущей генерации
резюме (английский, claim→proof). Хранит позиции, достижения с метрикой/статусом и
навыки с honesty-границами. Данные загружаются в Postgres и используются воркерами
при сборке пакета заявки.

## Формат файла

Три pipe-таблицы в одном Markdown-документе.

### Positions

| pid | company | title | start | end | location | summary |
|---|---|---|---|---|---|---|
| P-01 | Company | Role | YYYY-MM | present | City | One-liner |

### Achievements

| aid | pid | text | metric | status | claims | safe_use |
|---|---|---|---|---|---|---|
| A-01 | P-01 | Description | ~N | approximate/exact | C-XXX | Safe phrasing |

- **status**: `exact` или `approximate`
- **claims**: ссылки на claim-коды из career-evidence-vault (через запятую)
- **safe_use**: формулировка, безопасная для использования без вымысла

### Skills

| name | category | framing | evidence | safe_use |
|---|---|---|---|---|
| Python | skill | Fundamentals | C-014 | never commercial |

- **safe_use**: ограничение, которое нельзя нарушать в заявках

## Загрузка

### Переменная окружения

```
EXPERIENCE_CLOUD_PATH=<путь к experience-cloud.md>
```

### Команда

```bash
uv run python -m job_machine.cloud.load_experience_cloud "<путь к experience-cloud.md>"
```

Вывод: `loaded N positions, N achievements, N skills`

### Идемпотентность

Загрузчик использует upsert по PK (`pid`, `aid`, `name`). Можно запускать повторно
после каждого обновления cloud-файла — дублей не возникнет, существующие записи
обновятся.

## Honesty-границы

Ограничения (Python без commercial CI/CD/Linux/JS, English B2 и т.д.) живут в самом
cloud-файле в колонке `safe_use`. Воркеры читают их из БД и не выдумывают ничего
сверх того, что там записано.
