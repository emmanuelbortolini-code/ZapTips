from datetime import date, datetime, timezone

import pytest
from starlette.testclient import TestClient

import app.console.rotas_saude as rotas_saude
from app.console.deps import estado_run_hoje, get_conexao, get_cursor
from app.console.main import create_app
from app.console.queries import EstadoEtapaDetalhado, EstadoRun
from tests._fakes import FakeConnection, FakeCursor


@pytest.fixture(autouse=True)
def _limpar_overrides():
    yield
    app.dependency_overrides.clear()
    rotas_saude._etapas_em_andamento.clear()


app = create_app()
client = TestClient(app, follow_redirects=False)

_ORIGEM = {"origin": "http://127.0.0.1:8000"}


def _etapa(nome, status, ordem, itens_ok=0, itens_erro=0, detalhe=None):
    return EstadoEtapaDetalhado(nome=nome, ordem=ordem, status=status, itens_ok=itens_ok, itens_erro=itens_erro, detalhe=detalhe or {})


_ESTADO_LIBERADO = EstadoRun(
    existe=True, status="pronto", etapa_atual="slate",
    etapas=(
        _etapa("fixtures", "ok", 1), _etapa("coleta", "ok", 2), _etapa("extracao", "ok", 3),
        _etapa("matching", "ok", 4), _etapa("odds", "ok", 5), _etapa("slate", "ok", 6),
    ),
)

_ESTADO_BLOQUEADO = EstadoRun(existe=False, status=None, etapa_atual=None, etapas=())


def test_raiz_redireciona_para_saude():
    resposta = client.get("/")
    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/saude"


def test_saude_responde_200():
    app.dependency_overrides[get_cursor] = lambda: FakeCursor(
        fetchone_results=[(0, None), (0,), (0,), (0,), (0,)], fetchall_results=[[], []]
    )
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_BLOQUEADO

    resposta = client.get("/saude")

    assert resposta.status_code == 200
    assert "pipeline" in resposta.text


def test_post_sincronizar_etapa_valida_agenda_e_redireciona(monkeypatch):
    chamadas = []
    monkeypatch.setattr("app.console.rotas_saude._disparar_sincronizacao", lambda etapa: chamadas.append(etapa))

    resposta = client.post("/saude/sincronizar/odds", headers=_ORIGEM)

    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/saude"
    assert chamadas == ["odds"]


def test_post_sincronizar_etapa_invalida_404(monkeypatch):
    chamadas = []
    monkeypatch.setattr("app.console.rotas_saude._disparar_sincronizacao", lambda etapa: chamadas.append(etapa))

    resposta = client.post("/saude/sincronizar/nao-existe", headers=_ORIGEM)

    assert resposta.status_code == 404
    assert chamadas == []  # nunca agenda a task pra uma etapa que nao existe


def test_post_sincronizar_etapa_ja_em_andamento_devolve_409(monkeypatch):
    # Achado do code-reviewer: dois cliques rapidos (ou um F5 antes do
    # primeiro POST voltar) nao podem agendar duas execucoes da MESMA
    # etapa em paralelo - dobraria o consumo da cota paga da OddsPapi
    # silenciosamente. O segundo POST tem que ser recusado antes de
    # sequer agendar o BackgroundTasks.
    chamadas = []
    monkeypatch.setattr("app.console.rotas_saude._disparar_sincronizacao", lambda etapa: chamadas.append(etapa))
    rotas_saude._etapas_em_andamento.add("odds")

    resposta = client.post("/saude/sincronizar/odds", headers=_ORIGEM)

    assert resposta.status_code == 409
    assert chamadas == []  # segundo clique nunca chega a agendar a task


def test_curadoria_bloqueada_quando_nao_ha_run_hoje():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_BLOQUEADO

    resposta = client.get("/curadoria")

    assert resposta.status_code == 200
    assert "nao rodou hoje" in resposta.text
    assert "<table" not in resposta.text


def test_curadoria_liberada_sem_slate_no_banco_mostra_vazio():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    app.dependency_overrides[get_cursor] = lambda: FakeCursor(fetchone_results=[None], fetchall_results=[[]])

    resposta = client.get("/curadoria")

    assert resposta.status_code == 200
    assert "Nenhum item no rascunho" in resposta.text


def test_post_remover_bloqueado_quando_gate_fechado_e_nao_escreve():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_BLOQUEADO
    cur = FakeCursor()
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/remover/sp-1", headers=_ORIGEM)

    assert resposta.status_code == 409
    assert cur.queries == []


def test_post_remover_bloqueado_quando_slate_nao_e_o_atual_de_hoje():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    # buscar_slate_atual devolve um slate diferente do pedido na URL
    cur = FakeCursor(fetchone_results=[("slate-DIFERENTE", "rascunho", None)])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/remover/sp-1", headers=_ORIGEM)

    assert resposta.status_code == 409
    assert not any("delete" in q[0] for q in cur.queries)


