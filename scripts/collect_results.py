"""Fecha partidas passadas: busca fixtures que ainda nao estao encerradas
mas ja tiveram tempo de sobra para terminar, le o /summary e grava
placar final, placar do intervalo e estatisticas por time.

Idempotente por construcao: a query so seleciona fixtures com
`status != 'encerrada'`, entao uma partida que ja foi fechada em uma
execucao anterior nao e reprocessada na proxima (nao precisa de estado
externo). `fixture_stats` tambem tem upsert via ON CONFLICT (migration
0003), para o caso raro de rodar 2x antes do status virar `encerrada` no
banco.

Job pensado para rodar a cada 30 minutos (agendamento real fica para a
Fase 7, com APScheduler - por enquanto e so mais um comando manual).

Uso:
    uv run python -m scripts.collect_results
"""

import sys
import time

import httpx
import psycopg
import structlog

from app.config import get_settings
from app.db import get_connection
from app.espn_summary import RATE_LIMIT_SECONDS, EspnMatchResult, EspnTeamStats, fetch_summary, parse_summary_response
from app.pipeline import ResultadoEtapa

log = structlog.get_logger()

# Nao confundir com settings.antecedencia_minima_horas (Fase 5/7: janela
# minima antes do KICKOFF para a mensagem entrar no envio). Esta constante
# e sobre o outro lado da partida: quanto tempo esperar DEPOIS do kickoff
# antes de tentar fechar o resultado. Mesmo valor hoje por coincidencia,
# nao por serem o mesmo conceito.
HORAS_APOS_KICKOFF_PARA_FECHAR = 2


def atualizar_fixture(cur: psycopg.Cursor, fixture_id: str, resultado: EspnMatchResult) -> None:
    cur.execute(
        """
        update fixtures set
            status = %s,
            placar_casa = %s,
            placar_fora = %s,
            placar_ht_casa = %s,
            placar_ht_fora = %s,
            encerrado_em = case when %s = 'encerrada' then now() else encerrado_em end,
            atualizado_em = now()
        where id = %s
        """,
        (
            resultado.status,
            resultado.placar_casa,
            resultado.placar_fora,
            resultado.placar_ht_casa,
            resultado.placar_ht_fora,
            resultado.status,
            fixture_id,
        ),
    )


def upsert_fixture_stat(cur: psycopg.Cursor, fixture_id: str, time_id: str, stat: EspnTeamStats) -> None:
    cur.execute(
        """
        insert into fixture_stats (
            fixture_id, time_id, escanteios, cartoes_amarelos, cartoes_vermelhos, finalizacoes, posse, origem
        )
        values (%s, %s, %s, %s, %s, %s, %s, 'espn')
        on conflict (fixture_id, time_id) do update set
            escanteios = excluded.escanteios,
            cartoes_amarelos = excluded.cartoes_amarelos,
            cartoes_vermelhos = excluded.cartoes_vermelhos,
            finalizacoes = excluded.finalizacoes,
            posse = excluded.posse,
            coletado_em = now()
        """,
        (
            fixture_id,
            time_id,
            stat.escanteios,
            stat.cartoes_amarelos,
            stat.cartoes_vermelhos,
            stat.finalizacoes,
            stat.posse,
        ),
    )


def processar_resultado(
    cur: psycopg.Cursor,
    fixture_id: str,
    resultado: EspnMatchResult,
    stats: list[EspnTeamStats],
    team_id_by_espn_id: dict[str, str],
) -> int:
    atualizar_fixture(cur, fixture_id, resultado)

    gravados = 0
    for stat in stats:
        time_id = team_id_by_espn_id.get(stat.espn_team_id)
        if time_id is None:
            log.warning(
                "time_nao_encontrado_stats",
                espn_event_id=stat.espn_event_id,
                espn_team_id=stat.espn_team_id,
            )
            continue
        upsert_fixture_stat(cur, fixture_id, time_id, stat)
        gravados += 1

    return gravados


def buscar_fixtures_elegiveis(cur: psycopg.Cursor) -> list[tuple[str, str, str]]:
    cur.execute(
        """
        select id, espn_event_id, liga
        from fixtures
        where status != 'encerrada'
          and kickoff_utc < now() - make_interval(hours => %s)
        """,
        (HORAS_APOS_KICKOFF_PARA_FECHAR,),
    )
    return cur.fetchall()


def executar() -> ResultadoEtapa:
    # Extraido de main() (Fase 7, agendador precisa chamar isso a cada
    # 30min programaticamente, mesmo padrao executar()/main() ja usado
    # no resto do projeto).
    #
    # Fase de rede (lenta, 1 req/s) e fase de escrita ficam separadas -
    # mesmo padrao do collect_fixtures.py. Segurar uma transacao aberta
    # durante o loop inteiro de chamadas rate-limited significa que, se
    # uma fixture no meio do lote falhar, o rollback joga fora o trabalho
    # de rede ja feito (e ja pago em tempo) de todas as anteriores.
    settings = get_settings()
    with get_connection() as conn:
        with conn.cursor() as cur:
            elegiveis = buscar_fixtures_elegiveis(cur)
            cur.execute("select espn_team_id, id from teams where espn_team_id is not null")
            team_id_by_espn_id = {espn_id: str(team_id) for espn_id, team_id in cur.fetchall()}

    print(f"{len(elegiveis)} fixture(s) elegivel(is) para fechamento.")

    resultados: list[tuple[str, EspnMatchResult, list[EspnTeamStats]]] = []
    ignoradas = 0
    with httpx.Client() as client:
        for fixture_id, espn_event_id, liga in elegiveis:
            try:
                payload = fetch_summary(client, settings.espn_base_url, liga, espn_event_id)
            except httpx.HTTPError as exc:
                log.warning("falha_ao_buscar_summary", espn_event_id=espn_event_id, liga=liga, erro=str(exc))
                time.sleep(RATE_LIMIT_SECONDS)
                continue

            resultado, stats, ignorado = parse_summary_response(payload)
            if ignorado is not None:
                log.warning(
                    "evento_ignorado",
                    espn_event_id=ignorado.espn_event_id,
                    motivo=ignorado.motivo,
                    status_raw=ignorado.status_raw,
                )
                ignoradas += 1
                time.sleep(RATE_LIMIT_SECONDS)
                continue

            resultados.append((fixture_id, resultado, stats))
            time.sleep(RATE_LIMIT_SECONDS)

    fechadas = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for fixture_id, resultado, stats in resultados:
                processar_resultado(cur, fixture_id, resultado, stats, team_id_by_espn_id)
                if resultado.status == "encerrada":
                    fechadas += 1
        conn.commit()

    print(f"Fixtures fechadas: {fechadas} | ignoradas: {ignoradas} | total processado: {len(elegiveis)}")
    return ResultadoEtapa(
        status="ok", itens_ok=fechadas, itens_erro=ignoradas,
        detalhe={"elegiveis": len(elegiveis), "fechadas": fechadas, "ignoradas": ignoradas},
    )


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL vazia, abortando.")
        return 1

    executar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
