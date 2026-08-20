from app.console.acoes import marcar_enviada, pular, regerar_corpos
from tests._fakes import FakeCursor


def test_marcar_enviada_idempotente_via_where_status_pronta():
    cur = FakeCursor(fetchone_results=[("msg-1",)])

    resultado = marcar_enviada(cur, "msg-1")

    assert resultado is True
    sql, params = cur.queries[0]
    assert "status='enviada'" in sql or "status = 'enviada'" in sql
    assert "status = 'pronta'" in sql
    assert params == ("msg-1",)


def test_marcar_enviada_segunda_chamada_retorna_false():
    cur = FakeCursor(fetchone_results=[None])

    assert marcar_enviada(cur, "msg-1") is False


def test_pular_exige_motivo_nao_vazio():
    cur = FakeCursor(fetchone_results=[("msg-1",)])

    resultado = pular(cur, "msg-1", "assinante pediu pra nao receber hoje")

    assert resultado is True
    sql, params = cur.queries[0]
    assert "status = 'pulada'" in sql
    assert "motivo_pulo" in sql
    assert params == ("assinante pediu pra nao receber hoje", "msg-1")


def test_pular_motivo_vazio_levanta_erro():
    import pytest

    cur = FakeCursor()

    with pytest.raises(ValueError):
        pular(cur, "msg-1", "   ")

    assert cur.queries == []


def test_regerar_corpos_so_toca_pronta_e_conta_atualizadas():
    cur = FakeCursor(fetchone_results=[("msg-1",), None])

    atualizadas = regerar_corpos(cur, {"msg-1": "novo corpo", "msg-2": "outro corpo"})

    assert atualizadas == 1
    assert all("status = 'pronta'" in q[0] for q in cur.queries)
