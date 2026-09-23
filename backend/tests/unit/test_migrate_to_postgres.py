import sqlite3

import migrate_to_postgres as migrator


class _FakePostgresCursor:
    def __init__(self):
        self.executed: list[tuple[str, list[object]]] = []
        self._last_sql = ""

    def execute(self, sql: str, values: list[object] | None = None):
        self._last_sql = sql
        self.executed.append((sql, values or []))

    def fetchall(self):
        if "information_schema.columns" in self._last_sql:
            return [
                ("id", "uuid", "uuid"),
                ("embedding", "USER-DEFINED", "vector"),
                ("metadata", "jsonb", "jsonb"),
            ]
        return []

    def close(self):
        return None


class _FakePostgresConnection:
    def __init__(self):
        self.cursor_obj = _FakePostgresCursor()
        self.commit_calls = 0
        self.rollback_calls = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1


def test_safe_json_handles_none_and_invalid_strings():
    assert migrator._safe_json(None) == "{}"
    assert migrator._safe_json('{"ok": true}') == '{"ok": true}'
    assert migrator._safe_json("not-json") == '"not-json"'


def test_migrate_generic_serializes_jsonb_and_vector_from_sqlite():
    sqlite_conn = sqlite3.connect(":memory:")
    sqlite_conn.execute(
        """
        CREATE TABLE face_data (
            id TEXT PRIMARY KEY,
            embedding TEXT,
            metadata TEXT
        )
        """
    )
    sqlite_conn.execute(
        "INSERT INTO face_data (id, embedding, metadata) VALUES (?, ?, ?)",
        ("fd-1", "[0.1, 0.2, 0.3]", '{"source":"seed"}'),
    )
    sqlite_conn.commit()

    pg_conn = _FakePostgresConnection()

    migrator._migrate_generic(
        sqlite_conn=sqlite_conn,
        pg_conn=pg_conn,
        table_name="face_data",
        columns=["id", "embedding", "metadata"],
        jsonb_columns=["metadata"],
        vector_columns=["embedding"],
    )

    assert pg_conn.commit_calls == 1
    assert pg_conn.rollback_calls == 0
    insert_calls = [
        call for call in pg_conn.cursor_obj.executed if call[0].lstrip().startswith("INSERT")
    ]
    assert len(insert_calls) == 1

    sql, values = insert_calls[0]
    assert "embedding" in sql
    assert "%s::vector" in sql
    assert "%s::jsonb" in sql
    assert values[0] == "fd-1"
    assert values[1] == "[0.1, 0.2, 0.3]"
    assert values[2] == '{"source":"seed"}'


def test_migrate_generic_skips_missing_table_without_commits():
    sqlite_conn = sqlite3.connect(":memory:")
    pg_conn = _FakePostgresConnection()

    migrator._migrate_generic(
        sqlite_conn=sqlite_conn,
        pg_conn=pg_conn,
        table_name="does_not_exist",
        columns=["id"],
    )

    assert pg_conn.commit_calls == 0
    assert pg_conn.rollback_calls == 0
    assert pg_conn.cursor_obj.executed == []
