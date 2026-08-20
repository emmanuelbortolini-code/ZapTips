from datetime import date
from decimal import Decimal

import psycopg.errors
import pytest

from app.subs import (
    AssinaturaVencendo,
    PeriodoInvalido,
    PicoAssinantes,
    ReferenciaPagamentoDuplicada,
    TetoExcedido,
    UsuarioInexistente,
    UsuarioOptOut,
    cabe_no_teto,
    listar_vencendo,
    pico_assinantes_no_periodo,
    registrar_assinatura,
    validar_periodo,
)
from app.users import UsuarioResumo
from tests._fakes import FakeCursor


class _CursorQueViolaUniqueNoInsert(FakeCursor):
    """FakeCursor que simula o driver real recusando um insert por
    violar uq_subscriptions_referencia_pagamento (migration 0017) -
    achado real da validacao contra o Postgres (o erro cru do driver
    vazava como traceback em vez de mensagem legivel; ver CLAUDE.md
    Fase 5b)."""

    def execute(self, sql, params=None):
        super().execute(sql, params)
        if "insert into subscriptions" in sql:
            raise psycopg.errors.UniqueViolation("duplicate key value violates unique constraint")


def test_validar_periodo_aceita_inicio_igual_fim():
    validar_periodo(date(2026, 8, 1), date(2026, 8, 1))  # nao levanta


def test_validar_periodo_recusa_fim_antes_do_inicio():
    with pytest.raises(PeriodoInvalido):
        validar_periodo(date(2026, 8, 10), date(2026, 8, 1))


def test_cabe_no_teto_no_limite_exato_e_true():
    assert cabe_no_teto(50, 50) is True


def test_cabe_no_teto_acima_do_limite_e_false():
    assert cabe_no_teto(51, 50) is False


def test_pico_assinantes_no_periodo_usa_count_distinct_e_union_all():
    cur = FakeCursor(fetchone_results=[(date(2026, 9, 1), 12)])

    pico = pico_assinantes_no_periodo(cur, inicio=date(2026, 9, 1), fim=date(2026, 9, 30), user_id_candidato="u1")

    assert pico == PicoAssinantes(dia=date(2026, 9, 1), quantidade=12)
    sql, params = cur.queries[0]
    assert "count(distinct" in sql
    assert "union all" in sql
    assert params == (date(2026, 9, 1), date(2026, 9, 30), "u1", date(2026, 9, 1), date(2026, 9, 30))


def test_registrar_assinatura_recusa_quando_teto_excedido_e_nao_insere():
    cur = FakeCursor(
        fetchone_results=[
            ("u1", "Fulano", "+5511999991111", "ativo", None),  # buscar_usuario_por_id
            (date(2026, 9, 3), 51),  # pico_assinantes_no_periodo
        ]
    )

    with pytest.raises(TetoExcedido) as exc_info:
        registrar_assinatura(
            cur, user_id="u1", inicio=date(2026, 9, 1), fim=date(2026, 9, 30), valor=Decimal("49.90"),
            meio_pagamento="pix", referencia_pagamento="E123", registrado_por="pm", teto=50,
        )

    assert exc_info.value.dia == date(2026, 9, 3)
    assert exc_info.value.quantidade == 51
    assert exc_info.value.teto == 50
    assert not any("insert into subscriptions" in sql for sql, _ in cur.queries)


def test_registrar_assinatura_aceita_renovacao_exatamente_no_teto():
    # D2: a assinatura hipotetica ja conta como o proprio usuario, entao
    # uma renovacao nunca deveria empurrar o pico pra alem do teto.
    cur = FakeCursor(
        fetchone_results=[
            ("u1", "Fulano", "+5511999991111", "ativo", None),
            (date(2026, 9, 1), 50),
            ("sub-nova",),
        ]
    )

    sub_id = registrar_assinatura(
        cur, user_id="u1", inicio=date(2026, 9, 1), fim=date(2026, 9, 30), valor=Decimal("49.90"),
        meio_pagamento="pix", referencia_pagamento="E123", registrado_por="pm", teto=50,
    )

    assert sub_id == "sub-nova"
    assert any("insert into subscriptions" in sql for sql, _ in cur.queries)


