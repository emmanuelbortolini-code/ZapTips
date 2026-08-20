from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from app.users import (
    EXPORT_TABELAS,
    TelefoneInvalido,
    TelefoneJaCadastrado,
    UsuarioResumo,
    buscar_usuario_por_id,
    buscar_usuario_por_telefone,
    criar_usuario,
    exportar_dados_usuario,
    mascarar_telefone,
    normalizar_telefone_e164,
    registrar_opt_in_novamente,
    registrar_opt_out,
)
from tests._fakes import FakeCursor


def test_normalizar_telefone_e164_remove_espacos_parenteses_e_hifen():
    assert normalizar_telefone_e164("+55 (11) 99999-1111") == "+5511999991111"


def test_normalizar_telefone_e164_ja_normalizado_fica_igual():
    assert normalizar_telefone_e164("+5511999991111") == "+5511999991111"


def test_normalizar_telefone_e164_sem_mais_e_invalido():
    with pytest.raises(TelefoneInvalido):
        normalizar_telefone_e164("5511999991111")


def test_normalizar_telefone_e164_com_letras_e_invalido():
    with pytest.raises(TelefoneInvalido):
        normalizar_telefone_e164("+55119999abcd")


def test_normalizar_telefone_e164_curto_demais_e_invalido():
    with pytest.raises(TelefoneInvalido):
        normalizar_telefone_e164("+5511")


def test_normalizar_telefone_e164_longo_demais_e_invalido():
    with pytest.raises(TelefoneInvalido):
        normalizar_telefone_e164("+" + "1" * 16)


def test_normalizar_telefone_e164_codigo_pais_com_zero_e_invalido():
    with pytest.raises(TelefoneInvalido):
        normalizar_telefone_e164("+0511999991111")


def test_mascarar_telefone_preserva_ddi_ddd_e_ultimos_4():
    assert mascarar_telefone("+5511999991111") == "+5511*****1111"


def test_mascarar_telefone_numero_minimo_mascara_tudo_menos_o_mais():
    # E.164 minimo valido (8 digitos apos o +) e curto demais pra separar
    # DDI/DDD dos ultimos 4 sem revelar o numero inteiro - mascara tudo.
    assert mascarar_telefone("+12345678") == "+********"


def test_criar_usuario_grava_todos_os_campos_de_opt_in():
    cur = FakeCursor(fetchone_results=[("user-1",)])

    user_id = criar_usuario(
        cur,
        nome="Fulano",
        telefone_e164="+55 11 99999-1111",
        fuso_horario="America/Sao_Paulo",
        idioma="pt-BR",
        opt_in_origem="whatsapp direto",
        opt_in_evidencia="print da conversa 2026-08-11",
    )

    assert user_id == "user-1"
    sql, params = cur.queries[0]
    assert "on conflict (telefone_e164) do nothing" in sql
    assert params[1] == "+5511999991111"  # telefone normalizado, nao o bruto
    assert "whatsapp direto" in params
    assert "print da conversa 2026-08-11" in params


def test_criar_usuario_ja_cadastrado_levanta_erro_com_telefone_mascarado():
    cur = FakeCursor(fetchone_results=[None])

    with pytest.raises(TelefoneJaCadastrado) as exc_info:
        criar_usuario(
            cur, nome=None, telefone_e164="+5511999991111", fuso_horario="America/Sao_Paulo",
            idioma="pt-BR", opt_in_origem="x", opt_in_evidencia="y",
        )

    assert "+5511*****1111" in str(exc_info.value)
    assert "999991111" not in str(exc_info.value)


def test_buscar_usuario_por_telefone_mapeia_colunas():
    cur = FakeCursor(fetchone_results=[("user-1", "Fulano", "+5511999991111", "ativo", None)])

    usuario = buscar_usuario_por_telefone(cur, "+5511999991111")

    assert usuario == UsuarioResumo(
        user_id="user-1", nome="Fulano", telefone_e164="+5511999991111", status="ativo", opt_out_em=None
    )


def test_buscar_usuario_por_telefone_none_quando_nao_existe():
    cur = FakeCursor(fetchone_results=[None])
    assert buscar_usuario_por_telefone(cur, "+5511999991111") is None


def test_buscar_usuario_por_id_mapeia_colunas():
    cur = FakeCursor(fetchone_results=[("user-1", "Fulano", "+5511999991111", "ativo", None)])

    usuario = buscar_usuario_por_id(cur, "user-1")

    assert usuario == UsuarioResumo(
        user_id="user-1", nome="Fulano", telefone_e164="+5511999991111", status="ativo", opt_out_em=None
    )


