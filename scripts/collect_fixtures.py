"""Coleta fixtures dos proximos 7 dias para as ligas do lancamento.

Idempotente: `fixtures.espn_event_id` e unico desde a migration 0001,
entao rodar de novo atualiza a partida ja existente (status, estadio,
horario, times) em vez de duplicar linha. UA default do httpx, rate limit
de 1 requisicao por segundo entre chamadas (uma por liga por dia) - mesmas
decisoes ja registradas no CLAUDE.md (Fase 1a).

Escopo: so agendamento. Placar e placar do intervalo ficam para o job de
coleta de resultados, que ainda nao existe (ver CLAUDE.md, "Proximos
passos") - ele le o /summary, muito mais completo para isso do que o
/scoreboard usado aqui.

Uso:
    uv run python -m scripts.collect_fixtures
"""

import sys
import time
from datetime import date, timedelta

import httpx
import psycopg
import structlog

from app.config import get_settings
from app.db import get_connection
from app.espn_fixtures import RATE_LIMIT_SECONDS, EspnFixtureRaw, fetch_scoreboard, parse_scoreboard_response
from app.ligas import LIGAS
from app.pipeline import ResultadoEtapa

log = structlog.get_logger()

DIAS_JANELA = 7


def _resolver_time(
    raw: EspnFixtureRaw, espn_team_id: str | None, lado: str, team_id_by_espn_id: dict[str, str]
) -> str | None:
    if not espn_team_id:
        return None

    team_id = team_id_by_espn_id.get(espn_team_id)
    if team_id is None:
        log.warning(
            "time_nao_encontrado",
            espn_event_id=raw.espn_event_id,
            liga=raw.liga,
            lado=lado,
            espn_team_id=espn_team_id,
        )
    return team_id


def upsert_fixture(
    cur: psycopg.Cursor, raw: EspnFixtureRaw, team_id_by_espn_id: dict[str, str]
) -> tuple[str, bool]:
    cur.execute("select id from fixtures where espn_event_id = %s", (raw.espn_event_id,))
    ja_existia = cur.fetchone() is not None

    home_team_id = _resolver_time(raw, raw.home_espn_team_id, "home", team_id_by_espn_id)
    away_team_id = _resolver_time(raw, raw.away_espn_team_id, "away", team_id_by_espn_id)

    cur.execute(
        """
        insert into fixtures (
            espn_event_id, liga, temporada, home_team_id, away_team_id,
            kickoff_utc, status, estadio, atualizado_em
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, now())
        on conflict (espn_event_id) do update set
            liga = excluded.liga,
            temporada = excluded.temporada,
            home_team_id = excluded.home_team_id,
            away_team_id = excluded.away_team_id,
            kickoff_utc = excluded.kickoff_utc,
            status = excluded.status,
            estadio = excluded.estadio,
            atualizado_em = now()
        returning id
        """,
        (
            raw.espn_event_id,
            raw.liga,
            raw.temporada,
            home_team_id,
            away_team_id,
            raw.kickoff_utc,
            raw.status,
            raw.estadio,
        ),
    )
    fixture_id = cur.fetchone()[0]
    return fixture_id, not ja_existia


def buscar_fixtures_da_janela() -> tuple[list[EspnFixtureRaw], int]:
    settings = get_settings()
    todas: list[EspnFixtureRaw] = []
    ignorados_total = 0
    datas = [(date.today() + timedelta(days=i)).strftime("%Y%m%d") for i in range(DIAS_JANELA)]

    with httpx.Client() as client:
        for liga in LIGAS:
            for yyyymmdd in datas:
                try:
                    payload = fetch_scoreboard(client, settings.espn_base_url, liga, yyyymmdd)
                except httpx.HTTPError as exc:
                    log.warning("falha_ao_buscar_scoreboard", liga=liga, data=yyyymmdd, erro=str(exc))
                    time.sleep(RATE_LIMIT_SECONDS)
                    continue

                fixtures, ignorados = parse_scoreboard_response(payload, liga)
                for evento_ignorado in ignorados:
                    log.warning(
                        "evento_ignorado",
                        liga=liga,
                        data=yyyymmdd,
                        espn_event_id=evento_ignorado.espn_event_id,
                        motivo=evento_ignorado.motivo,
                        status_raw=evento_ignorado.status_raw,
                    )
                ignorados_total += len(ignorados)
                todas.extend(fixtures)
                time.sleep(RATE_LIMIT_SECONDS)

    return todas, ignorados_total


def executar() -> ResultadoEtapa:
    todas_fixtures, ignorados_total = buscar_fixtures_da_janela()

    novas = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select espn_team_id, id from teams where espn_team_id is not null")
            team_id_by_espn_id = {espn_id: str(team_id) for espn_id, team_id in cur.fetchall()}

            for raw in todas_fixtures:
                _, nova = upsert_fixture(cur, raw, team_id_by_espn_id)
                novas += int(nova)

            # "falhou" (Fase 5a, etapa que aborta o run) so quando o
            # resultado liquido e zero fixtures conhecidas na janela de
            # 72h que o resto do pipeline depende - nao quando esta
            # execucao especifica nao trouxe novidade (fixtures ja
            # coletadas ontem continuam validas). Um apagao parcial da
            # ESPN (algumas ligas 403) fica "ok" com itens_erro > 0,
            # nao aborta o run.
            cur.execute("select count(*) from fixtures where kickoff_utc between now() and now() + interval '72 hours'")
            fixtures_nas_72h = cur.fetchone()[0]
        conn.commit()

    atualizadas = len(todas_fixtures) - novas
    detalhe = {"novas": novas, "atualizadas": atualizadas, "ignorados": ignorados_total}
    status = "falhou" if fixtures_nas_72h == 0 else "ok"
    return ResultadoEtapa(status=status, itens_ok=novas, itens_erro=ignorados_total, detalhe=detalhe)


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL vazia, abortando.")
        return 1

    print(f"Buscando fixtures dos proximos {DIAS_JANELA} dias para {len(LIGAS)} ligas...")
    resultado = executar()
    print(
        f"Fixtures novas: {resultado.detalhe['novas']} | atualizadas: {resultado.detalhe['atualizadas']} "
        f"| ignoradas: {resultado.detalhe['ignorados']}"
    )
    if resultado.status == "falhou":
        print("ALERTA: nenhuma fixture nas proximas 72h no banco - ESPN pode estar indisponivel.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
