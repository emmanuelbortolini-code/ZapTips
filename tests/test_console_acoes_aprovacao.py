from datetime import date, datetime, timezone

import pytest

from app.console.acoes import (
    aprovar_slate,
    gerar_correcao,
    resolver_conflito_descartar_todas,
    resolver_conflito_usar_selecao,
)
from tests._fakes import FakeCursor


def test_aprovar_slate_update_condicional_por_status_rascunho():
    cur = FakeCursor(fetchone_results=[("slate-1",)])

    resultado = aprovar_slate(cur, "slate-1", curado_por="pm")

    assert resultado is True
    sql, params = cur.queries[0]
    assert "status = 'aprovado'" in sql
    assert "where id = %s::uuid and status = 'rascunho'" in sql
    assert params == ("pm", "slate-1")


def test_aprovar_slate_ja_aprovado_retorna_false_sem_reaprovar():
    cur = FakeCursor(fetchone_results=[None])

    assert aprovar_slate(cur, "slate-1", curado_por="pm") is False


def test_gerar_correcao_usa_a_data_do_proprio_slate_substituido():
    # Achado do security-reviewer (Fase 5c): a correcao tem que usar a
    # data do slate original, nunca "hoje" - senao um slate aprovado
    # antigo poderia ser corrigido e o resultado sombrear o rascunho
    # real do dia atual.
    cur = FakeCursor(fetchone_results=[(date(2026, 8, 5),), ("slate-novo",)])

    novo_id = gerar_correcao(cur, "slate-aprovado")

    assert novo_id == "slate-novo"
    sql_busca, params_busca = cur.queries[0]
    assert "select data from daily_slates" in sql_busca
    assert params_busca == ("slate-aprovado",)
    sql_insert, params_insert = cur.queries[1]
    assert "substitui_slate_id" in sql_insert
    assert params_insert == (date(2026, 8, 5), "slate-aprovado")
    sql_copia, params_copia = cur.queries[2]
    assert "insert into slate_picks" in sql_copia
    assert params_copia == ("slate-novo", "slate-aprovado")


def test_gerar_correcao_slate_inexistente_levanta_erro():
    cur = FakeCursor(fetchone_results=[None])

    with pytest.raises(ValueError):
        gerar_correcao(cur, "slate-fantasma")


def test_resolver_conflito_usar_selecao_exige_revisao_manual_e_fixture_do_slate():
    # ordem e calculada aqui via coalesce(max(ordem),0)+1 (achado HIGH do
    # code-reviewer, Fase 5d-E: o valor nunca deve vir do form/template -
    # "loop.length+1" no template so via a lista de candidatos em
    # conflito, nao o slate inteiro, e colidia com ordem ja existente).
    kickoff_odd_row = (1.85, datetime(2026, 8, 11, tzinfo=timezone.utc), 1.78, "oddspapi")
    cur = FakeCursor(fetchone_results=[("pick-9",), kickoff_odd_row, (4,)])

    resultado = resolver_conflito_usar_selecao(cur, "slate-1", "pick-9", fixture_ids=["fix-1"])

    assert resultado is True
    assert "curadoria_iniciada_em" in cur.queries[0][0]
    sql_update, params_update = cur.queries[1]
    assert "status = 'revisao_manual'" in sql_update
    assert "fixture_id = any(" in sql_update
    assert params_update == ("pick-9", ["fix-1"])
    sql_ordem = cur.queries[3][0]
    assert "coalesce(max(ordem), 0)" in sql_ordem
    sql_insert, params_insert = cur.queries[4]
    assert "insert into slate_picks" in sql_insert
    assert params_insert[0] == "slate-1"
    assert params_insert[1] == "pick-9"
    assert params_insert[2] == 5  # max existente (4) + 1


def test_resolver_conflito_usar_selecao_pick_fora_de_escopo_nao_muda_nada():
    # pick_id nao esta em revisao_manual, ou nao pertence a nenhuma
    # fixture deste slate - update com returning nao acha nada, funcao
    # para ali, sem tocar em slate_picks.
    cur = FakeCursor(fetchone_results=[None])

    resultado = resolver_conflito_usar_selecao(cur, "slate-1", "pick-de-outro-dia", fixture_ids=["fix-1"])

    assert resultado is False
    assert len(cur.queries) == 2  # marca curadoria + update sem match, nada mais
    assert not any("insert into slate_picks" in q[0] for q in cur.queries)


def test_resolver_conflito_descartar_todas_so_afeta_picks_em_conflito_no_slate():
    # pick_ids pode conter algo fora de escopo (achado do
    # security-reviewer) - so os que batem status='revisao_manual' e
    # fixture do slate sao de fato descartados.
    cur = FakeCursor(fetchall_results=[[("p1",)]], fetchone_results=[(1,)])

    resolver_conflito_descartar_todas(cur, "slate-1", ["p1", "p2-fora-de-escopo"], fixture_ids=["fix-1"], motivo="x")

    sql_filtro, params_filtro = cur.queries[1]
    assert "status = 'revisao_manual'" in sql_filtro
    assert params_filtro == (["p1", "p2-fora-de-escopo"], ["fix-1"])
    updates = [q for q in cur.queries if "update picks set status = 'descartado'" in q[0]]
    assert len(updates) == 1
    assert updates[0][1] == ("p1",)
