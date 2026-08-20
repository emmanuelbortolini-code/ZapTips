from datetime import date, datetime, timezone

from app.console.queries import (
    FixturaElegivel,
    ItemSlate,
    buscar_slate_atual,
    buscar_status_slate,
    carregar_itens_slate,
    conflitos_por_fixture,
    excluidos_do_dia,
    existe_pick_quarentena_no_slate,
    fixturas_elegiveis_do_dia,
)
from tests._fakes import FakeCursor


def test_buscar_slate_atual_pega_o_mais_recente_nao_substituido():
    cur = FakeCursor(fetchone_results=[("slate-1", "rascunho", None)])

    resultado = buscar_slate_atual(cur, date(2026, 8, 11))

    assert resultado == ("slate-1", "rascunho", None)
    sql = cur.queries[0][0]
    assert "order by criado_em desc limit 1" in sql


def test_buscar_slate_atual_none_quando_nao_ha_slate():
    cur = FakeCursor(fetchone_results=[None])
    assert buscar_slate_atual(cur, date(2026, 8, 11)) is None


def test_carregar_itens_slate_filtra_fonte_em_quarentena():
    cur = FakeCursor(fetchall_results=[[]])

    carregar_itens_slate(cur, "slate-1")

    sql = cur.queries[0][0]
    assert "quarentena is not true" in sql


def test_carregar_itens_slate_mapeia_colunas():
    kickoff = datetime(2026, 8, 11, 21, 0, tzinfo=timezone.utc)
    cur = FakeCursor(
        fetchall_results=[
            [
                (
                    "sp-1", "pick-1", "fix-1", 1, "automatico",
                    "1x2", "Home win", "Goias", "Londrina", "Serie B",
                    kickoff, 1.85, "Bet365", 1.90, "oddspapi", 1.82,
                    "TipsterX", "Sites de Apostas",
                )
            ]
        ]
    )

    itens = carregar_itens_slate(cur, "slate-1")

    assert itens == (
        ItemSlate(
            slate_pick_id="sp-1", pick_id="pick-1", fixture_id="fix-1", ordem=1, incluido_por="automatico",
            mercado="1x2", selecao="Home win", time_casa="Goias", time_fora="Londrina", competicao="Serie B",
            kickoff_utc=kickoff, odd_citada=1.85, casa_citada="Bet365",
            odd_referencia=1.90, odd_referencia_origem="oddspapi", odd_minima=1.82,
            tipster="TipsterX", fonte_nome="Sites de Apostas",
        ),
    )


def test_conflitos_por_fixture_busca_revisao_manual_das_fixtures_do_slate():
    cur = FakeCursor(fetchall_results=[[("fix-1", "1x2", "pick-9", "Away win", "TipsterY")]])

    conflitos = conflitos_por_fixture(cur, fixture_ids=["fix-1"])

    assert conflitos == {("fix-1", "1x2"): [("pick-9", "Away win", "TipsterY")]}
    sql, params = cur.queries[0]
    assert "revisao_manual" in sql
    assert "quarentena is not true" in sql
    assert params == (["fix-1"],)


def test_conflitos_por_fixture_lista_vazia_sem_query():
    cur = FakeCursor()
    assert conflitos_por_fixture(cur, fixture_ids=[]) == {}
    assert cur.queries == []


def test_excluidos_do_dia_junta_picks_orfaos_tipo_excluido():
    cur = FakeCursor(fetchall_results=[[("pick-5", "sem odd de referencia disponivel", "Time A", "Time B")]])

    excluidos = excluidos_do_dia(cur, fixture_ids=["fix-1"])

    assert excluidos == [("pick-5", "sem odd de referencia disponivel", "Time A", "Time B")]
    sql, params = cur.queries[0]
    assert "tipo = 'excluido'" in sql
    assert params == (["fix-1"],)


def test_excluidos_do_dia_lista_vazia_sem_query():
    cur = FakeCursor()
    assert excluidos_do_dia(cur, fixture_ids=[]) == []
    assert cur.queries == []


def test_existe_pick_quarentena_no_slate_true():
    cur = FakeCursor(fetchone_results=[(1,)])

    assert existe_pick_quarentena_no_slate(cur, "slate-1") is True
    sql, params = cur.queries[0]
    assert "quarentena is true" in sql
    assert params == ("slate-1",)


def test_existe_pick_quarentena_no_slate_false():
    cur = FakeCursor(fetchone_results=[None])
    assert existe_pick_quarentena_no_slate(cur, "slate-1") is False


def test_buscar_status_slate_retorna_status():
    cur = FakeCursor(fetchone_results=[("rascunho",)])
    assert buscar_status_slate(cur, "slate-1") == "rascunho"


def test_buscar_status_slate_none_quando_nao_existe():
    cur = FakeCursor(fetchone_results=[None])
    assert buscar_status_slate(cur, "slate-fantasma") is None


def test_fixturas_elegiveis_do_dia_mapeia_colunas():
    kickoff = datetime(2026, 8, 11, 21, 0, tzinfo=timezone.utc)
    cur = FakeCursor(fetchall_results=[[("fix-1", "Goias", "Londrina", "bra.2", kickoff)]])

    fixturas = fixturas_elegiveis_do_dia(cur)

    assert fixturas == (
        FixturaElegivel(fixture_id="fix-1", time_casa="Goias", time_fora="Londrina", liga="bra.2", kickoff_utc=kickoff),
    )
    sql = cur.queries[0][0]
    assert "status = 'agendada'" in sql
    assert "interval '24 hours'" in sql
