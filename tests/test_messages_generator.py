from datetime import date, datetime, timedelta, timezone

from app.messages_generator import (
    GrupoFixture,
    ItemParaMensagem,
    PreferenciaUsuario,
    agrupar_por_fixture,
    aplicar_max_msgs_dia,
    respeita_antecedencia_minima,
    filtrar_por_preferencia,
    montar_idempotency_key,
    ordem_da_sessao,
)

_KICKOFF = datetime(2026, 8, 11, 21, 0, tzinfo=timezone.utc)


def _item(**overrides) -> ItemParaMensagem:
    base = dict(
        pick_id="p1", fixture_id="fix-1", slate_pick_ordem=1, liga="bra.2", mercado="1x2",
        selecao="Home win", odd_referencia=1.85, odd_minima=1.77, fonte_publica=False, fonte=None,
        time_casa="Goias", time_fora="Londrina", competicao="Serie B", kickoff_utc=_KICKOFF, transmissao="Premiere",
    )
    base.update(overrides)
    return ItemParaMensagem(**base)


def test_montar_idempotency_key_e_deterministico():
    a = montar_idempotency_key("u1", "fix-1", date(2026, 8, 11))
    b = montar_idempotency_key("u1", "fix-1", date(2026, 8, 11))
    assert a == b


def test_montar_idempotency_key_nao_colide_entre_tuplas_diferentes():
    # concatenacao sem separador colidiria em "u1"+"1fix" vs "u11"+"fix"
    a = montar_idempotency_key("u1", "1fix", date(2026, 8, 11))
    b = montar_idempotency_key("u11", "fix", date(2026, 8, 11))
    assert a != b


def test_filtrar_por_preferencia_none_devolve_tudo():
    itens = [_item(), _item(pick_id="p2")]
    assert filtrar_por_preferencia(itens, None) == itens


def test_filtrar_por_preferencia_liga_excluida():
    itens = [_item(liga="bra.2"), _item(pick_id="p2", liga="bra.1")]
    pref = PreferenciaUsuario(ligas_excluidas=("bra.2",))

    resultado = filtrar_por_preferencia(itens, pref)

    assert [i.pick_id for i in resultado] == ["p2"]


def test_filtrar_por_preferencia_mercado_excluido():
    itens = [_item(mercado="1x2"), _item(pick_id="p2", mercado="over_under")]
    pref = PreferenciaUsuario(mercados_excluidos=("over_under",))

    resultado = filtrar_por_preferencia(itens, pref)

    assert [i.pick_id for i in resultado] == ["p1"]


def test_filtrar_por_preferencia_odd_min_max():
    itens = [_item(odd_referencia=1.20), _item(pick_id="p2", odd_referencia=2.00), _item(pick_id="p3", odd_referencia=5.00)]
    pref = PreferenciaUsuario(odd_min=1.50, odd_max=3.00)

    resultado = filtrar_por_preferencia(itens, pref)

    assert [i.pick_id for i in resultado] == ["p2"]


def test_agrupar_por_fixture_junta_picks_da_mesma_partida():
    itens = [_item(pick_id="p1", fixture_id="fix-1"), _item(pick_id="p2", fixture_id="fix-1"), _item(pick_id="p3", fixture_id="fix-2")]

    grupos = agrupar_por_fixture(itens)

    assert len(grupos) == 2
    grupo_fix1 = next(g for g in grupos if g.fixture_id == "fix-1")
    assert {i.pick_id for i in grupo_fix1.itens} == {"p1", "p2"}


def test_grupo_fixture_prioridade_e_o_menor_ordem_do_grupo():
    grupo = GrupoFixture(
        fixture_id="fix-1", time_casa="A", time_fora="B", competicao=None, kickoff_utc=_KICKOFF, transmissao=None,
        itens=(_item(slate_pick_ordem=5), _item(pick_id="p2", slate_pick_ordem=2)),
    )
    assert grupo.prioridade == 2


def test_aplicar_max_msgs_dia_sem_limite_devolve_tudo():
    grupos = [
        GrupoFixture("fix-1", "A", "B", None, _KICKOFF, None, (_item(slate_pick_ordem=1),)),
        GrupoFixture("fix-2", "C", "D", None, _KICKOFF, None, (_item(pick_id="p2", slate_pick_ordem=2),)),
    ]
    assert aplicar_max_msgs_dia(grupos, None) == grupos


def test_aplicar_max_msgs_dia_corta_pelas_de_maior_ordem():
    grupo_prioritario = GrupoFixture("fix-1", "A", "B", None, _KICKOFF, None, (_item(slate_pick_ordem=1),))
    grupo_secundario = GrupoFixture("fix-2", "C", "D", None, _KICKOFF, None, (_item(pick_id="p2", slate_pick_ordem=5),))

    resultado = aplicar_max_msgs_dia([grupo_secundario, grupo_prioritario], limite=1)

    assert resultado == [grupo_prioritario]


def test_respeita_antecedencia_minima_true_quando_kickoff_esta_longe():
    agora = datetime(2026, 8, 11, 6, 0, tzinfo=timezone.utc)
    kickoff = agora + timedelta(hours=5)
    assert respeita_antecedencia_minima(kickoff, agora, horas=2) is True


def test_respeita_antecedencia_minima_false_quando_kickoff_esta_proximo():
    agora = datetime(2026, 8, 11, 6, 0, tzinfo=timezone.utc)
    kickoff = agora + timedelta(hours=1)
    assert respeita_antecedencia_minima(kickoff, agora, horas=2) is False


def test_respeita_antecedencia_minima_no_limite_exato_e_aceito():
    # >= : exatamente 2h de antecedencia satisfaz "no minimo 2 horas".
    agora = datetime(2026, 8, 11, 6, 0, tzinfo=timezone.utc)
    kickoff = agora + timedelta(hours=2)
    assert respeita_antecedencia_minima(kickoff, agora, horas=2) is True


def test_ordem_da_sessao_e_deterministica_no_mesmo_dia():
    a = ordem_da_sessao(["u3", "u1", "u2"], date(2026, 8, 11))
    b = ordem_da_sessao(["u1", "u2", "u3"], date(2026, 8, 11))
    assert a == b


def test_ordem_da_sessao_roda_entre_dias():
    dia1 = ordem_da_sessao(["u1", "u2", "u3"], date(2026, 8, 11))
    dia2 = ordem_da_sessao(["u1", "u2", "u3"], date(2026, 8, 12))
    assert dia1 != dia2


def test_ordem_da_sessao_e_justa_ao_longo_de_n_dias():
    # cada pessoa ocupa cada posicao exatamente uma vez em n dias
    usuarios = ["u1", "u2", "u3"]
    posicoes_do_u1 = set()
    for dia_offset in range(len(usuarios)):
        ordem = ordem_da_sessao(usuarios, date(2026, 8, 11 + dia_offset))
        posicoes_do_u1.add(ordem.index("u1"))
    assert posicoes_do_u1 == {0, 1, 2}


def test_ordem_da_sessao_lista_vazia():
    assert ordem_da_sessao([], date(2026, 8, 11)) == []
