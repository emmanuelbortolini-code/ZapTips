from datetime import datetime, timezone

import httpx

from app.matcher import TeamAlias
from app.oddspapi import OddsPapiFixtureOdds
from scripts.collect_odds import (
    _erro_sem_segredo,
    carregar_fixtures_por_times,
    carregar_team_aliases,
    filtrar_aliases_relevantes,
    processar_odds,
    registrar_chamada_api,
    resolver_participante,
    upsert_casa,
    upsert_odds_referencia,
    validar_participantes,
)
from tests._fakes import FakeCursor

_KICKOFF = datetime(2026, 8, 15, 19, 30, tzinfo=timezone.utc)


def test_upsert_casa_grava_licenciada_br_true():
    cur = FakeCursor(fetchone_results=[("casa-id",)])

    casa_id = upsert_casa(cur, "Bet365", "bet365")

    assert casa_id == "casa-id"
    sql, params = cur.queries[0]
    assert "insert into casas" in sql
    assert "Bet365" in params and "bet365" in params


def test_upsert_odds_referencia_grava_origem_oddspapi():
    cur = FakeCursor()

    upsert_odds_referencia(cur, "fixture-1", "casa-1", "1x2", "casa", None, 2.82)

    sql, params = cur.queries[0]
    assert "insert into odds_referencia" in sql
    assert "'oddspapi'" in sql
    assert 2.82 in params


def test_registrar_chamada_api_retorna_total_do_mes():
    cur = FakeCursor(fetchone_results=[(15,)])

    total = registrar_chamada_api(cur, "oddspapi", limite=250)

    assert total == 15


def test_registrar_chamada_api_loga_perto_do_limite():
    cur = FakeCursor(fetchone_results=[(200,)])

    total = registrar_chamada_api(cur, "oddspapi", limite=250)

    assert total == 200  # 200/250 = 0.8, cruza o alerta - so garante que nao quebra


def test_carregar_fixtures_por_times_resolve_confronto_unico():
    cur = FakeCursor(fetchall_results=[[("bra.1", "time-a", "time-b", "fixture-1")]])

    resultado = carregar_fixtures_por_times(cur, ["bra.1"])

    assert resultado == {("bra.1", "time-a", "time-b"): "fixture-1"}


def test_carregar_fixtures_por_times_marca_confronto_ambiguo_como_none():
    cur = FakeCursor(
        fetchall_results=[
            [
                ("bra.1", "time-a", "time-b", "fixture-1"),
                ("bra.1", "time-a", "time-b", "fixture-2"),
            ]
        ]
    )

    resultado = carregar_fixtures_por_times(cur, ["bra.1"])

    assert resultado == {("bra.1", "time-a", "time-b"): None}


def test_carregar_team_aliases_converte_para_TeamAlias():
    cur = FakeCursor(fetchall_results=[[("time-a", "flamengo")]])

    resultado = carregar_team_aliases(cur)

    assert resultado == [TeamAlias(team_id="time-a", alias_normalizado="flamengo")]


def test_filtrar_aliases_relevantes_mantem_so_times_com_fixture_na_janela():
    # Cenario real: "atletico mineiro" tem 2 aliases no banco (time
    # principal + um time de categoria de base semeado da mesma ESPN),
    # mas so o principal tem fixture na janela atual de bra.1/bra.2.
    aliases = [
        TeamAlias(team_id="atletico-mg-principal", alias_normalizado="atletico mineiro"),
        TeamAlias(team_id="atletico-mg-sub20", alias_normalizado="atletico mineiro"),
        TeamAlias(team_id="flamengo", alias_normalizado="flamengo"),
    ]
    fixtures_por_times = {("bra.1", "atletico-mg-principal", "flamengo"): "fixture-1"}

    resultado = filtrar_aliases_relevantes(aliases, fixtures_por_times)

    assert resultado == [
        TeamAlias(team_id="atletico-mg-principal", alias_normalizado="atletico mineiro"),
        TeamAlias(team_id="flamengo", alias_normalizado="flamengo"),
    ]


def test_filtrar_aliases_relevantes_ignora_chaves_ambiguas_marcadas_como_none():
    aliases = [TeamAlias(team_id="time-a", alias_normalizado="time a")]
    fixtures_por_times = {("bra.1", "time-a", "time-b"): None}

    resultado = filtrar_aliases_relevantes(aliases, fixtures_por_times)

    # Chave ambigua (valor None) ainda contribui os team_ids envolvidos -
    # eles participam da janela mesmo que a fixture exata nao tenha sido
    # resolvida.
    assert resultado == [TeamAlias(team_id="time-a", alias_normalizado="time a")]


def test_resolver_participante_com_match_exato():
    aliases = [TeamAlias(team_id="time-a", alias_normalizado="fluminense")]
    participantes = {"1961": "Fluminense"}

    team_id = resolver_participante("1961", participantes, aliases)

    assert team_id == "time-a"


def test_resolver_participante_sem_nome_no_catalogo_retorna_none():
    team_id = resolver_participante("999", participantes={}, aliases=[])

    assert team_id is None


def test_resolver_participante_ambiguo_retorna_none():
    # "Botafogo" bate para dois times diferentes (RJ e SP) - nao pode
    # chutar, mesma politica do matcher.
    aliases = [
        TeamAlias(team_id="botafogo-rj", alias_normalizado="botafogo"),
        TeamAlias(team_id="botafogo-sp", alias_normalizado="botafogo"),
    ]
    participantes = {"1": "Botafogo"}

    team_id = resolver_participante("1", participantes, aliases)

    assert team_id is None


