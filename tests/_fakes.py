"""Duplos de teste para psycopg.Cursor/Connection, usados pelos testes de
scripts que fazem upsert (seed_team_aliases, collect_fixtures). Nao e um
arquivo de teste - nao comeca com test_, pytest nao coleta daqui."""


class FakeCursor:
    """So entende execute()/fetchone()/fetchall(), com filas de
    resultados pre-programadas na ordem em que serao consumidas."""

    def __init__(self, fetchone_results=None, fetchall_results=None):
        self._fetchone_results = list(fetchone_results or [])
        self._fetchall_results = list(fetchall_results or [])
        self.queries: list[tuple[str, tuple]] = []

    def execute(self, sql, params=None):
        self.queries.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._fetchone_results.pop(0)

    def fetchall(self):
        return self._fetchall_results.pop(0)


class FakeConnection:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self

    def __enter__(self):
        return self._cursor

    def __exit__(self, *exc):
        return False

    def commit(self):
        self.committed = True
