from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from app.console.deps import estado_run_hoje, get_conexao, get_cursor
from app.console.main import create_app
from app.console.queries import EstadoEtapaDetalhado, EstadoRun
from tests._fakes import FakeConnection, FakeCursor

_ORIGEM = {"origin": "http://127.0.0.1:8000"}


@pytest.fixture(autouse=True)
def _limpar_overrides():
    yield
    app.dependency_overrides.clear()


app = create_app()
client = TestClient(app, follow_redirects=False)

_KICKOFF = datetime(2026, 8, 11, 22, 30, tzinfo=timezone.utc)
_GERADA = datetime(2026, 8, 11, 16, 0, tzinfo=timezone.utc)
_INICIADA_EM = datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)


def _etapa(nome, status, ordem, itens_ok=0, itens_erro=0, detalhe=None):
    return EstadoEtapaDetalhado(nome=nome, ordem=ordem, status=status, itens_ok=itens_ok, itens_erro=itens_erro, detalhe=detalhe or {})


_ESTADO_LIBERADO = EstadoRun(
    existe=True, status="pronto", etapa_atual="slate",
    etapas=(
        _etapa("fixtures", "ok", 1), _etapa("coleta", "ok", 2), _etapa("extracao", "ok", 3),
        _etapa("matching", "ok", 4), _etapa("odds", "ok", 5), _etapa("slate", "ok", 6),
    ),
)

_FILA_ROW_U1 = (
    "msg-1", "u1", "Emmanuel", "+5511999991111", "palpite", "fix-1", "Avai", "CRB", _KICKOFF,
    "Fala Emmanuel, olha o jogo:\n\nAvai x CRB", _GERADA,
)

_SESSAO_ROW = ("sessao-1", None, "slate-1", "ativa", _INICIADA_EM, None, None, None)


def test_get_envio_sessao_bloqueado_quando_slate_nao_aprovado():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(fetchall_results=[[]], fetchone_results=[("slate-1", "rascunho", None)])
    app.dependency_overrides[get_cursor] = lambda: cur

    resposta = client.get("/envio/sessao")

    assert resposta.status_code == 200
    assert "aprovado" in resposta.text


def test_get_envio_sessao_liberado_sem_sessao_e_sem_paradas():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(
        fetchall_results=[[], [], []],  # expirar, universo, fila
        fetchone_results=[("slate-1", "aprovado", None), None],  # slate_atual, sessao_aberta
    )
    app.dependency_overrides[get_cursor] = lambda: cur

    resposta = client.get("/envio/sessao")

    assert resposta.status_code == 200
    assert "Nenhuma sess" in resposta.text
    assert "pronta" in resposta.text


def test_get_envio_sessao_liberado_sem_sessao_com_paradas_mostra_botao_iniciar():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(
        fetchall_results=[[], [("u1",)], [_FILA_ROW_U1]],
        fetchone_results=[("slate-1", "aprovado", None), None],
    )
    app.dependency_overrides[get_cursor] = lambda: cur

    resposta = client.get("/envio/sessao")

    assert resposta.status_code == 200
    assert "Iniciar sess" in resposta.text


def test_get_envio_sessao_com_sessao_aberta_mostra_parada_em_foco():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(
        fetchall_results=[[], [("u1",)], [_FILA_ROW_U1]],
        fetchone_results=[("slate-1", "aprovado", None), _SESSAO_ROW],
    )
    app.dependency_overrides[get_cursor] = lambda: cur

    resposta = client.get("/envio/sessao")

    assert resposta.status_code == 200
    assert "Emmanuel" in resposta.text
    assert "wa.me/5511999991111" in resposta.text
    assert "parada" in resposta.text.lower()


def test_get_envio_sessao_com_sessao_e_fila_vazia_encerra_sozinha_e_mostra_resumo():
    # D13: fila zerou (universo e fila ambos vazios) - a sessao aberta e
    # auto-encerrada (motivo='fila_vazia') na mesma requisicao, e a tela
    # mostra o resumo em vez dos controles de uma sessao ainda aberta.
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(
        fetchall_results=[[], [], [], [("Fulano", "+5511999990000", "nao atende")]],
        fetchone_results=[("slate-1", "aprovado", None), _SESSAO_ROW, ("sessao-1",), (3, 1, 2)],
    )
    app.dependency_overrides[get_cursor] = lambda: cur

    resposta = client.get("/envio/sessao")

    assert resposta.status_code == 200
    assert "Fulano" in resposta.text
    assert "nao atende" in resposta.text
    assert "Nenhuma sess" in resposta.text  # sessao ja None apos o auto-encerramento
    sql, params = next(q for q in cur.queries if "status = 'encerrada'" in q[0])
    assert params == ("sistema", "fila_vazia", "sessao-1")


