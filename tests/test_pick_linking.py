from datetime import date, datetime, timezone

from app.matcher import TeamAlias
from app.pick_linking import (
    FixtureCandidata,
    PickParaVincular,
    parse_data_referencia,
    vincular_pick,
)

ALIASES = [
    TeamAlias(team_id="time-a", alias_normalizado="goias"),
    TeamAlias(team_id="time-b", alias_normalizado="londrina"),
    TeamAlias(team_id="time-c", alias_normalizado="cruzeiro"),
]


def _fixture(fixture_id, home, away, kickoff) -> FixtureCandidata:
    return FixtureCandidata(fixture_id=fixture_id, home_team_id=home, away_team_id=away, kickoff_utc=kickoff)


def test_parse_data_referencia_formato_br():
    assert parse_data_referencia("10/08/2026") == date(2026, 8, 10)


def test_parse_data_referencia_formato_desconhecido_retorna_none():
    assert parse_data_referencia("hoje") is None
    assert parse_data_referencia(None) is None
    assert parse_data_referencia("") is None


def test_vincular_pick_time_faltando_fica_extraido():
    pick = PickParaVincular("p1", time_casa=None, time_fora="Londrina", data_referencia="10/08/2026")

    resultado = vincular_pick(pick, ALIASES, {})

    assert resultado.status == "extraido"
    assert resultado.fixture_id is None
    assert resultado.motivo == "sem_times_no_pick"


def test_vincular_pick_time_nao_resolvido_fica_extraido():
    pick = PickParaVincular("p1", time_casa="Time Desconhecido XYZ", time_fora="Londrina", data_referencia="10/08/2026")

    resultado = vincular_pick(pick, ALIASES, {})

    assert resultado.status == "extraido"
    assert resultado.fixture_id is None
    assert resultado.motivo == "time_nao_resolvido"


def test_vincular_pick_sem_fixture_candidata_fica_extraido():
    pick = PickParaVincular("p1", time_casa="Goias", time_fora="Londrina", data_referencia="10/08/2026")

    resultado = vincular_pick(pick, ALIASES, {})

    assert resultado.status == "extraido"
    assert resultado.motivo == "sem_fixture_na_janela"


def test_vincular_pick_match_unico_dentro_da_janela_fica_vinculado():
    pick = PickParaVincular("p1", time_casa="Goias", time_fora="Londrina", data_referencia="10/08/2026")
    kickoff = datetime(2026, 8, 10, 22, 30, tzinfo=timezone.utc)
    fixtures = {("time-a", "time-b"): [_fixture("fix-1", "time-a", "time-b", kickoff)]}

    resultado = vincular_pick(pick, ALIASES, fixtures)

    assert resultado.status == "vinculado"
    assert resultado.fixture_id == "fix-1"
    assert resultado.score_matching == 100.0
    assert resultado.motivo is None


def test_vincular_pick_fixture_fora_da_janela_fica_extraido():
    pick = PickParaVincular("p1", time_casa="Goias", time_fora="Londrina", data_referencia="10/08/2026")
    # kickoff 10 dias depois da data_referencia - bem fora da janela de 36h
    kickoff = datetime(2026, 8, 20, 22, 30, tzinfo=timezone.utc)
    fixtures = {("time-a", "time-b"): [_fixture("fix-1", "time-a", "time-b", kickoff)]}

    resultado = vincular_pick(pick, ALIASES, fixtures)

    assert resultado.status == "extraido"
    assert resultado.motivo == "sem_fixture_na_janela"


def test_vincular_pick_multiplas_fixtures_na_janela_fica_revisao_manual():
    # Confronto de ida e volta, ambos dentro da janela de 36h - nunca
    # chuta qual dos dois e o certo.
    pick = PickParaVincular("p1", time_casa="Goias", time_fora="Londrina", data_referencia="10/08/2026")
    fixtures = {
        ("time-a", "time-b"): [
            _fixture("fix-1", "time-a", "time-b", datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)),
            _fixture("fix-2", "time-a", "time-b", datetime(2026, 8, 10, 22, 0, tzinfo=timezone.utc)),
        ]
    }

    resultado = vincular_pick(pick, ALIASES, fixtures)

    assert resultado.status == "revisao_manual"
    assert resultado.fixture_id is None


def test_vincular_pick_sem_data_referencia_usa_qualquer_candidata_unica():
    # data_referencia nao parseavel - sem janela pra filtrar. Se so existe
    # UMA fixture candidata pro par de times (independente de data), nao
    # ha ambiguidade real e o vinculo e seguro.
    pick = PickParaVincular("p1", time_casa="Goias", time_fora="Londrina", data_referencia="hoje")
    fixtures = {("time-a", "time-b"): [_fixture("fix-1", "time-a", "time-b", datetime(2026, 8, 10, 22, 30, tzinfo=timezone.utc))]}

    resultado = vincular_pick(pick, ALIASES, fixtures)

    assert resultado.status == "vinculado"
    assert resultado.fixture_id == "fix-1"


def test_vincular_pick_sem_data_referencia_e_multiplas_candidatas_fica_revisao_manual():
    pick = PickParaVincular("p1", time_casa="Goias", time_fora="Londrina", data_referencia=None)
    fixtures = {
        ("time-a", "time-b"): [
            _fixture("fix-1", "time-a", "time-b", datetime(2026, 8, 10, 22, 30, tzinfo=timezone.utc)),
            _fixture("fix-2", "time-a", "time-b", datetime(2026, 9, 1, 22, 30, tzinfo=timezone.utc)),
        ]
    }

    resultado = vincular_pick(pick, ALIASES, fixtures)

    assert resultado.status == "revisao_manual"


def test_vincular_pick_score_e_o_minimo_entre_os_dois_times():
    # "Goias" bate exato (100.0), "Londrino" bate so por fuzzy (~87.5,
    # acima do threshold mas abaixo de 100) - score_matching do vinculo
    # deve refletir o pior dos dois casamentos, nao o melhor.
    pick = PickParaVincular("p1", time_casa="Goias", time_fora="Londrino", data_referencia="10/08/2026")
    kickoff = datetime(2026, 8, 10, 22, 30, tzinfo=timezone.utc)
    fixtures = {("time-a", "time-b"): [_fixture("fix-1", "time-a", "time-b", kickoff)]}

    resultado = vincular_pick(pick, ALIASES, fixtures)

    assert resultado.status == "vinculado"
    assert resultado.score_matching < 100.0