def test_post_remover_bloqueado_quando_slate_ja_aprovado():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(fetchone_results=[("slate-1", "aprovado", None)])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/remover/sp-1", headers=_ORIGEM)

    assert resposta.status_code == 409
    assert not any("delete" in q[0] for q in cur.queries)


def test_post_remover_sucesso_redireciona_303():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(fetchone_results=[("slate-1", "rascunho", None)])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/remover/sp-1", headers=_ORIGEM)

    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/curadoria"
    assert any("delete from slate_picks" in q[0] for q in cur.queries)


def test_post_origem_estranha_recusada_com_403():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor()
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/remover/sp-1", headers={"origin": "http://evil.example.com"})

    assert resposta.status_code == 403
    assert cur.queries == []


def test_post_sem_origem_e_recusada_com_403():
    # Falha fechado (achado MEDIUM do security-reviewer, Fase 5c).
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor()
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/remover/sp-1")

    assert resposta.status_code == 403
    assert cur.queries == []


def test_post_editar_piso_valor_invalido_400():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor()
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/piso/sp-1", data={"novo_piso": "nao-e-numero"}, headers=_ORIGEM)

    assert resposta.status_code == 400
    assert cur.queries == []


def test_post_editar_piso_abaixo_do_absoluto_400():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(fetchone_results=[("slate-1", "rascunho", None)])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/piso/sp-1", data={"novo_piso": "1.00"}, headers=_ORIGEM)

    assert resposta.status_code == 400
    assert not any("update slate_picks set odd_minima" in q[0] for q in cur.queries)


def test_post_aprovar_bloqueado_quando_ha_item_sem_odd_referencia():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    kickoff = datetime(2026, 8, 11, 21, 0, tzinfo=timezone.utc)
    item_sem_odd = (
        "sp-1", "p-1", "fix-1", 1, "automatico", "1x2", "Home", "A", "B", "Liga",
        kickoff, 1.9, "Bet365", None, None, None, "X", "Fonte",
    )
    cur = FakeCursor(
        fetchone_results=[("slate-1", "rascunho", None), None],  # buscar_slate_atual, existe_pick_quarentena_no_slate
        fetchall_results=[[item_sem_odd], []],  # itens, conflitos
    )
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/aprovar", headers=_ORIGEM)

    assert resposta.status_code == 409
    assert not any("status = 'aprovado'" in q[0] for q in cur.queries)


def test_post_aprovar_sucesso_quando_sem_bloqueios():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(
        fetchone_results=[
            ("slate-1", "rascunho", None),  # buscar_slate_atual (_exigir_pode_escrever)
            None,  # existe_pick_quarentena_no_slate (bloqueio)
            ("slate-1",),  # aprovar_slate UPDATE...RETURNING
            ("slate-1", "aprovado", None),  # buscar_slate_atual (dentro de gerar_mensagens)
            None,  # existe_pick_quarentena_no_slate (dentro de gerar_mensagens)
        ],
        fetchall_results=[
            [],  # itens vazios -> conflitos_por_fixture nem chega a consultar
            [],  # expirar_mensagens_vencidas
            [],  # carregar_itens_para_mensagem -> slate sem itens, gerar_mensagens para aqui
        ],
    )
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/aprovar", headers=_ORIGEM)

    assert resposta.status_code == 303
    assert any("status = 'aprovado'" in q[0] for q in cur.queries)


def test_post_aprovar_bloqueado_quando_ha_pick_quarentena_no_slate():
    # Defesa em profundidade (achado CRITICAL do code-reviewer, Fase 5c).
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(
        fetchone_results=[("slate-1", "rascunho", None), (1,)],  # existe_pick_quarentena_no_slate -> True
        fetchall_results=[[]],
    )
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/aprovar", headers=_ORIGEM)

    assert resposta.status_code == 409
    assert not any("status = 'aprovado'" in q[0] for q in cur.queries)


def test_post_gerar_correcao_recusa_slate_que_nao_esta_aprovado():
    cur = FakeCursor(fetchone_results=[("rascunho",)])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/gerar-correcao", headers=_ORIGEM)

    assert resposta.status_code == 409
    assert not any("insert into daily_slates" in q[0] for q in cur.queries)


def test_post_gerar_correcao_sucesso_quando_aprovado():
    cur = FakeCursor(fetchone_results=[("aprovado",), (date(2026, 8, 5),), ("slate-novo",)])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/gerar-correcao", headers=_ORIGEM)

    assert resposta.status_code == 303
    assert any("insert into daily_slates" in q[0] for q in cur.queries)


def test_post_reordenar_sucesso():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(fetchone_results=[("slate-1", "rascunho", None), (2,), ("sp-vizinho",)])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/reordenar/sp-2", data={"direcao": "subir"}, headers=_ORIGEM)

    assert resposta.status_code == 303
    assert any("update slate_picks set ordem" in q[0] for q in cur.queries)


def test_post_reordenar_direcao_invalida_400():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor()
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/reordenar/sp-1", data={"direcao": "esquerda"}, headers=_ORIGEM)

    assert resposta.status_code == 400
    assert cur.queries == []


