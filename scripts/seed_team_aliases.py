"""Popula teams e team_aliases a partir do endpoint /teams da ESPN.

Idempotente: roda quantas vezes precisar sem duplicar time nem alias.
`teams.espn_team_id` e unico desde a migration 0001; `team_aliases(team_id,
alias_normalizado)` e unico desde a 0002, feita para este script poder usar
upsert. UA default do httpx (sem customizacao) e rate limit de 1
requisicao por segundo entre ligas - decisoes ja registradas no CLAUDE.md
(Fase 1a).

Uso:
    uv run python -m scripts.seed_team_aliases
"""

import sys
import time

import httpx
import psycopg
import structlog

from app.config import get_settings
from app.db import get_connection
from app.espn_teams import RATE_LIMIT_SECONDS, EspnTeam, fetch_teams, parse_teams_response
from app.ligas import LIGAS
from app.matcher import normalize_team_name

log = structlog.get_logger()


def upsert_team(cur: psycopg.Cursor, time_espn: EspnTeam) -> tuple[str, bool]:
    cur.execute(
        """
        insert into teams (nome_canonico, espn_team_id)
        values (%s, %s)
        on conflict (espn_team_id) do nothing
        returning id
        """,
        (time_espn.nome_canonico, time_espn.espn_team_id),
    )
    row = cur.fetchone()
    if row is not None:
        return row[0], True

    cur.execute("select id from teams where espn_team_id = %s", (time_espn.espn_team_id,))
    return cur.fetchone()[0], False


def upsert_alias(cur: psycopg.Cursor, team_id: str, alias: str) -> bool:
    cur.execute(
        """
        insert into team_aliases (team_id, alias, alias_normalizado, fonte, confianca)
        values (%s, %s, %s, 'espn', 1.0)
        on conflict (team_id, alias_normalizado) do nothing
        returning id
        """,
        (team_id, alias, normalize_team_name(alias)),
    )
    return cur.fetchone() is not None


def seed(conn: psycopg.Connection, times: list[EspnTeam]) -> tuple[int, int]:
    times_novos = 0
    aliases_novos = 0
    with conn.cursor() as cur:
        for time_espn in times:
            team_id, inserido = upsert_team(cur, time_espn)
            times_novos += int(inserido)
            for alias in time_espn.aliases:
                if upsert_alias(cur, team_id, alias):
                    aliases_novos += 1
    conn.commit()
    return times_novos, aliases_novos


def buscar_todos_os_times() -> list[EspnTeam]:
    settings = get_settings()
    todos: list[EspnTeam] = []
    with httpx.Client() as client:
        for liga in LIGAS:
            print(f"Buscando times de {liga}...")
            try:
                payload = fetch_teams(client, settings.espn_base_url, liga)
            except httpx.HTTPError as exc:
                log.warning("falha_ao_buscar_times", liga=liga, erro=str(exc))
                time.sleep(RATE_LIMIT_SECONDS)
                continue
            times_liga = parse_teams_response(payload)
            print(f"  -> {len(times_liga)} time(s)")
            todos.extend(times_liga)
            time.sleep(RATE_LIMIT_SECONDS)
    return todos


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL vazia, abortando.")
        return 1

    todos_times = buscar_todos_os_times()

    with get_connection() as conn:
        times_novos, aliases_novos = seed(conn, todos_times)

    print(
        f"\nTimes processados: {len(todos_times)} | "
        f"times novos: {times_novos} | aliases novos: {aliases_novos}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
