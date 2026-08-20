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


def _etapa(nome, status, ordem, itens_ok=0, itens_erro=0, detalhe=None):
    return EstadoEtapaDetalhado(nome=nome, ordem=ordem, status=status, itens_ok=itens_ok, itens_erro=itens_erro, detalhe=detalhe or {})


_ESTADO_LIBERADO = EstadoRun(
    existe=True, status="pronto", etapa_atual="slate",
    etapas=(
        _etapa("fixtures", "ok", 1), _etapa("coleta", "ok", 2), _etapa("extracao", "ok", 3),
        _etapa("matching", "ok", 4), _etapa("odds", "ok", 5), _etapa("slate", "ok", 6),
    ),
)


def test_envio_bloqueado_quando_slate_nao_aprovado():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(fetchall_results=[[]], fetchone_results=[("slate-1", "rascunho", None)])
    app.dependency_overrides[get_cursor] = lambda: cur

    resposta = client.get("/envio")

    assert resposta.status_code == 200
    assert "aprovado" in resposta.text


def test_envio_liberado_mostra_fila_vazia():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(
        fetchall_results=[[], []],  # expirar_mensagens_vencidas, fila_envio
        fetchone_results=[("slate-1", "aprovado", None), (0, 0, 0)],  # buscar_slate_atual, contadores_do_dia
    )
    app.dependency_overrides[get_cursor] = lambda: cur

    resposta = client.get("/envio")

    assert resposta.status_code == 200
    assert "Nenhuma mensagem pronta" in resposta.text


def test_envio_liberado_mostra_mensagem_agrupada_por_assinante():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    fila_row = (
        "msg-1", "u1", "Emmanuel", "+5511999991111", "palpite", "fix-1", "Avai", "CRB", _KICKOFF,
        "Fala Emmanuel, olha o jogo:\n\nAvai x CRB", datetime(2026, 8, 11, 16, 0, tzinfo=timezone.utc),
    )
    cur = FakeCursor(
        fetchall_results=[[], [fila_row]],
        fetchone_results=[("slate-1", "aprovado", None), (1, 0, 0)],
    )
    app.dependency_overrides[get_cursor] = lambda: cur

    resposta = client.get("/envio")

    assert resposta.status_code == 200
    assert "Emmanuel" in resposta.text
    assert "wa.me/5511999991111" in resposta.text
    assert "Avai x CRB" in resposta.text


def test_post_marcar_enviada_sucesso():
    cur = FakeCursor(fetchone_results=[("msg-1",)])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/msg-1/enviada", headers=_ORIGEM)

    assert resposta.status_code == 303
    assert any("status = 'enviada'" in q[0] for q in cur.queries)


def test_post_marcar_enviada_sem_origem_recusada():
    cur = FakeCursor()
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/msg-1/enviada")

    assert resposta.status_code == 403
    assert cur.queries == []


def test_post_pular_exige_motivo():
    cur = FakeCursor()
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/msg-1/pular", data={"motivo": "  "}, headers=_ORIGEM)

    assert resposta.status_code == 400
    assert cur.queries == []


def test_post_pular_sucesso():
    cur = FakeCursor(fetchone_results=[("msg-1",)])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/msg-1/pular", data={"motivo": "assinante pediu"}, headers=_ORIGEM)

    assert resposta.status_code == 303
    assert any("status = 'pulada'" in q[0] for q in cur.queries)


def test_post_marcar_enviada_sem_modo_redireciona_pra_envio_manual():
    # Regressao (Fase 5d-D): rotas antigas, sem campo modo no form,
    # continuam indo pra /envio - nunca pra /envio/sessao por padrao.
    cur = FakeCursor(fetchone_results=[("msg-1",)])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/msg-1/enviada", headers=_ORIGEM)

    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/envio"


def test_post_marcar_enviada_modo_sessao_redireciona_pra_envio_sessao():
    cur = FakeCursor(fetchone_results=[None, ("msg-1",)])  # buscar_sessao_aberta (sem sessao), marcar_enviada
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/msg-1/enviada", data={"modo": "sessao"}, headers=_ORIGEM)

    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/envio/sessao"


def test_post_marcar_enviada_modo_sessao_com_sessao_pausada_recusada():
    sessao_pausada = ("sessao-1", None, "slate-1", "pausada", None, None, None, None)
    cur = FakeCursor(fetchone_results=[sessao_pausada])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/msg-1/enviada", data={"modo": "sessao"}, headers=_ORIGEM)

    assert resposta.status_code == 409
    # marcar_enviada nunca chegou a executar - so a consulta de sessao aberta rodou
    assert len(cur.queries) == 1


def test_post_marcar_enviada_modo_manual_ignora_sessao_pausada():
    # D14: pausa e ESTREITA - o modo manual nunca e bloqueado por uma
    # sessao pausada, mesmo que ela exista.
    cur = FakeCursor(fetchone_results=[("msg-1",)])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/envio/msg-1/enviada", headers=_ORIGEM)

    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/envio"
