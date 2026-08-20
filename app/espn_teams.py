"""Fetch e parsing do endpoint /teams da ESPN.

Achado da Fase 1c (ver CLAUDE.md): o campo de "apelido" citado no
documento original nao existe no payload real. Os campos disponiveis sao
`displayName`, `shortDisplayName`, `abbreviation`, `name` e `location` -
todos viram alias candidatos, deduplicados. Na amostra real (bra.1), a
unica divergencia relevante entre `displayName` e `shortDisplayName` foi
Vasco da Gama -> Vasco; os demais 19 times vieram com os 4 campos de nome
identicos, so `abbreviation` variando.
"""

from dataclasses import dataclass

import httpx

from app.espn_client import RATE_LIMIT_SECONDS


@dataclass(frozen=True)
class EspnTeam:
    espn_team_id: str
    nome_canonico: str
    aliases: frozenset[str]


def parse_teams_response(payload: dict) -> list[EspnTeam]:
    times: list[EspnTeam] = []
    for esporte in payload.get("sports", []):
        for liga in esporte.get("leagues", []):
            for entrada in liga.get("teams", []):
                time_espn = _parse_team(entrada.get("team", {}))
                if time_espn is not None:
                    times.append(time_espn)
    return times


def _parse_team(time: dict) -> EspnTeam | None:
    espn_team_id = time.get("id")
    display_name = time.get("displayName")
    if not espn_team_id or not display_name:
        return None

    candidatos = (
        display_name,
        time.get("shortDisplayName"),
        time.get("abbreviation"),
        time.get("name"),
        time.get("location"),
    )
    aliases = frozenset(nome for nome in candidatos if nome)
    return EspnTeam(espn_team_id=espn_team_id, nome_canonico=display_name, aliases=aliases)


def fetch_teams(client: httpx.Client, base_url: str, liga: str) -> dict:
    resp = client.get(f"{base_url}/{liga}/teams", timeout=20)
    resp.raise_for_status()
    return resp.json()
