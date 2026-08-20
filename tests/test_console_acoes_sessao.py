from datetime import date

from app.console.acoes import encerrar_sessao, iniciar_sessao, pausar_sessao, retomar_sessao
from tests._fakes import FakeCursor

_DATA = date(2026, 8, 11)


def test_iniciar_sessao_sucesso_devolve_id():
    cur = FakeCursor(fetchone_results=[("sessao-1",)])

    resultado = iniciar_sessao(cur, _DATA, "slate-1", "console")

    assert resultado == "sessao-1"
    sql, params = cur.queries[0]
    assert "insert into envio_sessoes" in sql
    assert "on conflict (data) where encerrada_em is null do nothing" in sql
    assert params == (_DATA, "slate-1", "console")


def test_iniciar_sessao_conflito_devolve_none():
    # Corrida de duplo clique em "Iniciar" - resolvida no banco pelo
    # indice parcial + ON CONFLICT DO NOTHING, nunca por uma checagem
    # SELECT-antes-de-INSERT em Python (TOCTOU).
    cur = FakeCursor(fetchone_results=[None])

    assert iniciar_sessao(cur, _DATA, "slate-1", "console") is None


def test_pausar_sessao_sucesso():
    cur = FakeCursor(fetchone_results=[("sessao-1",)])

    resultado = pausar_sessao(cur, "sessao-1")

    assert resultado is True
    sql, params = cur.queries[0]
    assert "status = 'pausada'" in sql
    assert "status = 'ativa'" in sql
    assert params == ("sessao-1",)


def test_pausar_sessao_segunda_chamada_retorna_false():
    cur = FakeCursor(fetchone_results=[None])

    assert pausar_sessao(cur, "sessao-1") is False


def test_retomar_sessao_sucesso():
    cur = FakeCursor(fetchone_results=[("sessao-1",)])

    resultado = retomar_sessao(cur, "sessao-1")

    assert resultado is True
    sql, params = cur.queries[0]
    assert "status = 'ativa'" in sql
    assert "status = 'pausada'" in sql
    assert params == ("sessao-1",)


def test_retomar_sessao_segunda_chamada_retorna_false():
    cur = FakeCursor(fetchone_results=[None])

    assert retomar_sessao(cur, "sessao-1") is False


def test_encerrar_sessao_sucesso():
    cur = FakeCursor(fetchone_results=[("sessao-1",)])

    resultado = encerrar_sessao(cur, "sessao-1", "console", "manual")

    assert resultado is True
    sql, params = cur.queries[0]
    assert "status = 'encerrada'" in sql
    assert "encerrada_em is null" in sql
    assert params == ("console", "manual", "sessao-1")


def test_encerrar_sessao_segunda_chamada_retorna_false():
    cur = FakeCursor(fetchone_results=[None])

    assert encerrar_sessao(cur, "sessao-1", "console", "manual") is False
