from datetime import datetime, timezone

from app.espn_fixtures import EspnFixtureRaw
from scripts.collect_fixtures import upsert_fixture
from tests._fakes import FakeCursor

_RAW = EspnFixtureRaw(
    espn_event_id="401841192",
    liga="bra.1",
    temporada="2026-brasileiro-serie-a",
    home_espn_team_id="3445",
    away_espn_team_id="2029",
    kickoff_utc=datetime(2026, 8, 15, 19, 30, tzinfo=timezone.utc),
    status="agendada",
    estadio="Estadio do Maracana",
)

_TEAM_IDS = {"3445": "uuid-fluminense", "2029": "uuid-palmeiras"}


def test_upsert_fixture_nova_marca_inserido_true():
    cur = FakeCursor([None, ("fixture-id",)])

    fixture_id, nova = upsert_fixture(cur, _RAW, _TEAM_IDS)

    assert fixture_id == "fixture-id"
    assert nova is True


def test_upsert_fixture_existente_marca_inserido_false():
    cur = FakeCursor([("ja-existe",), ("fixture-id",)])

    fixture_id, nova = upsert_fixture(cur, _RAW, _TEAM_IDS)

    assert fixture_id == "fixture-id"
    assert nova is False


def test_upsert_fixture_resolve_team_id_via_dict_espn_id():
    cur = FakeCursor([None, ("fixture-id",)])

    upsert_fixture(cur, _RAW, _TEAM_IDS)

    insert_sql, insert_params = cur.queries[1]
    assert "insert into fixtures" in insert_sql
    assert "uuid-fluminense" in insert_params
    assert "uuid-palmeiras" in insert_params


def test_upsert_fixture_com_time_nao_encontrado_grava_null():
    cur = FakeCursor([None, ("fixture-id",)])

    upsert_fixture(cur, _RAW, team_id_by_espn_id={})

    _, insert_params = cur.queries[1]
    assert None in insert_params


def test_upsert_fixture_sem_espn_team_id_grava_null_sem_consultar_dict():
    raw_sem_time = EspnFixtureRaw(
        espn_event_id="1",
        liga="bra.1",
        temporada=None,
        home_espn_team_id=None,
        away_espn_team_id=None,
        kickoff_utc=_RAW.kickoff_utc,
        status="agendada",
        estadio=None,
    )
    cur = FakeCursor([None, ("fixture-id",)])

    fixture_id, nova = upsert_fixture(cur, raw_sem_time, _TEAM_IDS)

    assert fixture_id == "fixture-id"
    assert nova is True
