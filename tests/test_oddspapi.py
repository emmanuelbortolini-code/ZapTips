from datetime import datetime, timezone

from app.oddspapi import (
    OddsPapiFixtureExtra,
    OddsPapiFixtureOdds,
    OddSelecao,
    parse_odds_by_tournaments_response,
    parse_odds_extras_by_tournaments_response,
)


def _fixture(**overrides) -> dict:
    base = {
        "fixtureId": "id1000032566886918",
        "tournamentId": 325,
        "startTime": "2026-08-15T19:30:00.000Z",
        "participant1Id": 1961,
        "participant2Id": 1963,
        "hasOdds": True,
        "bookmakerOdds": {
            "bet365": {
                "bookmakerIsActive": True,
                "suspended": False,
                "markets": {
                    "101": {
                        "marketActive": True,
                        "outcomes": {
                            "101": {"players": {"0": {"price": 2.82}}},
                            "102": {"players": {"0": {"price": 3.1}}},
                            "103": {"players": {"0": {"price": 2.5}}},
                        },
                    }
                },
            }
        },
    }
    base.update(overrides)
    return base


def test_parse_extrai_fixture_com_participantes_e_precos_das_3_selecoes():
    payload = [_fixture()]

    resultado, ignoradas = parse_odds_by_tournaments_response(payload, bookmaker="bet365")

    assert ignoradas == 0
    assert resultado == [
        OddsPapiFixtureOdds(
            oddspapi_fixture_id="id1000032566886918",
            tournament_id=325,
            start_time=datetime(2026, 8, 15, 19, 30, tzinfo=timezone.utc),
            participant1_id="1961",
            participant2_id="1963",
            bookmaker="bet365",
            precos={"casa": 2.82, "empate": 3.1, "fora": 2.5},
        )
    ]


def test_parse_ignora_fixture_sem_hasOdds():
    payload = [_fixture(hasOdds=False)]

    resultado, ignoradas = parse_odds_by_tournaments_response(payload, bookmaker="bet365")

    assert resultado == []
    assert ignoradas == 0


def test_parse_ignora_fixture_sem_mercado_1x2():
    payload = [_fixture(bookmakerOdds={"bet365": {"markets": {}}})]

    resultado, ignoradas = parse_odds_by_tournaments_response(payload, bookmaker="bet365")

    assert resultado == []
    assert ignoradas == 0


def test_parse_ignora_mercado_inativo():
    payload = [_fixture()]
    payload[0]["bookmakerOdds"]["bet365"]["markets"]["101"]["marketActive"] = False

    resultado, _ = parse_odds_by_tournaments_response(payload, bookmaker="bet365")

    assert resultado == []


def test_parse_ignora_bookmaker_diferente_do_pedido():
    payload = [_fixture()]

    resultado, _ = parse_odds_by_tournaments_response(payload, bookmaker="betano")

    assert resultado == []


def test_parse_mantem_selecoes_disponiveis_mesmo_faltando_uma():
    payload = [_fixture()]
    del payload[0]["bookmakerOdds"]["bet365"]["markets"]["101"]["outcomes"]["102"]

    resultado, ignoradas = parse_odds_by_tournaments_response(payload, bookmaker="bet365")

    assert ignoradas == 0
    assert set(resultado[0].precos) == {"casa", "fora"}


def test_parse_fixture_sem_id_ou_participantes_vira_ignorada():
    payload = [_fixture(participant1Id=None)]

    resultado, ignoradas = parse_odds_by_tournaments_response(payload, bookmaker="bet365")

    assert resultado == []
    assert ignoradas == 1


def test_parse_lida_com_bookmakerOdds_null_explicito_sem_crashar():
    # null explicito vira "sem mercado 1x2 pra essa casa", nao erro - o
    # mesmo tratamento de quando a chave simplesmente nao existe.
    payload = [_fixture(bookmakerOdds=None)]

    resultado, ignoradas = parse_odds_by_tournaments_response(payload, bookmaker="bet365")

    assert resultado == []
    assert ignoradas == 0


def test_parse_markets_null_explicito_nao_vira_erro_de_parsing():
    payload = [_fixture()]
    payload[0]["bookmakerOdds"]["bet365"]["markets"] = None

    resultado, ignoradas = parse_odds_by_tournaments_response(payload, bookmaker="bet365")

    assert resultado == []
    assert ignoradas == 0


def test_parse_selecao_malformada_nao_derruba_as_outras_do_mesmo_fixture():
    payload = [_fixture()]
    payload[0]["bookmakerOdds"]["bet365"]["markets"]["101"]["outcomes"]["101"] = "formato inesperado"

    resultado, ignoradas = parse_odds_by_tournaments_response(payload, bookmaker="bet365")

    assert ignoradas == 0
    assert set(resultado[0].precos) == {"empate", "fora"}


def test_parse_erro_inesperado_em_todo_o_fixture_vira_ignorada():
    payload = [_fixture()]
    payload[0]["bookmakerOdds"]["bet365"]["markets"]["101"]["outcomes"] = "formato inesperado"

    resultado, ignoradas = parse_odds_by_tournaments_response(payload, bookmaker="bet365")

    assert resultado == []
    assert ignoradas == 1


