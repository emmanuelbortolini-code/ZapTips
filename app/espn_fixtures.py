"""Fetch e parsing do endpoint /scoreboard da ESPN.

Escopo: so agendamento (id, times por espn_team_id, kickoff, status,
estadio). Placar e placar do intervalo ficam para o job de coleta de
resultados (ver CLAUDE.md, "Proximos passos"), que le o endpoint /summary
- muito mais completo para isso - em vez do /scoreboard usado aqui.

Mapeamento de status usa `status.type.state` (pre/in/post), mais estavel
que a lista aberta de `status.type.name`. Estado "post" sem `completed`
ainda nao tem confirmacao real de como distinguir adiada/cancelada (ver
Fase 1a no CLAUDE.md) - fica marcado como ignorado, nunca mapeado por
suposicao. `wasSuspended=true` tampouco tem caso real confirmado; mesmo
tratamento.
"""

from dataclasses import dataclass
from datetime import datetime

import httpx

from app.espn_client import RATE_LIMIT_SECONDS

_STATUS_POR_STATE = {
    "pre": "agendada",
    "in": "ao_vivo",
}


@dataclass(frozen=True)
class EspnFixtureRaw:
    espn_event_id: str
    liga: str
    temporada: str | None
    home_espn_team_id: str | None
    away_espn_team_id: str | None
    kickoff_utc: datetime
    status: str
    estadio: str | None


@dataclass(frozen=True)
class EventoIgnorado:
    espn_event_id: str | None
    motivo: str
    status_raw: str | None


def map_status(status_type: dict, was_suspended: bool) -> str | None:
    if was_suspended:
        return None

    state = status_type.get("state")
    if state == "post":
        return "encerrada" if status_type.get("completed") else None

    return _STATUS_POR_STATE.get(state)


def parse_scoreboard_response(payload: dict, liga: str) -> tuple[list[EspnFixtureRaw], list[EventoIgnorado]]:
    fixtures: list[EspnFixtureRaw] = []
    ignorados: list[EventoIgnorado] = []

    for evento in payload.get("events", []):
        try:
            resultado = _parse_evento(evento, liga)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            # API interna sem contrato de estabilidade (ver CLAUDE.md): um
            # campo que normalmente e um dict pode vir como `null` explicito
            # (nao so ausente), o que quebraria os .get() encadeados em
            # _parse_evento. Isola o evento problematico em vez de derrubar
            # a coleta inteira das 11 ligas por causa de 1 payload estranho.
            ignorados.append(
                EventoIgnorado(espn_event_id=evento.get("id"), motivo="erro_parsing", status_raw=str(exc))
            )
            continue

        if isinstance(resultado, EspnFixtureRaw):
            fixtures.append(resultado)
        else:
            ignorados.append(resultado)

    return fixtures, ignorados


def _parse_evento(evento: dict, liga: str) -> EspnFixtureRaw | EventoIgnorado:
    espn_event_id = evento.get("id")
    data_iso = evento.get("date")
    competicoes = evento.get("competitions") or []

    if not espn_event_id or not data_iso or not competicoes:
        return EventoIgnorado(espn_event_id=espn_event_id, motivo="payload_incompleto", status_raw=None)

    competicao = competicoes[0]
    status_type = competicao.get("status", {}).get("type", {})
    was_suspended = bool(competicao.get("wasSuspended", False))
    status = map_status(status_type, was_suspended)

    if status is None:
        return EventoIgnorado(
            espn_event_id=espn_event_id,
            motivo="status_nao_reconhecido",
            status_raw=status_type.get("name"),
        )

    return EspnFixtureRaw(
        espn_event_id=espn_event_id,
        liga=liga,
        temporada=evento.get("season", {}).get("slug"),
        home_espn_team_id=_time_por_lado(competicao, "home"),
        away_espn_team_id=_time_por_lado(competicao, "away"),
        kickoff_utc=datetime.fromisoformat(data_iso.replace("Z", "+00:00")),
        status=status,
        estadio=competicao.get("venue", {}).get("fullName"),
    )


def _time_por_lado(competicao: dict, lado: str) -> str | None:
    for competidor in competicao.get("competitors", []):
        if competidor.get("homeAway") == lado:
            return competidor.get("team", {}).get("id")
    return None


def fetch_scoreboard(client: httpx.Client, base_url: str, liga: str, yyyymmdd: str) -> dict:
    resp = client.get(f"{base_url}/{liga}/scoreboard", params={"dates": yyyymmdd}, timeout=20)
    resp.raise_for_status()
    return resp.json()