def test_post_iniciar_sessao_sucesso():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(
        fetchall_results=[[("u1",)], [_FILA_ROW_U1]],
        fetchone_results=[("slate-1", "aprovado", None), None, ("sessao-1",)],
    )
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/sessao/iniciar", headers=_ORIGEM)

    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/envio/sessao"


def test_post_iniciar_sessao_sem_origem_recusada():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor()
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/sessao/iniciar")

    assert resposta.status_code == 403
    assert cur.queries == []


def test_post_iniciar_sessao_slate_nao_aprovado_409():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(fetchone_results=[("slate-1", "rascunho", None)])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/sessao/iniciar", headers=_ORIGEM)

    assert resposta.status_code == 409


def test_post_iniciar_sessao_ja_existe_sessao_aberta_409():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(
        fetchall_results=[[("u1",)], [_FILA_ROW_U1]],
        fetchone_results=[("slate-1", "aprovado", None), _SESSAO_ROW],
    )
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/sessao/iniciar", headers=_ORIGEM)

    assert resposta.status_code == 409


def test_post_iniciar_sessao_race_apos_checagem_409():
    # TOCTOU legitimo: acesso_sessao.pode_iniciar passou, mas outra
    # requisicao inseriu a sessao entre a checagem e o INSERT (resolvido
    # no banco pelo indice parcial + ON CONFLICT DO NOTHING).
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(
        fetchall_results=[[("u1",)], [_FILA_ROW_U1]],
        fetchone_results=[("slate-1", "aprovado", None), None, None],
    )
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/sessao/iniciar", headers=_ORIGEM)

    assert resposta.status_code == 409


def test_post_pausar_sessao_falha_apos_gate_409():
    # sessao aberta encontrada e e a certa, mas pausar_sessao devolve
    # False (ex.: outra requisicao concorrente ja pausou/encerrou entre a
    # checagem e o UPDATE).
    cur = FakeCursor(fetchone_results=[_SESSAO_ROW, None])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/sessao/sessao-1/pausar", headers=_ORIGEM)

    assert resposta.status_code == 409


def test_post_retomar_sessao_falha_apos_gate_409():
    cur = FakeCursor(fetchone_results=[_SESSAO_ROW, None])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/sessao/sessao-1/retomar", headers=_ORIGEM)

    assert resposta.status_code == 409


def test_post_pausar_sessao_sucesso():
    cur = FakeCursor(fetchone_results=[_SESSAO_ROW, ("sessao-1",)])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/sessao/sessao-1/pausar", headers=_ORIGEM)

    assert resposta.status_code == 303
    assert any("status = 'pausada'" in q[0] for q in cur.queries)


def test_post_pausar_sessao_id_diferente_da_sessao_aberta_409():
    cur = FakeCursor(fetchone_results=[_SESSAO_ROW])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/sessao/outra-sessao/pausar", headers=_ORIGEM)

    assert resposta.status_code == 409


def test_post_retomar_sessao_sucesso():
    sessao_pausada = ("sessao-1", None, "slate-1", "pausada", _INICIADA_EM, _INICIADA_EM, None, None)
    cur = FakeCursor(fetchone_results=[sessao_pausada, ("sessao-1",)])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/sessao/sessao-1/retomar", headers=_ORIGEM)

    assert resposta.status_code == 303
    assert any("status = 'ativa'" in q[0] for q in cur.queries)


def test_post_encerrar_sessao_sucesso():
    cur = FakeCursor(fetchone_results=[_SESSAO_ROW, ("sessao-1",)])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/sessao/sessao-1/encerrar", headers=_ORIGEM)

    assert resposta.status_code == 303
    assert any("status = 'encerrada'" in q[0] for q in cur.queries)


def test_post_encerrar_sessao_sem_origem_403():
    cur = FakeCursor()
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/sessao/sessao-1/encerrar")

    assert resposta.status_code == 403
    assert cur.queries == []


def test_sessao_js_carrega_so_na_pagina_de_sessao():
    # sessao.js e cosmetico e so faz sentido com uma parada em foco - as
    # outras paginas do console nunca devem carrega-lo.
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(
        fetchall_results=[[], [("u1",)], [_FILA_ROW_U1]],
        fetchone_results=[("slate-1", "aprovado", None), _SESSAO_ROW],
    )
    app.dependency_overrides[get_cursor] = lambda: cur

    resposta_sessao = client.get("/envio/sessao")
    assert "sessao.js" in resposta_sessao.text

    app.dependency_overrides.clear()
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur2 = FakeCursor(fetchall_results=[[], []], fetchone_results=[("slate-1", "aprovado", None), (0, 0, 0)])
    app.dependency_overrides[get_cursor] = lambda: cur2

    resposta_manual = client.get("/envio")
    assert "sessao.js" not in resposta_manual.text
