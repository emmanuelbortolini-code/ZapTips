from app.espn_summary import EspnMatchResult, EspnTeamStats
from scripts.collect_results import atualizar_fixture, processar_resultado, upsert_fixture_stat
from tests._fakes import FakeCursor

_RESULTADO = EspnMatchResult(
    espn_event_id="401841183",
    status="encerrada",
    placar_casa=3,
    placar_fora=1,
    placar_ht_casa=1,
    placar_ht_fora=0,
)

_STAT_CASA = EspnTeamStats(
    espn_event_id="401841183",
    espn_team_id="2022",
    escanteios=4,
    cartoes_amarelos=3,
    cartoes_vermelhos=0,
    finalizacoes=11,
    posse=50.1,
)

_STAT_FORA = EspnTeamStats(
    espn_event_id="401841183",
    espn_team_id="9169",
    escanteios=2,
    cartoes_amarelos=1,
    cartoes_vermelhos=1,
    finalizacoes=8,
    posse=49.9,
)

_TEAM_IDS = {"2022": "uuid-cruzeiro", "9169": "uuid-mirassol"}


def test_atualizar_fixture_grava_status_e_placar():
    cur = FakeCursor([])

    atualizar_fixture(cur, "fixture-1", _RESULTADO)

    sql, params = cur.queries[0]
    assert "update fixtures" in sql
    assert params[0] == "encerrada"
    assert 3 in params and 1 in params


def test_upsert_fixture_stat_grava_origem_espn():
    cur = FakeCursor([])

    upsert_fixture_stat(cur, "fixture-1", "uuid-cruzeiro", _STAT_CASA)

    sql, params = cur.queries[0]
    assert "insert into fixture_stats" in sql
    assert "uuid-cruzeiro" in params
    assert 4 in params


def test_processar_resultado_atualiza_fixture_e_grava_stats_dos_dois_times():
    cur = FakeCursor([])

    gravados = processar_resultado(cur, "fixture-1", _RESULTADO, [_STAT_CASA, _STAT_FORA], _TEAM_IDS)

    assert gravados == 2
    # 1 update de fixtures + 2 inserts de fixture_stats.
    assert len(cur.queries) == 3


def test_processar_resultado_pula_time_nao_encontrado_sem_quebrar():
    cur = FakeCursor([])

    gravados = processar_resultado(cur, "fixture-1", _RESULTADO, [_STAT_CASA], team_id_by_espn_id={})

    assert gravados == 0
    assert len(cur.queries) == 1  # so o update de fixtures


def test_processar_resultado_sem_stats_so_atualiza_fixture():
    cur = FakeCursor([])

    gravados = processar_resultado(cur, "fixture-1", _RESULTADO, [], _TEAM_IDS)

    assert gravados == 0
    assert len(cur.queries) == 1
