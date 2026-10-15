"""[SAFETY] Миграции канона обязаны воспроизводить схему прод-БД.

Прод ушёл на миграцию 0030 раньше канона, и расхождение сред уже ломало проект:
код проверялся на схеме, отличной от той, куда его деплоили. Опись объектов прода
зафиксирована в prod_schema_objects.txt, поэтому тест выполняется всегда и не
требует доступа к проду.

Снимок сравнивается по системному каталогу PostgreSQL (pg_attribute/pg_constraint/
pg_index/pg_trigger), а не по regex-разбору текста pg_dump: колонки таблиц с типом
и NOT NULL, констрейнты ВСЕХ видов (включая CHECK) с их полным определением через
pg_get_constraintdef, индексы через pg_get_indexdef, триггеры через
pg_get_triggerdef. Сравнение двустороннее — лишнее локально ловится наравне с
недостающим, потому что расхождение схем в любую сторону означает несовпадение
кода и прода.

Исторический prod_schema_objects.txt был собран миграциями 0001–0030 к чистой тестовой
схеме и СВЕРЕН С БОЕВОЙ БД 2026-08-05: те же четыре каталожных запроса, выполненные
против схемы public базы job_machine на lab-do, дали ровно эти же 507 объектов,
расхождений ноль. То есть фикстура — одновременно и «что производят миграции», и
«что есть в проде», и это проверено, а не предположено.

Обновление 2026-10-15: fixture получен read-only из production после 0035 и
сверен с локальными миграциями; evidence audit/baseline/catalog-parity.json.
Таблица reconcile_snapshot_20260806 исключена как исторический операционный снимок.
NOT NULL проверяется через attnotnull; дополнительный contype n локального PG18
не дублируется в constraints при сравнении с PG15.

Дальнейшая ценность теста двойная: поймать тихое изменение схемы миграциями без
осознанного обновления фикстуры в PR, и поймать повторный уход прода вперёд кода —
для второго достаточно пересобрать фикстуру теми же запросами против прода и
увидеть ненулевой диф.
"""
import os
from pathlib import Path

import pytest

from tests.conftest import apply_migrations

_EXPECTED = Path(__file__).with_name("prod_schema_objects.txt")

_CONTYPE_LABELS = {
    "c": "check",
    "p": "primary_key",
    "f": "foreign_key",
    "u": "unique",
    "x": "exclusion",
}

_COLUMNS_SQL = """
    select c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull
    from pg_attribute a
    join pg_class c on c.oid = a.attrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = %s
      and c.relkind = 'r'
      and a.attnum > 0
      and not a.attisdropped
    order by c.relname, a.attnum
"""

_CONSTRAINTS_SQL = """
    select c.relname, con.conname, con.contype, pg_get_constraintdef(con.oid)
    from pg_constraint con
    join pg_class c on c.oid = con.conrelid
    join pg_namespace n on n.oid = con.connamespace
    where n.nspname = %s and con.contype <> 'n'
    order by c.relname, con.conname
"""

_INDEXES_SQL = """
    select c.relname, i.relname, pg_get_indexdef(i.oid)
    from pg_index ix
    join pg_class c on c.oid = ix.indrelid
    join pg_class i on i.oid = ix.indexrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = %s
    order by c.relname, i.relname
"""

_TRIGGERS_SQL = """
    select c.relname, t.tgname, pg_get_triggerdef(t.oid)
    from pg_trigger t
    join pg_class c on c.oid = t.tgrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = %s
      and not t.tgisinternal
    order by c.relname, t.tgname
"""


def _denormalize(schema: str, text: str) -> str:
    """Strip the random per-run temp schema name out of a catalog definition.

    pg_get_*def() functions normally omit the schema prefix for same-schema
    references, but stay defensive in case a future object qualifies it
    explicitly (e.g. a cross-schema FK) — otherwise every test run would
    mismatch the fixture on the schema name alone.
    """
    return text.replace(f'"{schema}".', "").replace(f"{schema}.", "")


def _snapshot_schema(conn, schema: str) -> set[str]:
    """Catalog snapshot of one schema: columns, constraints, indexes, triggers."""
    objects: set[str] = set()
    with conn.cursor() as cur:
        cur.execute(_COLUMNS_SQL, (schema,))
        for table, column, data_type, not_null in cur.fetchall():
            nullability = "NOT NULL" if not_null else "NULL"
            objects.add(f"column:{table}.{column}:{data_type}:{nullability}")

        cur.execute(_CONSTRAINTS_SQL, (schema,))
        for table, name, contype, definition in cur.fetchall():
            kind = _CONTYPE_LABELS.get(contype, contype)
            definition = _denormalize(schema, definition)
            objects.add(f"constraint:{table}.{name}:{kind}:{definition}")

        cur.execute(_INDEXES_SQL, (schema,))
        for table, name, definition in cur.fetchall():
            definition = _denormalize(schema, definition)
            objects.add(f"index:{table}.{name}:{definition}")

        cur.execute(_TRIGGERS_SQL, (schema,))
        for table, name, definition in cur.fetchall():
            definition = _denormalize(schema, definition)
            objects.add(f"trigger:{table}.{name}:{definition}")
    return objects


@pytest.mark.db
def test_migrations_reproduce_production_schema(db_schema):
    conn, schema = db_schema
    apply_migrations(conn)
    conn.commit()

    local = _snapshot_schema(conn, schema)
    expected = {
        line.rstrip("\n")
        for line in _EXPECTED.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }

    missing = sorted(expected - local)
    extra = sorted(local - expected)
    assert not missing and not extra, (
        f"canon migrations do not reproduce the recorded schema — "
        f"missing: {missing}; extra (undocumented locally-only): {extra}"
    )
