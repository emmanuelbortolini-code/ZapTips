from datetime import date
from decimal import Decimal

from app.fechamento_generator import (
    ApostaParaFechamento,
    GrupoFechamento,
    buscar_grupos_pendentes,
    gerar_fechamentos,
    montar_idempotency_key_fechamento,
)
from app.messages_generator import montar_idempotency_key
from tests._fakes import FakeCursor


def test_montar_idempotency_key_fechamento_e_deterministico():
    a = montar_idempotency_key_fechamento("u1", "f1", date(2026, 8, 12))
    b = montar_idempotency_key_fechamento("u1", "f1", date(2026, 8, 12))
    assert a == b


def test_montar_idempotency_key_fechamento_nunca_colide_com_a_chave_de_palpite():
    fechamento = montar_idempotency_key_fechamento("u1", "f1", date(2026, 8, 12))
    palpite = montar_idempotency_key("u1", "f1", date(2026, 8, 12))
    assert fechamento != palpite


def test_buscar_grupos_pendentes_agrupa_por_usuario_e_fixture():
    cur = FakeCursor(
        fetchall_results=[
            [
                ("u1", "f1", "Casa1", "Fora1", 2, 1, "p1", "Menos de 2.5", Decimal("1.77"), "green", Decimal("1000"), Decimal("1013.54")),
                ("u1", "f1", "Casa1", "Fora1", 2, 1, "p2", "Ambas Nao", Decimal("1.50"), "red", Decimal("1013.54"), Decimal("993.54")),
                ("u2", "f2", "CasaX", "ForaX", 0, 0, "p3", "Menos de 1.5", Decimal("1.60"), "void", Decimal("500"), Decimal("500")),
            ]
        ]
    )

    grupos = buscar_grupos_pendentes(cur)

    assert grupos == [
        GrupoFechamento(
            user_id="u1", fixture_id="f1", time_casa="Casa1", time_fora="Fora1",
            placar_casa=2, placar_fora=1,
            apostas=(
                ApostaParaFechamento(pick_id="p1", selecao="Menos de 2.5", odd=Decimal("1.77"), resultado="green", banca_antes=Decimal("1000"), banca_depois=Decimal("1013.54")),
                ApostaParaFechamento(pick_id="p2", selecao="Ambas Nao", odd=Decimal("1.50"), resultado="red", banca_antes=Decimal("1013.54"), banca_depois=Decimal("993.54")),
            ),
        ),
        GrupoFechamento(
            user_id="u2", fixture_id="f2", time_casa="CasaX", time_fora="ForaX",
            placar_casa=0, placar_fora=0,
            apostas=(ApostaParaFechamento(pick_id="p3", selecao="Menos de 1.5", odd=Decimal("1.60"), resultado="void", banca_antes=Decimal("500"), banca_depois=Decimal("500")),),
        ),
    ]
    sql = cur.queries[0][0]
    assert "tipo = 'fechamento'" in sql


def test_buscar_grupos_pendentes_lista_vazia():
    cur = FakeCursor(fetchall_results=[[]])
    assert buscar_grupos_pendentes(cur) == []


def test_gerar_fechamentos_grava_mensagem_com_tipo_fechamento():
    cur = FakeCursor(
        fetchall_results=[
            [("u1", "f1", "Casa1", "Fora1", 2, 1, "p1", "Menos de 2.5", Decimal("1.77"), "green", Decimal("1000"), Decimal("1013.54"))]
        ],
        fetchone_results=[("msg-1",)],
    )

    total = gerar_fechamentos(cur, date(2026, 8, 12), rodape_legal="18+. Aposte com responsabilidade.")

    assert total == 1
    insert_sql, params = cur.queries[1]
    assert "insert into messages" in insert_sql
    assert "'fechamento'" in insert_sql
    assert "on conflict (idempotency_key) do nothing" in insert_sql
    user_id, fixture_id, pick_ids, corpo, idempotency_key = params
    assert user_id == "u1" and fixture_id == "f1" and pick_ids == ["p1"]
    assert "Banca simulada" in corpo


def test_gerar_fechamentos_idempotente_nao_conta_conflito():
    cur = FakeCursor(
        fetchall_results=[
            [("u1", "f1", "Casa1", "Fora1", 2, 1, "p1", "Menos de 2.5", Decimal("1.77"), "green", Decimal("1000"), Decimal("1013.54"))]
        ],
        fetchone_results=[None],  # on conflict do nothing -> sem row retornada
    )

    total = gerar_fechamentos(cur, date(2026, 8, 12), rodape_legal="18+. Aposte com responsabilidade.")

    assert total == 0


def test_gerar_fechamentos_sem_grupos_pendentes():
    cur = FakeCursor(fetchall_results=[[]])
    assert gerar_fechamentos(cur, date(2026, 8, 12), rodape_legal="18+.") == 0


def test_gerar_fechamentos_variacao_imune_a_aposta_de_outra_fixture_intercalada():
    # Achado HIGH do code-reviewer: bets.sequencia e' GLOBAL por usuario
    # (ordenada por kickoff+pick_id de TODAS as fixtures do usuario, nao
    # so desta) - se outra fixture G (ja fechada/mensageada, fora deste
    # lote pendente) tiver uma aposta intercalada entre as duas apostas
    # de F1 na sequencia global, banca_depois de F1-p1 (1020) NAO e'
    # igual a banca_antes de F1-p2 (1010) - a diferenca de 10 e' o
    # resultado de G, que nunca deveria aparecer na mensagem de F1.
    cur = FakeCursor(
        fetchall_results=[
            [
                ("u1", "f1", "Casa1", "Fora1", 2, 1, "p1", "Menos de 2.5", Decimal("2.0"), "green", Decimal("1000"), Decimal("1020")),
                ("u1", "f1", "Casa1", "Fora1", 2, 1, "p2", "Ambas Nao", Decimal("2.0"), "green", Decimal("1010"), Decimal("1030")),
            ]
        ],
        fetchone_results=[("msg-1",)],
    )

    gerar_fechamentos(cur, date(2026, 8, 12), rodape_legal="18+.")

    _, params = cur.queries[1]
    corpo = params[3]
    # Delta real de F1: (1020-1000) + (1030-1010) = 40, nunca 30
    # (1030-1000, que incluiria o -10 da fixture G intercalada).
    assert "+R$ 40.00" in corpo
    assert "+R$ 30.00" not in corpo
