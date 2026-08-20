from datetime import datetime, timezone

from app.pick_linking import PickParaVincular, ResultadoVinculo
from scripts.link_picks import (
    aplicar_vinculo,
    buscar_picks_extraidos,
    carregar_aliases_relevantes,
    carregar_fixtures_por_par,
)
from tests._fakes import FakeCursor


def test_buscar_picks_extraidos_mapeia_colunas():
    cur = FakeCursor(fetchall_results=[[("p1", "Goias", "Londrina", "10/08/2026")]])

    picks = buscar_picks_extraidos(cur)

    assert picks == [PickParaVincular(pick_id="p1", time_casa="Goias", time_fora="Londrina", data_referencia="10/08/2026")]
    assert "status = 'extraido'" in cur.queries[0][0]


def test_carregar_fixtures_por_par_agrupa_e_ignora_time_nulo():
    kickoff = datetime(2026, 8, 10, 22, 30, tzinfo=timezone.utc)
    cur = FakeCursor(
        fetchall_results=[
            [
                ("fix-1", "time-a", "time-b", kickoff),
                ("fix-2", None, "time-b", kickoff),
            ]
        ]
    )

    fixtures_por_par = carregar_fixtures_por_par(cur)

    assert set(fixtures_por_par.keys()) == {("time-a", "time-b")}
    assert len(fixtures_por_par[("time-a", "time-b")]) == 1
    assert fixtures_por_par[("time-a", "time-b")][0].fixture_id == "fix-1"


def test_carregar_aliases_relevantes_filtra_times_fora_do_conjunto():
    cur = FakeCursor(fetchall_results=[[("time-a", "goias"), ("time-x", "time-fora-de-escopo")]])

    aliases = carregar_aliases_relevantes(cur, times_relevantes={"time-a"})

    assert [a.team_id for a in aliases] == ["time-a"]


def test_aplicar_vinculo_vinculado_atualiza_fixture_e_score_e_limpa_orfao():
    cur = FakeCursor()

    aplicar_vinculo(
        cur, ResultadoVinculo(pick_id="p1", fixture_id="fix-1", score_matching=95.0, status="vinculado"), contar_tentativa=True
    )

    sql, params = cur.queries[0]
    assert "status = 'vinculado'" in sql
    assert params == ("fix-1", 95.0, "p1")
    # limpa um eventual registro de orfao 'sem_fixture' de tentativas
    # anteriores - o pick achou fixture, o contador nao faz mais sentido.
    sql2, params2 = cur.queries[1]
    assert "delete from picks_orfaos" in sql2
    assert params2 == ("p1", "sem_fixture")


def test_aplicar_vinculo_revisao_manual_so_atualiza_status():
    cur = FakeCursor()

    aplicar_vinculo(
        cur, ResultadoVinculo(pick_id="p1", fixture_id=None, score_matching=None, status="revisao_manual"), contar_tentativa=True
    )

    sql, params = cur.queries[0]
    assert "revisao_manual" in sql
    assert params == ("p1",)
    assert len(cur.queries) == 1


def test_aplicar_vinculo_extraido_sem_motivo_nao_executa_query():
    cur = FakeCursor()

    aplicar_vinculo(
        cur, ResultadoVinculo(pick_id="p1", fixture_id=None, score_matching=None, status="extraido"), contar_tentativa=True
    )

    assert cur.queries == []


def test_aplicar_vinculo_extraido_time_nao_resolvido_nunca_conta_tentativa():
    # D1: pick de liga fora de escopo nunca vai achar fixture so com o
    # tempo passando - contar tentativa aqui inundaria a fila de revisao
    # manual com ~1000 itens inacionaveis (ver CLAUDE.md, Fase 5a).
    cur = FakeCursor()

    aplicar_vinculo(
        cur,
        ResultadoVinculo(pick_id="p1", fixture_id=None, score_matching=None, status="extraido", motivo="time_nao_resolvido"),
        contar_tentativa=True,
    )

    assert cur.queries == []


def test_aplicar_vinculo_sem_fixture_na_janela_conta_tentativa_quando_pedido():
    cur = FakeCursor(fetchone_results=[(1,)])

    aplicar_vinculo(
        cur,
        ResultadoVinculo(pick_id="p1", fixture_id=None, score_matching=None, status="extraido", motivo="sem_fixture_na_janela"),
        contar_tentativa=True,
    )

    sql, params = cur.queries[0]
    assert "insert into picks_orfaos" in sql
    assert params == ("p1", "sem_fixture", "pick sem fixture na janela de kickoff ainda")


def test_aplicar_vinculo_sem_fixture_na_janela_nao_conta_quando_fixtures_nao_trouxe_novas():
    # D2: contador so avanca quando a etapa fixtures trouxe partida nova
    # nesta execucao - senao uma semana parada queimaria tentativas a toa.
    cur = FakeCursor()

    aplicar_vinculo(
        cur,
        ResultadoVinculo(pick_id="p1", fixture_id=None, score_matching=None, status="extraido", motivo="sem_fixture_na_janela"),
        contar_tentativa=False,
    )

    assert cur.queries == []


def test_aplicar_vinculo_sem_fixture_na_janela_escala_apos_5_tentativas():
    cur = FakeCursor(fetchone_results=[(5,)])

    aplicar_vinculo(
        cur,
        ResultadoVinculo(pick_id="p1", fixture_id=None, score_matching=None, status="extraido", motivo="sem_fixture_na_janela"),
        contar_tentativa=True,
    )

    assert len(cur.queries) == 2
    sql, params = cur.queries[1]
    assert "revisao_manual" in sql
    assert params == ("p1",)
