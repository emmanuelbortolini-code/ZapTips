"""Fetch e parsing do OddsPapi (api.oddspapi.io/v4): odd de referencia
independente, nivel 2 da hierarquia (ver CLAUDE.md, "Fase 1b").

Escopo desta etapa: so o mercado 1x2 (moneyline), o unico confirmado com
dado real e usado no exemplo motivador do documento original. Outros
mercados (over/under, ambas marcam, cartoes, escanteios) ficam para
quando a Fase 3/4 (extracao/curadoria de palpites) precisar deles - mesmo
criterio ja usado no coletor de fixtures e no job de resultados: escopo
minimo, validado com dado real, extensivel depois.

Achados da verificacao real (Fase 1b, documentados no CLAUDE.md):
- `sportId=10` e obrigatorio e nao documentado no material original.
- So os slugs globais de casa funcionam na chave gratuita (nunca
  `.bet.br`, que devolve 403 RESTRICTED_ACCESS).
- `oddsFormat=decimal` sempre, autenticacao via query param `apiKey`.

Achado da Fase 1g (correcao de design, ver CLAUDE.md): `/odds-by-tournaments`
so devolve `participant1Id`/`participant2Id` numericos, sem nome de time.
Casar fixture so por (liga, kickoff_utc) parecia suficiente, mas dado real
mostrou ~60% de colisao de horario no Brasileirao (rodadas usam sempre os
mesmos 3-4 horarios padrao). `participant1Id` e sempre o mandante -
confirmado com o exemplo real Palmeiras x Fluminense, onde participant1Id
bateu com o time que a ESPN marca como `home`. `fetch_participants` resolve
os IDs pra nome (catalogo grande mas estatico, ~19500 times de todos os
campeonatos - cachear e revalidar raramente, mesmo tratamento de
/bookmakers e /tournaments); o nome resolvido entao passa pelo
`app.matcher` ja existente contra `team_aliases`.
"""

from dataclasses import dataclass
from datetime import datetime

import httpx

SPORT_ID_SOCCER = 10
MARKET_1X2_ID = "101"
OUTCOME_1X2 = {"101": "casa", "102": "empate", "103": "fora"}

# Cooldown entre chamadas ao mesmo endpoint (aqui, sempre
# /odds-by-tournaments, uma vez por casa) - exigencia documentada do
# provedor, nao inventada.
COOLDOWN_SECONDS = 5.0


@dataclass(frozen=True)
class OddsPapiFixtureOdds:
    oddspapi_fixture_id: str
    tournament_id: int
    start_time: datetime
    participant1_id: str
    participant2_id: str
    bookmaker: str
    precos: dict[str, float]


def parse_odds_by_tournaments_response(payload: list, bookmaker: str) -> tuple[list[OddsPapiFixtureOdds], int]:
    resultado: list[OddsPapiFixtureOdds] = []
    ignoradas = 0

    for fixture in payload or []:
        try:
            item = _parse_fixture(fixture, bookmaker)
        except (AttributeError, KeyError, TypeError, ValueError):
            ignoradas += 1
            continue

        if item is not None:
            resultado.append(item)

    return resultado, ignoradas


def _campos_comuns_fixture(fixture: dict) -> tuple[str, int, datetime, str, str]:
    fixture_id = fixture.get("fixtureId")
    tournament_id = fixture.get("tournamentId")
    start_time_raw = fixture.get("startTime")
    participant1_id = fixture.get("participant1Id")
    participant2_id = fixture.get("participant2Id")
    if not (fixture_id and tournament_id is not None and start_time_raw and participant1_id and participant2_id):
        # Campo obrigatorio faltando de verdade (nao so "sem odd") - vira
        # excecao de proposito, pro try/except externo contar como
        # ignorada. Diferente de hasOdds=false, que e um caso esperado e
        # nao um problema de dado.
        raise ValueError("fixture sem id/torneio/horario/participantes")

    start_time = datetime.fromisoformat(start_time_raw.replace("Z", "+00:00"))
    return str(fixture_id), int(tournament_id), start_time, str(participant1_id), str(participant2_id)