def test_buscar_usuario_por_id_none_quando_nao_existe():
    cur = FakeCursor(fetchone_results=[None])
    assert buscar_usuario_por_id(cur, "user-1") is None


def test_registrar_opt_out_atualiza_usuario_e_invalida_mensagens_prontas():
    cur = FakeCursor(fetchone_results=[("user-1",)], fetchall_results=[[("msg-1",), ("msg-2",)]])

    quantidade = registrar_opt_out(cur, "+5511999991111")

    assert quantidade == 2
    sql1, params1 = cur.queries[0]
    assert "opt_out_em is null" in sql1
    assert "coalesce" in sql1
    sql2, params2 = cur.queries[1]
    assert "status = 'pulada'" in sql2
    assert "motivo_pulo = 'opt_out'" in sql2
    assert "status = 'pronta'" in sql2
    assert params2 == ("user-1",)


def test_registrar_opt_out_idempotente_nao_reexecuta_update_de_mensagens():
    cur = FakeCursor(fetchone_results=[None])

    resultado = registrar_opt_out(cur, "+5511999991111")

    assert resultado is None
    assert len(cur.queries) == 1  # so o update de users, nada de messages


def test_registrar_opt_in_novamente_limpa_opt_out_e_grava_consentimento_novo():
    cur = FakeCursor(fetchone_results=[("user-1",)])

    user_id = registrar_opt_in_novamente(
        cur, "+5511999991111", opt_in_origem="voltou via whatsapp", opt_in_evidencia="print novo"
    )

    assert user_id == "user-1"
    sql, params = cur.queries[0]
    assert "opt_out_em = null" in sql
    assert "voltou via whatsapp" in params
    assert "print novo" in params


def test_registrar_opt_in_novamente_none_quando_telefone_nao_existe():
    cur = FakeCursor(fetchone_results=[None])
    assert registrar_opt_in_novamente(cur, "+5511999991111", opt_in_origem="x", opt_in_evidencia="y") is None


def test_export_tabelas_cobre_as_seis_tabelas_ligadas_a_usuario():
    nomes = {t.tabela for t in EXPORT_TABELAS}
    assert nomes == {"users", "subscriptions", "user_preferences", "messages", "user_bankroll_config", "bets"}


def test_exportar_dados_usuario_uma_query_por_tabela_na_ordem():
    cur = FakeCursor(fetchall_results=[[] for _ in EXPORT_TABELAS])

    resultado = exportar_dados_usuario(cur, "user-1")

    assert len(cur.queries) == len(EXPORT_TABELAS)
    for (sql, params), tabela_export in zip(cur.queries, EXPORT_TABELAS):
        assert f"from {tabela_export.tabela}" in sql
        assert params == ("user-1",)
    assert set(resultado["tabelas"].keys()) == {t.tabela for t in EXPORT_TABELAS}


def test_exportar_dados_usuario_tabela_vazia_e_lista_vazia_nao_ausente():
    cur = FakeCursor(fetchall_results=[[] for _ in EXPORT_TABELAS])
    resultado = exportar_dados_usuario(cur, "user-1")
    assert resultado["tabelas"]["messages"] == []


def test_exportar_dados_usuario_serializa_decimal_como_string_nunca_float():
    fetchall_results = [[] for _ in EXPORT_TABELAS]
    idx_subscriptions = [t.tabela for t in EXPORT_TABELAS].index("subscriptions")
    linha = tuple(Decimal("49.90") if col == "valor" else None for col in EXPORT_TABELAS[idx_subscriptions].colunas)
    fetchall_results[idx_subscriptions] = [linha]
    cur = FakeCursor(fetchall_results=fetchall_results)

    resultado = exportar_dados_usuario(cur, "user-1")

    valor_exportado = resultado["tabelas"]["subscriptions"][0]["valor"]
    assert valor_exportado == "49.90"
    assert isinstance(valor_exportado, str)


def test_exportar_dados_usuario_serializa_data_e_uuid():
    fetchall_results = [[] for _ in EXPORT_TABELAS]
    idx_users = [t.tabela for t in EXPORT_TABELAS].index("users")
    colunas = EXPORT_TABELAS[idx_users].colunas
    linha = tuple(
        UUID("11111111-1111-1111-1111-111111111111") if col == "id"
        else datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc) if col == "opt_in_em"
        else None
        for col in colunas
    )
    fetchall_results[idx_users] = [linha]
    cur = FakeCursor(fetchall_results=fetchall_results)

    resultado = exportar_dados_usuario(cur, "user-1")

    linha_exportada = resultado["tabelas"]["users"][0]
    assert linha_exportada["id"] == "11111111-1111-1111-1111-111111111111"
    assert linha_exportada["opt_in_em"] == "2026-08-11T12:00:00+00:00"
