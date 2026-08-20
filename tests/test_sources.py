from app.sources import upsert_source
from tests._fakes import FakeCursor


def test_upsert_source_grava_quarentena_e_ativo_true():
    cur = FakeCursor(fetchone_results=[("source-id",)])

    source_id = upsert_source(cur, "Fonte X", "telegram", "https://exemplo.com")

    assert source_id == "source-id"
    sql, params = cur.queries[0]
    assert "insert into sources" in sql
    assert "true" in sql  # quarentena e ativo hardcoded true no insert
    assert "Fonte X" in params and "telegram" in params