def _precos_do_mercado(markets: dict, market_id: str, outcome_map: dict[str, str]) -> dict[str, float]:
    mercado = (markets or {}).get(market_id)
    if not mercado or not mercado.get("marketActive", True):
        return {}

    precos: dict[str, float] = {}
    for outcome_id, selecao in outcome_map.items():
        outcome = (mercado.get("outcomes") or {}).get(outcome_id)
        if not outcome:
            continue
        # Uma selecao malformada (formato inesperado nesta API sem
        # contrato de estabilidade) nao pode derrubar as outras do mesmo
        # fixture - mesma licao ja aplicada em espn_summary.py.
        try:
            preco = _extrair_preco(outcome)
            if preco is None:
                continue
            precos[selecao] = float(preco)
        except (AttributeError, TypeError, ValueError):
            continue
    return precos


def _parse_fixture(fixture: dict, bookmaker: str) -> OddsPapiFixtureOdds | None:
    if not fixture.get("hasOdds"):
        return None

    fixture_id, tournament_id, start_time, participant1_id, participant2_id = _campos_comuns_fixture(fixture)

    markets = ((fixture.get("bookmakerOdds") or {}).get(bookmaker) or {}).get("markets") or {}
    precos = _precos_do_mercado(markets, MARKET_1X2_ID, OUTCOME_1X2)
    if not precos:
        return None

    return OddsPapiFixtureOdds(
        oddspapi_fixture_id=fixture_id,
        tournament_id=tournament_id,
        start_time=start_time,
        participant1_id=participant1_id,
        participant2_id=participant2_id,
        bookmaker=bookmaker,
        precos=precos,
    )


@dataclass(frozen=True)
class OddSelecao:
    mercado: str
    selecao: str
    linha: float | None
    valor: float


@dataclass(frozen=True)
class OddsPapiFixtureExtra:
    oddspapi_fixture_id: str
    tournament_id: int
    start_time: datetime
    participant1_id: str
    participant2_id: str
    bookmaker: str
    odds: tuple[OddSelecao, ...]


MARKET_BTTS_ID = "104"
OUTCOME_BTTS = {"104": "sim", "105": "nao"}

# Over/Under gols, tempo cheio - o marketId muda por linha (nao e fixo
# como 1x2/BTTS). Fonte: GET /markets (catalogo estatico da OddsPapi, ja
# usado desde a Fase 1b) filtrado sportId=10, marketType='totals',
# period='fulltime' - confirmado ao vivo em 2026-08-20 contra a API real,
# nao documentado em lugar nenhum do material original. Cada entrada:
# linha -> (marketId, outcome_id_over, outcome_id_under).
MARKETS_TOTAL_FULLTIME: dict[float, tuple[str, str, str]] = {
    0.25: ("10158", "10158", "10159"),
    0.5: ("106", "106", "107"),
    0.75: ("10160", "10160", "10161"),
    1.0: ("10162", "10162", "10163"),
    1.25: ("10164", "10164", "10165"),
    1.5: ("108", "108", "109"),
    1.75: ("10166", "10166", "10167"),
    2.0: ("10168", "10168", "10169"),
    2.25: ("10170", "10170", "10171"),
    2.5: ("1010", "1010", "1011"),
    2.75: ("10172", "10172", "10173"),
    3.0: ("10174", "10174", "10175"),
    3.25: ("10176", "10176", "10177"),
    3.5: ("1012", "1012", "1013"),
    3.75: ("10178", "10178", "10179"),
    4.0: ("10180", "10180", "10181"),
    4.25: ("10182", "10182", "10183"),
    4.5: ("1014", "1014", "1015"),
    4.75: ("10184", "10184", "10185"),
    5.0: ("10186", "10186", "10187"),
    5.25: ("10188", "10188", "10189"),
    5.5: ("1016", "1016", "1017"),
    5.75: ("10190", "10190", "10191"),
    6.0: ("10192", "10192", "10193"),
    6.25: ("10194", "10194", "10195"),
    6.5: ("1018", "1018", "1019"),
    6.75: ("10196", "10196", "10197"),
    7.0: ("10198", "10198", "10199"),
    7.25: ("10200", "10200", "10201"),
    7.5: ("1020", "1020", "1021"),
    7.75: ("10202", "10202", "10203"),
    8.0: ("10204", "10204", "10205"),
    8.25: ("10206", "10206", "10207"),
    8.5: ("1022", "1022", "1023"),
}