def test_processar_odds_grava_todas_as_selecoes_de_um_fixture_casado():
    odds = [
        OddsPapiFixtureOdds(
            oddspapi_fixture_id="1", tournament_id=325, start_time=_KICKOFF,
            participant1_id="1961", participant2_id="1963", bookmaker="bet365",
            precos={"casa": 1.5, "empate": 3.4, "fora": 5.0},
        ),
    ]
    cur = FakeCursor()
    aliases = [
        TeamAlias(team_id="time-fluminense", alias_normalizado="fluminense"),
        TeamAlias(team_id="time-palmeiras", alias_normalizado="palmeiras"),
    ]
    participantes = {"1961": "Fluminense", "1963": "Palmeiras"}
    fixtures_por_times = {("bra.1", "time-fluminense", "time-palmeiras"): "fixture-1"}
    liga_by_tournament_id = {"325": "bra.1"}

    gravadas, nao_casadas = processar_odds(
        cur, odds, liga_by_tournament_id, fixtures_por_times, participantes, aliases, casa_id="casa-1"
    )

    assert gravadas == 3
    assert nao_casadas == 0
    assert len(cur.queries) == 3


def test_processar_odds_time_sem_match_conta_como_nao_casada():
    odds = [
        OddsPapiFixtureOdds(
            oddspapi_fixture_id="1", tournament_id=325, start_time=_KICKOFF,
            participant1_id="1961", participant2_id="1963", bookmaker="bet365",
            precos={"casa": 1.5, "empate": 3.4, "fora": 5.0},
        ),
    ]
    cur = FakeCursor()

    gravadas, nao_casadas = processar_odds(
        cur, odds, liga_by_tournament_id={"325": "bra.1"}, fixtures_por_times={},
        participantes={}, aliases=[], casa_id="casa-1",
    )

    assert gravadas == 0
    assert nao_casadas == 3
    assert cur.queries == []


def test_processar_odds_torneio_fora_do_league_map_conta_como_nao_casada():
    odds = [
        OddsPapiFixtureOdds(
            oddspapi_fixture_id="1", tournament_id=999, start_time=_KICKOFF,
            participant1_id="1961", participant2_id="1963", bookmaker="bet365",
            precos={"casa": 1.5},
        ),
    ]
    cur = FakeCursor()

    gravadas, nao_casadas = processar_odds(
        cur, odds, liga_by_tournament_id={"325": "bra.1"}, fixtures_por_times={},
        participantes={}, aliases=[], casa_id="casa-1",
    )

    assert gravadas == 0
    assert nao_casadas == 1


def test_processar_odds_home_away_trocado_nao_grava_mas_nao_derruba():
    # Se o inverso (away, home) bate mas o par (home, away) nao, o
    # pressuposto "participant1Id = mandante" quebrou pra esse caso -
    # melhor nao gravar (odd trocada seria pior que odd faltando) do que
    # chutar.
    odds = [
        OddsPapiFixtureOdds(
            oddspapi_fixture_id="1", tournament_id=325, start_time=_KICKOFF,
            participant1_id="1963", participant2_id="1961", bookmaker="bet365",
            precos={"casa": 1.5, "empate": 3.4, "fora": 5.0},
        ),
    ]
    cur = FakeCursor()
    aliases = [
        TeamAlias(team_id="time-fluminense", alias_normalizado="fluminense"),
        TeamAlias(team_id="time-palmeiras", alias_normalizado="palmeiras"),
    ]
    participantes = {"1961": "Fluminense", "1963": "Palmeiras"}
    # Fixture real: mandante Fluminense, visitante Palmeiras.
    fixtures_por_times = {("bra.1", "time-fluminense", "time-palmeiras"): "fixture-1"}
    liga_by_tournament_id = {"325": "bra.1"}

    gravadas, nao_casadas = processar_odds(
        cur, odds, liga_by_tournament_id, fixtures_por_times, participantes, aliases, casa_id="casa-1"
    )

    assert gravadas == 0
    assert nao_casadas == 3
    assert cur.queries == []


def test_validar_participantes_aceita_dict():
    assert validar_participantes({"1961": "Fluminense"}) == {"1961": "Fluminense"}


def test_validar_participantes_rejeita_none():
    # /participants pode devolver 200 com corpo null (API sem contrato de
    # estabilidade) - isso nao e HTTPError, so um formato inesperado.
    assert validar_participantes(None) is None


def test_validar_participantes_rejeita_lista():
    assert validar_participantes(["Fluminense", "Palmeiras"]) is None


def test_erro_sem_segredo_nunca_expoe_a_url_com_apikey():
    # httpx.HTTPStatusError.__str__() inclui a URL completa da resposta,
    # que carrega a apiKey como query param nesta API. O helper nunca pode
    # deixar a apiKey vazar pro log.
    request = httpx.Request("GET", "https://api.oddspapi.io/v4/odds-by-tournaments?apiKey=segredo-real")
    response = httpx.Response(403, request=request)
    exc = httpx.HTTPStatusError("erro", request=request, response=response)

    mensagem = _erro_sem_segredo(exc)

    assert "segredo-real" not in mensagem
    assert mensagem == "HTTP 403"


def test_erro_sem_segredo_lida_com_erro_de_conexao():
    exc = httpx.ConnectTimeout("timeout")

    mensagem = _erro_sem_segredo(exc)

    assert mensagem == "ConnectTimeout"
