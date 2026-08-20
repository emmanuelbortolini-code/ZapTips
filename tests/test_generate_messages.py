from datetime import date, datetime, timezone

from app.messages_generator import (
    ItemParaMensagem,
    PreferenciaUsuario,
    RelatorioGeracao,
    carregar_assinantes_elegiveis,
    carregar_itens_para_mensagem,
    carregar_preferencia,
    expirar_mensagens_vencidas,
    gerar_mensagens,
)
from tests._fakes import FakeCursor

_KICKOFF = datetime(2026, 8, 11, 21, 0, tzinfo=timezone.utc)


class _Settings:
    queue_enabled = True
    antecedencia_minima_horas = 2
    rodape_legal = "18+. Aposte com responsabilidade."


def test_expirar_mensagens_vencidas_so_toca_pronta_com_kickoff_passado():
    cur = FakeCursor(fetchall_results=[[("m1",), ("m2",)]])

    quantidade = expirar_mensagens_vencidas(cur, datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc))

    assert quantidade == 2
    sql = cur.queries[0][0]
    assert "status='expirada'" in sql or "status = 'expirada'" in sql
    assert "status = 'pronta'" in sql or "status='pronta'" in sql
    assert "kickoff_utc" in sql
    # Achado CRITICAL do code-reviewer (Fase 6e): uma mensagem de
    # fechamento (app.fechamento_generator) sempre aponta pra um jogo
    # que ja aconteceu, por definicao - sem restringir a expiracao a
    # tipo='palpite', ela seria marcada 'expirada' antes de qualquer
    # operador conseguir ve-la.
    assert "tipo = 'palpite'" in sql


def test_carregar_itens_para_mensagem_mapeia_colunas():
    cur = FakeCursor(
        fetchall_results=[
            [("p1", 1, "fix-1", "bra.2", "1x2", "Home win", 1.85, 1.77, "Goias", "Londrina", "Serie B", _KICKOFF, None)]
        ]
    )

    itens = carregar_itens_para_mensagem(cur, "slate-1")

    assert itens == [
        ItemParaMensagem(
            pick_id="p1", fixture_id="fix-1", slate_pick_ordem=1, liga="bra.2", mercado="1x2", selecao="Home win",
            odd_referencia=1.85, odd_minima=1.77, fonte_publica=False, fonte=None,
            time_casa="Goias", time_fora="Londrina", competicao="Serie B", kickoff_utc=_KICKOFF, transmissao=None,
        )
    ]


def test_carregar_assinantes_elegiveis_filtra_por_data_e_ativo():
    cur = FakeCursor(fetchall_results=[[("u1",), ("u2",)]])

    resultado = carregar_assinantes_elegiveis(cur, date(2026, 8, 11))

    assert resultado == ["u1", "u2"]
    sql = cur.queries[0][0]
    assert "opt_out_em is null" in sql
    assert "status = 'ativo'" in sql


def test_carregar_preferencia_none_quando_nao_ha_linha():
    cur = FakeCursor(fetchone_results=[None])
    assert carregar_preferencia(cur, "u1") is None


def test_carregar_preferencia_mapeia_colunas():
    cur = FakeCursor(fetchone_results=[(["bra.1"], ["handicap"], 1.5, 5.0, 3)])

    pref = carregar_preferencia(cur, "u1")

    assert pref == PreferenciaUsuario(
        ligas_excluidas=("bra.1",), mercados_excluidos=("handicap",), odd_min=1.5, odd_max=5.0, max_msgs_dia=3
    )


def test_gerar_mensagens_pula_quando_queue_desabilitada():
    class Settings(_Settings):
        queue_enabled = False

    cur = FakeCursor()

    relatorio = gerar_mensagens(cur, date(2026, 8, 11), datetime.now(timezone.utc), Settings())

    assert relatorio == RelatorioGeracao(status="pulado", motivo_pulo="queue_disabled")
    assert cur.queries == []


def test_gerar_mensagens_pula_quando_slate_nao_esta_aprovado():
    cur = FakeCursor(
        fetchall_results=[[]],  # expirar_mensagens_vencidas
        fetchone_results=[("slate-1", "rascunho", None)],  # buscar_slate_atual
    )

    relatorio = gerar_mensagens(cur, date(2026, 8, 11), datetime.now(timezone.utc), _Settings())

    assert relatorio.status == "pulado"
    assert relatorio.motivo_pulo == "slate_nao_aprovado"


def test_gerar_mensagens_pula_quando_ha_pick_quarentena_no_slate():
    cur = FakeCursor(
        fetchall_results=[[]],
        fetchone_results=[("slate-1", "aprovado", None), (1,)],  # slate atual, existe_pick_quarentena
    )

    relatorio = gerar_mensagens(cur, date(2026, 8, 11), datetime.now(timezone.utc), _Settings())

    assert relatorio.status == "pulado"
    assert relatorio.motivo_pulo == "quarentena_no_slate"


