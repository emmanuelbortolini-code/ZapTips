from datetime import date, datetime, timedelta, timezone

from app.console.queries import EstadoRun, MensagemNaFila, SessaoEnvio
from app.console.rules import (
    AcessoEnvio,
    AcessoSessao,
    ParadaSessao,
    avaliar_acesso_sessao,
    montar_paradas,
    montar_resumo,
    parada_atual,
    progresso,
)

_KICKOFF = datetime(2026, 8, 11, 22, 0, tzinfo=timezone.utc)
_GERADA = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
_DATA = date(2026, 8, 11)  # toordinal() % 3 = 2 para os testes de 3 usuarios abaixo


def _msg(user_id, message_id="m", nome="Fulano", telefone="+5511999990000") -> MensagemNaFila:
    return MensagemNaFila(
        message_id=message_id, user_id=user_id, nome=nome, telefone_e164=telefone, tipo="palpite",
        fixture_id="fix-1", time_casa="Avai", time_fora="CRB", kickoff_utc=_KICKOFF,
        corpo_renderizado="corpo", gerada_em=_GERADA,
    )


def test_montar_paradas_universo_vazio_devolve_vazio():
    assert montar_paradas([], [], _DATA) == ()


def test_montar_paradas_um_assinante():
    fila = [_msg("u1")]
    paradas = montar_paradas(["u1"], fila, _DATA)

    assert len(paradas) == 1
    assert paradas[0].user_id == "u1"
    assert paradas[0].posicao == 1
    assert paradas[0].mensagens == (fila[0],)


def test_montar_paradas_agrupa_mensagens_do_mesmo_usuario():
    fila = [_msg("u1", message_id="m1"), _msg("u1", message_id="m2")]
    paradas = montar_paradas(["u1"], fila, _DATA)

    assert len(paradas) == 1
    assert [m.message_id for m in paradas[0].mensagens] == ["m1", "m2"]


def test_montar_paradas_usa_ordem_estavel_do_universo():
    universo = ["u1", "u2", "u3"]
    fila = [_msg("u1"), _msg("u2"), _msg("u3")]

    paradas = montar_paradas(universo, fila, _DATA)

    # ordem_da_sessao(["u1","u2","u3"], 2026-08-11): offset = toordinal() % 3
    posicoes = {p.user_id: p.posicao for p in paradas}
    assert sorted(posicoes.values()) == [1, 2, 3]
    # a mesma chamada, em outra ordem de entrada da fila, da a mesma posicao por user
    paradas_2 = montar_paradas(universo, list(reversed(fila)), _DATA)
    assert {p.user_id: p.posicao for p in paradas_2} == posicoes


def test_montar_paradas_usuario_fora_do_universo_entra_no_fim_sem_erro():
    fila = [_msg("u1"), _msg("fantasma")]
    paradas = montar_paradas(["u1"], fila, _DATA)

    assert len(paradas) == 2
    posicoes = {p.user_id: p.posicao for p in paradas}
    assert posicoes["u1"] == 1
    assert posicoes["fantasma"] == 2


def test_montar_paradas_marcar_uma_como_resolvida_nao_muda_posicao_das_outras():
    # Regressao do achado central do plano: universo tem que ser ESTAVEL
    # (todos que tiveram mensagem gerada hoje), nunca recalculado sobre a
    # fila restante - senao "n" muda a cada mensagem resolvida e o
    # offset de ordem_da_sessao reembaralha quem e a proxima parada.
    universo = ["u1", "u2", "u3"]
    fila_antes = [_msg("u1"), _msg("u2"), _msg("u3")]
    paradas_antes = montar_paradas(universo, fila_antes, _DATA)
    posicoes_antes = {p.user_id: p.posicao for p in paradas_antes}

    # u1 (primeira parada) foi resolvida - sai da fila, mas o universo
    # (quem teve mensagem gerada hoje) continua o mesmo.
    primeira = parada_atual(paradas_antes)
    fila_depois = [m for m in fila_antes if m.user_id != primeira.user_id]
    paradas_depois = montar_paradas(universo, fila_depois, _DATA)
    posicoes_depois = {p.user_id: p.posicao for p in paradas_depois}

    for user_id, posicao in posicoes_depois.items():
        assert posicao == posicoes_antes[user_id]


def test_parada_atual_devolve_primeira_da_lista():
    p1 = ParadaSessao(user_id="u1", nome="A", telefone_e164="+551", posicao=1)
    p2 = ParadaSessao(user_id="u2", nome="B", telefone_e164="+552", posicao=2)
    assert parada_atual((p1, p2)) is p1


def test_parada_atual_devolve_none_quando_vazio():
    assert parada_atual(()) is None


def test_progresso_calcula_concluidas_e_duracao_estimada():
    paradas = (
        ParadaSessao(user_id="u2", nome=None, telefone_e164="+552", posicao=2, mensagens=(_msg("u2"),)),
    )
    resultado = progresso(paradas, universo_user_ids=["u1", "u2", "u3"], intervalo_segundos=30)

    assert resultado.total == 3
    assert resultado.restantes == 1
    assert resultado.concluidas == 2
    assert resultado.mensagens_pendentes == 1
    assert resultado.duracao_estimada == timedelta(seconds=30)


def test_progresso_universo_vazio():
    resultado = progresso((), universo_user_ids=[], intervalo_segundos=30)
    assert resultado == progresso((), [], 30)
    assert resultado.total == 0
    assert resultado.concluidas == 0


def _acesso_liberado():
    return AcessoEnvio(liberado=True, motivo_bloqueio=None)


def _sessao(status="ativa"):
    return SessaoEnvio(
        id="sessao-1", data=_DATA, slate_id="slate-1", status=status,
        iniciada_em=_GERADA, pausada_em=None, retomada_em=None, encerrada_em=None,
    )


def test_avaliar_acesso_sessao_bloqueado_quando_envio_bloqueado():
    acesso_envio = AcessoEnvio(liberado=False, motivo_bloqueio="Slate de hoje ainda nao foi aprovado.")
    resultado = avaliar_acesso_sessao(acesso_envio, sessao_aberta=None, paradas=())

    assert resultado == AcessoSessao(pode_iniciar=False, motivo="Slate de hoje ainda nao foi aprovado.")


def test_avaliar_acesso_sessao_bloqueado_quando_ja_existe_sessao_aberta():
    resultado = avaliar_acesso_sessao(_acesso_liberado(), sessao_aberta=_sessao(), paradas=(ParadaSessao("u1", None, "+1", 1),))

    assert resultado.pode_iniciar is False
    assert "aberta" in resultado.motivo


def test_avaliar_acesso_sessao_bloqueado_quando_sem_paradas():
    resultado = avaliar_acesso_sessao(_acesso_liberado(), sessao_aberta=None, paradas=())

    assert resultado.pode_iniciar is False
    assert "pronta" in resultado.motivo


def test_avaliar_acesso_sessao_liberado():
    resultado = avaliar_acesso_sessao(_acesso_liberado(), sessao_aberta=None, paradas=(ParadaSessao("u1", None, "+1", 1),))

    assert resultado == AcessoSessao(pode_iniciar=True, motivo=None)


def test_montar_resumo_agrega_contadores_e_pulos():
    puladas = [("Fulano", "+5511999990000", "nao atende")]
    resumo = montar_resumo(enviadas=3, expiradas=1, prontas_restantes=2, puladas=puladas)

    assert resumo.enviadas == 3
    assert resumo.expiradas == 1
    assert resumo.prontas_restantes == 2
    assert resumo.puladas == tuple(puladas)
