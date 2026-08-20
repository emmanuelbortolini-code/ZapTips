from datetime import datetime, timezone

from app.console.queries import ContadoresEnvio, MensagemNaFila, contadores_do_dia, fila_envio
from tests._fakes import FakeCursor

_KICKOFF = datetime(2026, 8, 11, 22, 30, tzinfo=timezone.utc)


def test_fila_envio_filtra_opt_out_no_sql():
    # Mesmo predicado do teto de assinantes (Fase 5b) - registrar_opt_out
    # ja marca as mensagens 'pronta' do usuario como 'pulada' (Fase 5b),
    # mas essa query NAO deve depender so disso: o mesmo raciocinio do
    # CRITICAL de quarentena da Fase 5c (garantido no dado, nao so na
    # exibicao) vale aqui.
    cur = FakeCursor(fetchall_results=[[]])

    fila_envio(cur)

    sql = cur.queries[0][0]
    assert "status = 'pronta'" in sql
    assert "opt_out_em is null" in sql
    assert "status = 'ativo'" in sql


def test_fila_envio_mapeia_colunas_ordenadas_por_kickoff():
    cur = FakeCursor(
        fetchall_results=[
            [
                (
                    "msg-1", "u1", "Emmanuel", "+5511999991111", "palpite", "fix-1", "Avai", "CRB",
                    _KICKOFF, "corpo da mensagem", datetime(2026, 8, 11, 16, 0, tzinfo=timezone.utc),
                )
            ]
        ]
    )

    fila = fila_envio(cur)

    assert fila == [
        MensagemNaFila(
            message_id="msg-1", user_id="u1", nome="Emmanuel", telefone_e164="+5511999991111", tipo="palpite",
            fixture_id="fix-1", time_casa="Avai", time_fora="CRB", kickoff_utc=_KICKOFF,
            corpo_renderizado="corpo da mensagem", gerada_em=datetime(2026, 8, 11, 16, 0, tzinfo=timezone.utc),
        )
    ]


def test_fila_envio_inclui_mensagem_de_resumo_semanal_sem_fixture():
    # Fase 6e: tipo='resumo_semanal' tem fixture_id NULL por design - a
    # query precisa de LEFT JOIN pra nao excluir essa linha da fila
    # inteira (mesma classe do bug ja corrigido pra universo_da_sessao/
    # resumo_do_dia no checklist manual de sessao).
    gerada = datetime(2026, 8, 17, 8, 0, tzinfo=timezone.utc)
    cur = FakeCursor(
        fetchall_results=[
            [("msg-2", "u1", "Emmanuel", "+5511999991111", "resumo_semanal", None, None, None, None, "corpo semanal", gerada)]
        ]
    )

    fila = fila_envio(cur)

    assert fila == [
        MensagemNaFila(
            message_id="msg-2", user_id="u1", nome="Emmanuel", telefone_e164="+5511999991111",
            tipo="resumo_semanal", fixture_id=None, time_casa=None, time_fora=None, kickoff_utc=None,
            corpo_renderizado="corpo semanal", gerada_em=gerada,
        )
    ]


def test_contadores_do_dia_mapeia_prontas_enviadas_e_expirando():
    cur = FakeCursor(fetchone_results=[(3, 2, 1)])

    contadores = contadores_do_dia(cur, datetime(2026, 8, 11, 16, 0, tzinfo=timezone.utc))

    assert contadores == ContadoresEnvio(prontas=3, enviadas_hoje=2, expirando_2h=1)


def test_contadores_do_dia_usa_left_join_fixtures():
    # Fase 6e: INNER JOIN excluiria mensagem de resumo_semanal
    # (fixture_id NULL) de TODOS os contadores, nao so' de expirando_2h.
    cur = FakeCursor(fetchone_results=[(3, 2, 1)])

    contadores_do_dia(cur, datetime(2026, 8, 11, 16, 0, tzinfo=timezone.utc))

    sql = cur.queries[0][0]
    assert "left join fixtures" in sql