def test_gerar_mensagens_gera_para_assinante_ativo_com_assinatura_valida():
    agora = datetime(2026, 8, 11, 6, 0, tzinfo=timezone.utc)
    cur = FakeCursor(
        fetchall_results=[
            [],  # expirar_mensagens_vencidas
            [("p1", 1, "fix-1", "bra.2", "1x2", "Home win", 1.85, 1.77, "Goias", "Londrina", "Serie B", _KICKOFF, None)],  # itens
            [("u1",)],  # assinantes elegiveis
        ],
        fetchone_results=[
            ("slate-1", "aprovado", None),  # slate atual
            None,  # existe_pick_quarentena_no_slate
            None,  # preferencia do u1
            ("Emmanuel", "America/Sao_Paulo"),  # nome e fuso do u1
            ("msg-1",),  # insert into messages returning id
        ],
    )

    relatorio = gerar_mensagens(cur, date(2026, 8, 11), agora, _Settings())

    assert relatorio.gerados == 1
    assert any("insert into messages" in q[0] for q in cur.queries)


def test_gerar_mensagens_aprovado_sem_itens_devolve_ok_sem_gerar():
    cur = FakeCursor(
        fetchall_results=[[], []],  # expirar_mensagens_vencidas, carregar_itens_para_mensagem (vazio)
        fetchone_results=[("slate-1", "aprovado", None), None],
    )

    relatorio = gerar_mensagens(cur, date(2026, 8, 11), datetime.now(timezone.utc), _Settings())

    assert relatorio == RelatorioGeracao(status="ok")


def test_gerar_mensagens_segunda_execucao_conta_como_ja_existente():
    # on conflict (idempotency_key) do nothing -> fetchone() vem None na
    # segunda vez (nao houve returning porque nada foi inserido).
    agora = datetime(2026, 8, 11, 6, 0, tzinfo=timezone.utc)
    cur = FakeCursor(
        fetchall_results=[
            [],
            [("p1", 1, "fix-1", "bra.2", "1x2", "Home win", 1.85, 1.77, "Goias", "Londrina", "Serie B", _KICKOFF, None)],
            [("u1",)],
        ],
        fetchone_results=[
            ("slate-1", "aprovado", None),
            None,
            None,
            ("Emmanuel", "America/Sao_Paulo"),
            None,  # insert ... on conflict do nothing -> nada retornado
        ],
    )

    relatorio = gerar_mensagens(cur, date(2026, 8, 11), agora, _Settings())

    assert relatorio.gerados == 0
    assert relatorio.ja_existentes == 1


def test_gerar_mensagens_nao_gera_quando_fora_da_antecedencia_minima():
    agora = datetime(2026, 8, 11, 20, 30, tzinfo=timezone.utc)  # 30 min antes do kickoff, corte e 2h
    cur = FakeCursor(
        fetchall_results=[
            [],
            [("p1", 1, "fix-1", "bra.2", "1x2", "Home win", 1.85, 1.77, "Goias", "Londrina", "Serie B", _KICKOFF, None)],
            [("u1",)],
        ],
        fetchone_results=[
            ("slate-1", "aprovado", None),
            None,
            None,
            ("Emmanuel", "America/Sao_Paulo"),
        ],
    )

    relatorio = gerar_mensagens(cur, date(2026, 8, 11), agora, _Settings())

    assert relatorio.gerados == 0
    assert relatorio.pulados_antecedencia == 1
    assert not any("insert into messages" in q[0] for q in cur.queries)


def test_gerar_mensagens_conta_pulados_por_preferencia():
    # Achado MEDIUM do code-reviewer (Fase 5d-E): pulados_preferencia
    # existia na dataclass mas nunca era incrementado. u1 tem preferencia
    # excluindo o mercado do unico item do slate - o grupo inteiro
    # (fixture) some pra ele, e isso tem que aparecer no relatorio.
    agora = datetime(2026, 8, 11, 6, 0, tzinfo=timezone.utc)
    cur = FakeCursor(
        fetchall_results=[
            [],
            [("p1", 1, "fix-1", "bra.2", "1x2", "Home win", 1.85, 1.77, "Goias", "Londrina", "Serie B", _KICKOFF, None)],
            [("u1",)],
        ],
        fetchone_results=[
            ("slate-1", "aprovado", None),
            None,
            (None, ["1x2"], None, None, None),  # preferencia de u1: exclui mercado 1x2
            ("Emmanuel", "America/Sao_Paulo"),
        ],
    )

    relatorio = gerar_mensagens(cur, date(2026, 8, 11), agora, _Settings())

    assert relatorio.gerados == 0
    assert relatorio.pulados_preferencia == 1
    assert not any("insert into messages" in q[0] for q in cur.queries)
