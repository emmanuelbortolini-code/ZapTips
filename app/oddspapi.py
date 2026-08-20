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


def _parse_fixture(fixture: dict, bookmaker: str) -> OddsPapiFixtureOdds | None:
    if not fixture.get("hasOdds"):
        return None

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

    mercado = (((fixture.get("bookmakerOdds") or {}).get(bookmaker) or {}).get("markets") or {}).get(MARKET_1X2_ID)
    if not mercado or not mercado.get("marketActive", True):
        return None

    start_time = datetime.fromisoformat(start_time_raw.replace("Z", "+00:00"))

    precos: dict[str, float] = {}
    for outcome_id, selecao in OUTCOME_1X2.items():
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

    if not precos:
        return None

    return OddsPapiFixtureOdds(
        oddspapi_fixture_id=str(fixture_id),
        tournament_id=int(tournament_id),
        start_time=start_time,
        participant1_id=str(participant1_id),
        participant2_id=str(participant2_id),
        bookmaker=bookmaker,
        precos=precos,
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
