"""Parsing do endpoint /summary da ESPN: placar final, placar do intervalo
e estatisticas por time (escanteios, cartoes, finalizacoes, posse).

Reusa `map_status` e `EventoIgnorado` de app.espn_fixtures - mesmo formato
de status (`status.type.state`/`completed`) e mesma politica de nunca
mapear adiada/cancelada por suposicao.

Placar e estatisticas so sao extraidos quando a partida esta de fato
`encerrada`. Uma partida `ao_vivo` tem placar e stats parciais que ainda
vao mudar; gravar isso como se fosse definitivo seria o mesmo erro que a
politica de status ja evita para adiada/cancelada.
"""

from dataclasses import dataclass

import httpx

from app.espn_client import RATE_LIMIT_SECONDS
from app.espn_fixtures import EventoIgnorado, map_status

_ESTATISTICAS_RELEVANTES = {
    "wonCorners": "escanteios",
    "yellowCards": "cartoes_amarelos",
    "redCards": "cartoes_vermelhos",
    "totalShots": "finalizacoes",
    "possessionPct": "posse",
}


@dataclass(frozen=True)
class EspnMatchResult:
    espn_event_id: str
    status: str
    placar_casa: int | None
    placar_fora: int | None
    placar_ht_casa: int | None
    placar_ht_fora: int | None


@dataclass(frozen=True)
class EspnTeamStats:
    espn_event_id: str
    espn_team_id: str
    escanteios: int | None
    cartoes_amarelos: int | None
    cartoes_vermelhos: int | None
    finalizacoes: int | None
    posse: float | None


ParseResult = tuple[EspnMatchResult | None, list[EspnTeamStats], EventoIgnorado | None]


def parse_summary_response(payload: dict) -> ParseResult:
    header = payload.get("header") or {}
    espn_event_id = header.get("id")
    competicoes = header.get("competitions") or []

    if not espn_event_id or not competicoes:
        return None, [], EventoIgnorado(espn_event_id=espn_event_id, motivo="payload_incompleto", status_raw=None)

    try:
        return _parse(payload, espn_event_id, competicoes[0])
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        return None, [], EventoIgnorado(espn_event_id=espn_event_id, motivo="erro_parsing", status_raw=str(exc))


def _parse(payload: dict, espn_event_id: str, competicao: dict) -> ParseResult:
    status_type = (competicao.get("status") or {}).get("type") or {}
    was_suspended = bool(competicao.get("wasSuspended", False))
    status = map_status(status_type, was_suspended)

    if status is None:
        return None, [], EventoIgnorado(
            espn_event_id=espn_event_id, motivo="status_nao_reconhecido", status_raw=status_type.get("name")
        )

    if status != "encerrada":
        resultado = EspnMatchResult(
            espn_event_id=espn_event_id,
            status=status,
            placar_casa=None,
            placar_fora=None,
            placar_ht_casa=None,
            placar_ht_fora=None,
        )
        return resultado, [], None

    placar_casa = placar_fora = placar_ht_casa = placar_ht_fora = None
    for competidor in competicao.get("competitors") or []:
        score = _to_int(competidor.get("score"))
        ht = _placar_ht(competidor)
        if competidor.get("homeAway") == "home":
            placar_casa, placar_ht_casa = score, ht
        elif competidor.get("homeAway") == "away":
            placar_fora, placar_ht_fora = score, ht

    resultado = EspnMatchResult(
        espn_event_id=espn_event_id,
        status=status,
        placar_casa=placar_casa,
        placar_fora=placar_fora,
        placar_ht_casa=placar_ht_casa,
        placar_ht_fora=placar_ht_fora,
    )

    # Um placar final ja valido nao pode ser descartado por causa de um
    # problema so no bloco de estatisticas (achado real: "statistics": null
    # explicito em boxscore.teams[i] quebrava o parsing inteiro do evento,
    # jogando fora um resultado que ja estava correto). Falha aqui vira
    # stats vazias, nunca EventoIgnorado.
    try:
        stats = _parse_stats(payload, espn_event_id)
    except (AttributeError, KeyError, TypeError, ValueError):
        stats = []

    return resultado, stats, None


def _placar_ht(competidor: dict) -> int | None:
    linescores = competidor.get("linescores") or []
    if not linescores:
        return None
    return _to_int(linescores[0].get("displayValue"))


def _parse_stats(payload: dict, espn_event_id: str) -> list[EspnTeamStats]:
    times = (payload.get("boxscore") or {}).get("teams") or []
    stats: list[EspnTeamStats] = []

    for entrada in times:
        espn_team_id = (entrada.get("team") or {}).get("id")
        if not espn_team_id:
            continue

        valores = {
            campo: stat.get("displayValue")
            for stat in entrada.get("statistics") or []
            if (campo := _ESTATISTICAS_RELEVANTES.get(stat.get("name")))
        }
        stats.append(
            EspnTeamStats(
                espn_event_id=espn_event_id,
                espn_team_id=espn_team_id,
                escanteios=_to_int(valores.get("escanteios")),
                cartoes_amarelos=_to_int(valores.get("cartoes_amarelos")),
                cartoes_vermelhos=_to_int(valores.get("cartoes_vermelhos")),
                finalizacoes=_to_int(valores.get("finalizacoes")),
                posse=_to_float(valores.get("posse")),
            )
        )

    return stats


def _to_int(valor: object) -> int | None:
    if valor is None:
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _to_float(valor: object) -> float | None:
    if valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def fetch_summary(client: httpx.Client, base_url: str, liga: str, espn_event_id: str) -> dict:
    resp = client.get(f"{base_url}/{liga}/summary", params={"event": espn_event_id}, timeout=20)
    resp.raise_for_status()
    return resp.json()