def test_parse_preco_nao_numerico_pula_so_essa_selecao():
    payload = [_fixture()]
    payload[0]["bookmakerOdds"]["bet365"]["markets"]["101"]["outcomes"]["101"]["players"]["0"]["price"] = "N/A"

    resultado, ignoradas = parse_odds_by_tournaments_response(payload, bookmaker="bet365")

    assert ignoradas == 0
    assert set(resultado[0].precos) == {"empate", "fora"}


def test_parse_selecao_sem_players_e_pulada_sem_erro():
    payload = [_fixture()]
    payload[0]["bookmakerOdds"]["bet365"]["markets"]["101"]["outcomes"]["101"] = {"players": {}}

    resultado, ignoradas = parse_odds_by_tournaments_response(payload, bookmaker="bet365")

    assert ignoradas == 0
    assert set(resultado[0].precos) == {"empate", "fora"}


def test_parse_todas_selecoes_invalidas_retorna_fixture_ignorado_silenciosamente():
    payload = [_fixture()]
    for outcome_id in ("101", "102", "103"):
        payload[0]["bookmakerOdds"]["bet365"]["markets"]["101"]["outcomes"][outcome_id] = {"players": {}}

    resultado, ignoradas = parse_odds_by_tournaments_response(payload, bookmaker="bet365")

    assert resultado == []
    assert ignoradas == 0


def test_parse_lista_vazia_retorna_vazio():
    resultado, ignoradas = parse_odds_by_tournaments_response([], bookmaker="bet365")

    assert resultado == []
    assert ignoradas == 0


def _fixture_extras(**overrides) -> dict:
    base = {
        "fixtureId": "id1000032566886918",
        "tournamentId": 325,
        "startTime": "2026-08-15T19:30:00.000Z",
        "participant1Id": 1961,
        "participant2Id": 1963,
        "hasOdds": True,
        "bookmakerOdds": {
            "bet365": {
                "markets": {
                    "104": {  # BTTS
                        "marketActive": True,
                        "outcomes": {
                            "104": {"players": {"0": {"price": 1.83}}},
                            "105": {"players": {"0": {"price": 1.83}}},
                        },
                    },
                    "1010": {  # over/under 2.5 gols
                        "marketActive": True,
                        "outcomes": {
                            "1010": {"players": {"0": {"price": 2.35}}},
                            "1011": {"players": {"0": {"price": 1.57}}},
                        },
                    },
                },
            }
        },
    }
    base.update(overrides)
    return base


def test_parse_extras_extrai_btts_e_over_under():
    payload = [_fixture_extras()]

    resultado, ignoradas = parse_odds_extras_by_tournaments_response(payload, bookmaker="bet365")

    assert ignoradas == 0
    assert len(resultado) == 1
    odds = set(resultado[0].odds)
    assert OddSelecao(mercado="ambas_marcam", selecao="sim", linha=None, valor=1.83) in odds
    assert OddSelecao(mercado="ambas_marcam", selecao="nao", linha=None, valor=1.83) in odds
    assert OddSelecao(mercado="over_under", selecao="over", linha=2.5, valor=2.35) in odds
    assert OddSelecao(mercado="over_under", selecao="under", linha=2.5, valor=1.57) in odds


def test_parse_extras_ignora_fixture_sem_hasOdds():
    payload = [_fixture_extras(hasOdds=False)]

    resultado, ignoradas = parse_odds_extras_by_tournaments_response(payload, bookmaker="bet365")

    assert resultado == []
    assert ignoradas == 0


def test_parse_extras_sem_nenhum_mercado_conhecido_devolve_none():
    payload = [_fixture_extras(bookmakerOdds={"bet365": {"markets": {}}})]

    resultado, ignoradas = parse_odds_extras_by_tournaments_response(payload, bookmaker="bet365")

    assert resultado == []
    assert ignoradas == 0


def test_parse_extras_mercado_inativo_e_ignorado_mas_outros_seguem():
    payload = [_fixture_extras()]
    payload[0]["bookmakerOdds"]["bet365"]["markets"]["104"]["marketActive"] = False

    resultado, ignoradas = parse_odds_extras_by_tournaments_response(payload, bookmaker="bet365")

    assert ignoradas == 0
    mercados = {o.mercado for o in resultado[0].odds}
    assert mercados == {"over_under"}  # BTTS inativo, over_under continua


def test_parse_extras_fixture_sem_participantes_vira_ignorada():
    payload = [_fixture_extras(participant1Id=None)]

    resultado, ignoradas = parse_odds_extras_by_tournaments_response(payload, bookmaker="bet365")

    assert resultado == []
    assert ignoradas == 1


def test_parse_extras_lista_vazia_retorna_vazio():
    resultado, ignoradas = parse_odds_extras_by_tournaments_response([], bookmaker="bet365")

    assert resultado == []
    assert ignoradas == 0