def test_post_editar_odd_referencia_sucesso():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor(fetchone_results=[("slate-1", "rascunho", None)])
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/odd-referencia/sp-1", data={"nova_odd": "2.00"}, headers=_ORIGEM)

    assert resposta.status_code == 303
    assert any("odd_referencia_origem = 'manual'" in q[0] for q in cur.queries)


def test_post_editar_odd_referencia_zero_400():
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    cur = FakeCursor()
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/odd-referencia/sp-1", data={"nova_odd": "0"}, headers=_ORIGEM)

    assert resposta.status_code == 400
    assert cur.queries == []


def test_post_conflito_usar_selecao_sucesso():
    kickoff = datetime(2026, 8, 11, 21, 0, tzinfo=timezone.utc)
    item_row = (
        "sp-1", "p-1", "fix-1", 1, "automatico", "1x2", "Home", "A", "B", "Liga",
        kickoff, 1.9, "Bet365", 1.85, "oddspapi", 1.78, "X", "Fonte",
    )
    odd_row = (1.85, kickoff, 1.78, "oddspapi")
    cur = FakeCursor(
        # ultimo fetchone e o coalesce(max(ordem),0) calculado
        # server-side (achado HIGH do code-reviewer, Fase 5d-E) - nunca
        # mais vem do form.
        fetchone_results=[("slate-1", "rascunho", None), ("pick-9",), odd_row, (1,)],
        fetchall_results=[[item_row], []],
    )
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/conflito/usar/pick-9", headers=_ORIGEM)

    assert resposta.status_code == 303
    assert any("insert into slate_picks" in q[0] for q in cur.queries)


def test_post_conflito_usar_selecao_fora_de_escopo_409():
    # pick_id nao esta em conflito em nenhuma fixture deste slate
    # (achado HIGH do security-reviewer) - sem itens no slate, fixture_ids
    # fica vazio e o update com escopo nao acha nada.
    cur = FakeCursor(
        fetchone_results=[("slate-1", "rascunho", None), None],
        fetchall_results=[[]],
    )
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/conflito/usar/pick-fantasma", headers=_ORIGEM)

    assert resposta.status_code == 409


def test_post_conflito_descartar_todas_sucesso():
    kickoff = datetime(2026, 8, 11, 21, 0, tzinfo=timezone.utc)
    item_row = (
        "sp-1", "p-1", "fix-1", 1, "automatico", "1x2", "Home", "A", "B", "Liga",
        kickoff, 1.9, "Bet365", 1.85, "oddspapi", 1.78, "X", "Fonte",
    )
    cur = FakeCursor(
        fetchone_results=[("slate-1", "rascunho", None), (1,)],
        fetchall_results=[[item_row], [], [("p9",)]],
    )
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post("/curadoria/slate-1/conflito/descartar", data={"pick_ids": "p9,p10"}, headers=_ORIGEM)

    assert resposta.status_code == 303
    assert any("update picks set status = 'descartado'" in q[0] for q in cur.queries)


def test_post_palpite_manual_sucesso():
    cur = FakeCursor(
        fetchone_results=[
            ("slate-1", "rascunho", None),  # buscar_slate_atual (_exigir_pode_escrever)
            ("fix-1", "Goias", "Londrina"),  # fixture elegivel
            ("source-console-manual",),
            ("raw-pick-1",),
            ("pick-1",),
            (0,),
        ],
    )
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post(
        "/curadoria/slate-1/palpite-manual",
        data={"fixture_id": "fix-1", "mercado": "1x2", "selecao": "Home win", "odd_referencia": "1.90"},
        headers=_ORIGEM,
    )

    assert resposta.status_code == 303
    assert any("insert into picks" in q[0] for q in cur.queries)


def test_post_palpite_manual_mercado_invalido_400():
    cur = FakeCursor(fetchone_results=[("slate-1", "rascunho", None)])
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    app.dependency_overrides[get_conexao] = lambda: FakeConnection(cur)

    resposta = client.post(
        "/curadoria/slate-1/palpite-manual",
        data={"fixture_id": "fix-1", "mercado": "chute_de_bicicleta", "selecao": "Home win", "odd_referencia": "1.90"},
        headers=_ORIGEM,
    )

    assert resposta.status_code == 400
    assert not any("insert into raw_picks" in q[0] for q in cur.queries)


def test_curadoria_liberada_esconde_pick_de_fonte_em_quarentena():
    # carregar_itens_slate ja filtra na SQL (testado em
    # tests/test_console_queries_slate.py); aqui confirmamos que a
    # ausencia se reflete na pagina renderizada de ponta a ponta.
    app.dependency_overrides[estado_run_hoje] = lambda: _ESTADO_LIBERADO
    app.dependency_overrides[get_cursor] = lambda: FakeCursor(
        fetchone_results=[("slate-1", "rascunho", None)],
        fetchall_results=[[], [], [], []],  # fixturas_elegiveis, itens (filtrados=vazio), conflitos, excluidos
    )

    resposta = client.get("/curadoria")

    assert resposta.status_code == 200
    assert "TEXTO-DE-FONTE-EM-QUARENTENA" not in resposta.text