def parse_odds_extras_by_tournaments_response(
    payload: list, bookmaker: str
) -> tuple[list[OddsPapiFixtureExtra], int]:
    """Mesma resposta de /odds-by-tournaments ja buscada pro 1x2 (nenhuma
    chamada de rede extra, o payload inteiro ja vem com todos os mercados
    da casa) - so extrai mais mercados do mesmo payload: ambas_marcam
    (BTTS) e over_under (gols, todas as linhas conhecidas). Pedido do PM
    (2026-08-20, "nao tem como trazer as odds da fonte caso nao tenha da
    OddsPapi?"): a maioria dos picks reais do dia usa esses dois
    mercados, e o dado ja estava disponivel na mesma resposta que o
    projeto so usava parcialmente (so 1x2, Fase 1g)."""
    resultado: list[OddsPapiFixtureExtra] = []
    ignoradas = 0

    for fixture in payload or []:
        try:
            item = _parse_fixture_extras(fixture, bookmaker)
        except (AttributeError, KeyError, TypeError, ValueError):
            ignoradas += 1
            continue

        if item is not None:
            resultado.append(item)

    return resultado, ignoradas


def _parse_fixture_extras(fixture: dict, bookmaker: str) -> OddsPapiFixtureExtra | None:
    if not fixture.get("hasOdds"):
        return None

    fixture_id, tournament_id, start_time, participant1_id, participant2_id = _campos_comuns_fixture(fixture)
    markets = ((fixture.get("bookmakerOdds") or {}).get(bookmaker) or {}).get("markets") or {}

    odds: list[OddSelecao] = []
    for selecao, valor in _precos_do_mercado(markets, MARKET_BTTS_ID, OUTCOME_BTTS).items():
        odds.append(OddSelecao(mercado="ambas_marcam", selecao=selecao, linha=None, valor=valor))

    for linha, (market_id, over_id, under_id) in MARKETS_TOTAL_FULLTIME.items():
        precos_linha = _precos_do_mercado(markets, market_id, {over_id: "over", under_id: "under"})
        for selecao, valor in precos_linha.items():
            odds.append(OddSelecao(mercado="over_under", selecao=selecao, linha=linha, valor=valor))

    if not odds:
        return None

    return OddsPapiFixtureExtra(
        oddspapi_fixture_id=fixture_id,
        tournament_id=tournament_id,
        start_time=start_time,
        participant1_id=participant1_id,
        participant2_id=participant2_id,
        bookmaker=bookmaker,
        odds=tuple(odds),
    )


def _extrair_preco(outcome: dict) -> float | None:
    players = outcome.get("players") or {}
    jogador = players.get("0") or next(iter(players.values()), None)
    if not jogador:
        return None
    return jogador.get("price")


def fetch_odds_by_tournaments(
    client: httpx.Client, base_url: str, api_key: str, bookmaker: str, tournament_ids: list[str]
) -> list[dict]:
    resp = client.get(
        f"{base_url}/odds-by-tournaments",
        params={
            "apiKey": api_key,
            "oddsFormat": "decimal",
            "bookmaker": bookmaker,
            "tournamentIds": ",".join(tournament_ids),
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_participants(
    client: httpx.Client, base_url: str, api_key: str, sport_id: int = SPORT_ID_SOCCER
) -> dict[str, str]:
    resp = client.get(
        f"{base_url}/participants",
        params={"apiKey": api_key, "sportId": sport_id},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