def test_registrar_assinatura_recusa_usuario_inexistente():
    cur = FakeCursor(fetchone_results=[None])

    with pytest.raises(UsuarioInexistente):
        registrar_assinatura(
            cur, user_id="u-fantasma", inicio=date(2026, 9, 1), fim=date(2026, 9, 30), valor=Decimal("49.90"),
            meio_pagamento="pix", referencia_pagamento="E123", registrado_por="pm", teto=50,
        )


def test_registrar_assinatura_recusa_usuario_que_optou_por_sair():
    cur = FakeCursor(fetchone_results=[("u1", "Fulano", "+5511999991111", "ativo", "2026-08-01T00:00:00Z")])

    with pytest.raises(UsuarioOptOut):
        registrar_assinatura(
            cur, user_id="u1", inicio=date(2026, 9, 1), fim=date(2026, 9, 30), valor=Decimal("49.90"),
            meio_pagamento="pix", referencia_pagamento="E123", registrado_por="pm", teto=50,
        )


def test_registrar_assinatura_periodo_invalido_nao_consulta_banco():
    cur = FakeCursor()

    with pytest.raises(PeriodoInvalido):
        registrar_assinatura(
            cur, user_id="u1", inicio=date(2026, 9, 30), fim=date(2026, 9, 1), valor=Decimal("49.90"),
            meio_pagamento="pix", referencia_pagamento="E123", registrado_por="pm", teto=50,
        )

    assert cur.queries == []


def test_registrar_assinatura_grava_valor_como_decimal_nunca_float():
    cur = FakeCursor(
        fetchone_results=[
            ("u1", "Fulano", "+5511999991111", "ativo", None),
            (date(2026, 9, 1), 1),
            ("sub-nova",),
        ]
    )

    registrar_assinatura(
        cur, user_id="u1", inicio=date(2026, 9, 1), fim=date(2026, 9, 30), valor=Decimal("49.90"),
        meio_pagamento="pix", referencia_pagamento="E123", registrado_por="pm", teto=50,
    )

    insert_sql, insert_params = next((sql, p) for sql, p in cur.queries if "insert into subscriptions" in sql)
    valor_gravado = next(p for p in insert_params if isinstance(p, Decimal))
    assert valor_gravado == Decimal("49.90")
    assert not isinstance(valor_gravado, float)


def test_registrar_assinatura_referencia_duplicada_vira_erro_legivel():
    cur = _CursorQueViolaUniqueNoInsert(
        fetchone_results=[
            ("u1", "Fulano", "+5511999991111", "ativo", None),
            (date(2026, 9, 1), 1),
        ]
    )

    with pytest.raises(ReferenciaPagamentoDuplicada) as exc_info:
        registrar_assinatura(
            cur, user_id="u1", inicio=date(2026, 9, 1), fim=date(2026, 9, 30), valor=Decimal("49.90"),
            meio_pagamento="pix", referencia_pagamento="E123", registrado_por="pm", teto=50,
        )

    assert "E123" in str(exc_info.value)


def test_listar_vencendo_filtra_opt_out_no_predicado():
    cur = FakeCursor(fetchall_results=[[]])

    listar_vencendo(cur, hoje=date(2026, 8, 11))

    sql = cur.queries[0][0]
    assert "opt_out_em is null" in sql


def test_listar_vencendo_mapeia_dias_restantes_e_ja_renovado():
    cur = FakeCursor(
        fetchall_results=[
            [("u1", "Fulano", "+5511999991111", date(2026, 8, 16), Decimal("49.90"), False)]
        ]
    )

    resultado = listar_vencendo(cur, hoje=date(2026, 8, 11), dias=10)

    assert resultado == [
        AssinaturaVencendo(
            user_id="u1", nome="Fulano", telefone_e164="+5511999991111",
            fim=date(2026, 8, 16), dias_restantes=5, valor=Decimal("49.90"), ja_renovado=False,
        )
    ]


def test_listar_vencendo_ja_renovado_true_ainda_aparece_na_lista():
    cur = FakeCursor(
        fetchall_results=[
            [("u1", "Fulano", "+5511999991111", date(2026, 8, 16), Decimal("49.90"), True)]
        ]
    )

    resultado = listar_vencendo(cur, hoje=date(2026, 8, 11))

    assert len(resultado) == 1
    assert resultado[0].ja_renovado is True
