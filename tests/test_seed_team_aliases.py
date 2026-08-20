from app.espn_teams import EspnTeam
from scripts.seed_team_aliases import seed, upsert_alias, upsert_team
from tests._fakes import FakeConnection, FakeCursor


def test_upsert_team_novo_usa_so_o_insert():
    cur = FakeCursor([("id-novo",)])

    team_id, inserido = upsert_team(cur, EspnTeam(espn_team_id="1", nome_canonico="Time X", aliases=frozenset()))

    assert team_id == "id-novo"
    assert inserido is True
    assert len(cur.queries) == 1
    assert "insert into teams" in cur.queries[0][0]


def test_upsert_team_existente_cai_para_select_apos_conflito():
    cur = FakeCursor([None, ("id-existente",)])

    team_id, inserido = upsert_team(cur, EspnTeam(espn_team_id="1", nome_canonico="Time X", aliases=frozenset()))

    assert team_id == "id-existente"
    assert inserido is False
    assert len(cur.queries) == 2
    assert "select id from teams" in cur.queries[1][0]


def test_upsert_alias_novo_retorna_true():
    cur = FakeCursor([("alias-id",)])

    assert upsert_alias(cur, "team-1", "Flamengo") is True


def test_upsert_alias_ja_existente_retorna_false():
    cur = FakeCursor([None])

    assert upsert_alias(cur, "team-1", "Flamengo") is False


def test_seed_conta_apenas_times_e_aliases_novos_e_comita_uma_vez():
    times = [
        EspnTeam(espn_team_id="a", nome_canonico="Time A", aliases=frozenset({"Alias A"})),
        EspnTeam(espn_team_id="b", nome_canonico="Time B", aliases=frozenset({"Alias B"})),
    ]
    # Time A: insert novo (1 fetchone) + alias novo (1 fetchone).
    # Time B: insert em conflito -> None, select existente (2 fetchone) +
    # alias ja existente -> None (1 fetchone).
    cur = FakeCursor([("id-a",), ("alias-a-id",), None, ("id-b",), None])
    conn = FakeConnection(cur)

    times_novos, aliases_novos = seed(conn, times)

    assert times_novos == 1
    assert aliases_novos == 1
    assert conn.committed is True
