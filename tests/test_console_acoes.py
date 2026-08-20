from decimal import Decimal

import pytest

from app.console.acoes import PisoAbaixoDoAbsoluto, editar_odd_referencia, editar_piso, remover_item, reordenar_item
from tests._fakes import FakeCursor


def test_remover_item_carimba_curadoria_e_deleta():
    cur = FakeCursor()

    remover_item(cur, "slate-1", "sp-1")

    assert len(cur.queries) == 2
    sql1 = cur.queries[0][0]
    assert "curadoria_iniciada_em = coalesce(curadoria_iniciada_em, now())" in sql1
    sql2, params2 = cur.queries[1]
    assert "delete from slate_picks" in sql2
    assert params2 == ("sp-1", "slate-1")


def test_reordenar_item_subir_troca_ordem_com_vizinho_anterior():
    cur = FakeCursor(fetchone_results=[(2,), ("sp-vizinho",)])

    reordenar_item(cur, "slate-1", "sp-2", "subir")

    # marca curadoria, busca ordem atual, busca vizinho, 2 updates
    assert len(cur.queries) == 5
    update1_sql, update1_params = cur.queries[3]
    update2_sql, update2_params = cur.queries[4]
    assert update1_params == (1, "sp-2")
    assert update2_params == (2, "sp-vizinho")


def test_reordenar_item_descer_troca_ordem_com_proximo():
    cur = FakeCursor(fetchone_results=[(1,), ("sp-vizinho",)])

    reordenar_item(cur, "slate-1", "sp-1", "descer")

    update1_sql, update1_params = cur.queries[3]
    update2_sql, update2_params = cur.queries[4]
    assert update1_params == (2, "sp-1")
    assert update2_params == (1, "sp-vizinho")


def test_reordenar_item_na_ponta_nao_faz_update():
    cur = FakeCursor(fetchone_results=[(1,), None])  # ordem 1, subir -> ordem 0 nao existe

    reordenar_item(cur, "slate-1", "sp-1", "subir")

    assert len(cur.queries) == 3  # marca + busca ordem + busca vizinho, sem updates
    assert not any("update slate_picks set ordem" in q[0] for q in cur.queries)


def test_reordenar_item_slate_pick_inexistente_nao_quebra():
    cur = FakeCursor(fetchone_results=[None])

    reordenar_item(cur, "slate-1", "sp-fantasma", "subir")

    assert len(cur.queries) == 2  # marca + busca (sem achar), sem mais nada


def test_editar_piso_grava_origem_manual():
    cur = FakeCursor()

    editar_piso(cur, "slate-1", "sp-1", Decimal("1.55"), odd_minima_absoluta=1.40)

    sql, params = cur.queries[1]
    assert "odd_minima_origem = 'manual'" in sql
    assert params == (Decimal("1.55"), "sp-1", "slate-1")


def test_editar_piso_abaixo_do_absoluto_recusa_e_nao_escreve():
    cur = FakeCursor()

    with pytest.raises(PisoAbaixoDoAbsoluto):
        editar_piso(cur, "slate-1", "sp-1", Decimal("1.00"), odd_minima_absoluta=1.40)

    assert cur.queries == []


def test_editar_piso_igual_ao_absoluto_e_aceito():
    cur = FakeCursor()

    editar_piso(cur, "slate-1", "sp-1", Decimal("1.40"), odd_minima_absoluta=1.40)  # nao levanta

    assert len(cur.queries) == 2


def test_editar_odd_referencia_recalcula_piso_com_calcular_odd_minima():
    cur = FakeCursor()

    editar_odd_referencia(cur, "slate-1", "sp-1", Decimal("2.00"), margem_pct=0.04, odd_minima_absoluta=1.40)

    sql, params = cur.queries[1]
    assert "odd_referencia_origem = 'manual'" in sql
    assert "odd_minima_origem = 'calculada'" in sql
    assert params[0] == Decimal("2.00")
    # piso = max(2.00*0.96, 1.40) = 1.92, arredondado pra baixo em 2 casas
    assert params[1] == 1.92
