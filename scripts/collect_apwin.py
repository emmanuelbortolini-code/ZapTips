"""Coletor do APWin Decreasing Stats (documento original, "Fonte 4:
APWin Decreasing Stats", QUARENTENA - ver app/apwin.py pro parsing).

Diferenca das outras fontes (Eagle Predict/SDA): o mercado vem da
PAGINA, nao do texto, entao esta fonte pula scripts/extract_picks.py de
proposito - grava `raw_picks` (proveniencia/dedupe, igual as outras) e
`picks` estruturado na MESMA transacao, marcando `raw_picks.extraido_em`
na hora pra `extract_picks.py` nunca reprocessar esse texto como se
fosse de tipster (queimaria credito de API pra reclassificar algo que
ja esta estruturado).

Escopo restrito a Brasileirao A/B (`LIGAS_ESCOPO`) - decisao do PM
(ver CLAUDE.md): unicas ligas com `league_map.oddspapi_tournament_id`
mapeado hoje, entao as unicas onde um pick da APWin teria chance real de
odd de referencia. Resolve fixture/time no proprio coletor (nao passa
por scripts/link_picks.py, que so processa status='extraido') via
app.matcher.match_team_name contra um team_aliases reduzido só aos
times com fixture em bra.1/bra.2 - mesmo padrao de
scripts/collect_odds.py::filtrar_aliases_relevantes. Sem match
confiavel de time OU fixture (inclusive empate sem desempate possivel
por horario) -> descarta a entrada, nunca revisao_manual (documento
original: "descartando o resto na entrada" - sem operador revisando
uma fonte em quarentena que ainda nem foi validada).

Uso:
    uv run python -m scripts.collect_apwin
"""

import hashlib
import sys
import time
from datetime import date, datetime

import httpx
import psycopg
import structlog

from app.apwin import PAGINAS, ApwinEntrada, PaginaMercado, RATE_LIMIT_SEGUNDOS, fetch_market_page, montar_texto_bruto, parse_market_page
from app.config import get_settings
from app.db import get_connection
from app.matcher import TeamAlias, match_team_name
from app.pipeline import ResultadoEtapa
from app.sources import upsert_source

log = structlog.get_logger()

NOME_FONTE = "APWin Decreasing Stats"
ENDPOINT = "https://www.apwin.com/decreasing-stats/"
LIGAS_ESCOPO = ("bra.1", "bra.2")
STAT_FONTE_TIPO = "frequencia_ultimos_jogos"

FixturaCandidata = tuple[str, str, str, datetime | None]  # home_id, away_id, fixture_id, kickoff_utc


def calcular_hash_conteudo(entrada: ApwinEntrada, pagina: PaginaMercado, texto_bruto: str) -> str:
    base = f"{entrada.match_url}:{pagina.mercado}:{texto_bruto}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def carregar_fixtures_escopo(cur: psycopg.Cursor) -> list[FixturaCandidata]:
    cur.execute(
        "select home_team_id, away_team_id, id, kickoff_utc from fixtures "
        "where liga = any(%s) and home_team_id is not null and away_team_id is not null",
        (list(LIGAS_ESCOPO),),
    )
    return [(str(h), str(a), str(fid), kickoff) for h, a, fid, kickoff in cur.fetchall()]


def carregar_aliases_relevantes(cur: psycopg.Cursor, fixtures: list[FixturaCandidata]) -> list[TeamAlias]:
    # Mesmo raciocinio de collect_odds.py::filtrar_aliases_relevantes:
    # team_aliases cobre 11 competicoes ESPN (times de base/reserva
    # incluidos) - reduzir aos times que de fato tem fixture no escopo
    # evita ambiguidade falsa (ex.: um time de outra competicao que
    # normaliza igual a um time do Brasileirao).
    times_relevantes = {team_id for home, away, _, _ in fixtures for team_id in (home, away)}
    cur.execute("select team_id, alias_normalizado from team_aliases")
    return [
        TeamAlias(team_id=str(team_id), alias_normalizado=alias)
        for team_id, alias in cur.fetchall()
        if str(team_id) in times_relevantes
    ]


def resolver_fixture_id(
    entrada: ApwinEntrada, aliases: list[TeamAlias], fixtures: list[FixturaCandidata]
) -> str | None:
    casa = match_team_name(entrada.time_casa_texto, aliases)
    fora = match_team_name(entrada.time_fora_texto, aliases)
    if casa.team_id is None or fora.team_id is None:
        return None

    candidatas = [(fid, kickoff) for home, away, fid, kickoff in fixtures if home == casa.team_id and away == fora.team_id]
    if not candidatas:
        return None
    if len(candidatas) == 1:
        return candidatas[0][0]
    if entrada.kickoff_utc is None:
        # Mais de uma fixture pro mesmo confronto (ida/volta) e sem
        # horario pra desempatar - nunca chuta.
        return None
    mais_proxima = min(candidatas, key=lambda c: abs((c[1] - entrada.kickoff_utc).total_seconds()))
    return mais_proxima[0]


def upsert_raw_pick(
    cur: psycopg.Cursor, source_id: str, entrada: ApwinEntrada, texto_bruto: str, hash_conteudo: str
) -> tuple[str, bool]:
    cur.execute(
        """
        insert into raw_picks (source_id, texto_bruto, url_origem, publicado_em, hash_conteudo, extraido_em)
        values (%s, %s, %s, %s, %s, now())
        on conflict (hash_conteudo) do nothing
        returning id
        """,
        (source_id, texto_bruto, entrada.match_url, entrada.kickoff_utc, hash_conteudo),
    )
    row = cur.fetchone()
    if row is not None:
        return row[0], True
    cur.execute("select id from raw_picks where hash_conteudo = %s", (hash_conteudo,))
    return cur.fetchone()[0], False


def inserir_pick(
    cur: psycopg.Cursor, raw_pick_id: str, entrada: ApwinEntrada, pagina: PaginaMercado, fixture_id: str
) -> None:
    data_referencia: date | None = entrada.kickoff_utc.date() if entrada.kickoff_utc else None
    cur.execute(
        """
        insert into picks (
            raw_pick_id, mercado, selecao, linha, fixture_id, status,
            stat_fonte, stat_fonte_tipo, time_casa, time_fora, competicao, data_referencia
        )
        values (%s, %s, %s, %s, %s::uuid, 'vinculado', %s, %s, %s, %s, %s, %s)
        """,
        (
            raw_pick_id, pagina.mercado, pagina.selecao, pagina.linha, fixture_id,
            entrada.percentual, STAT_FONTE_TIPO, entrada.time_casa_texto, entrada.time_fora_texto,
            entrada.liga_texto, data_referencia,
        ),
    )


def coletar_entradas(client: httpx.Client) -> list[tuple[PaginaMercado, ApwinEntrada]]:
    coletadas: list[tuple[PaginaMercado, ApwinEntrada]] = []
    for pagina in PAGINAS:
        try:
            html = fetch_market_page(client, pagina)
        except httpx.HTTPError as exc:
            log.warning("apwin_falha_ao_buscar_pagina", mercado=pagina.mercado, erro=type(exc).__name__)
            continue
        coletadas.extend((pagina, entrada) for entrada in parse_market_page(html))
        time.sleep(RATE_LIMIT_SEGUNDOS)
    return coletadas


def executar() -> ResultadoEtapa:
    with get_connection() as conn:
        with conn.cursor() as cur:
            source_id = upsert_source(cur, NOME_FONTE, "site", ENDPOINT)
            fixtures = carregar_fixtures_escopo(cur)
            aliases = carregar_aliases_relevantes(cur, fixtures)
        conn.commit()

    with httpx.Client() as client:
        pares = coletar_entradas(client)

    novos_raw = 0
    picks_criados = 0
    descartados_sem_fixture = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for pagina, entrada in pares:
                texto_bruto = montar_texto_bruto(entrada, pagina)
                hash_conteudo = calcular_hash_conteudo(entrada, pagina, texto_bruto)
                raw_pick_id, novo = upsert_raw_pick(cur, source_id, entrada, texto_bruto, hash_conteudo)
                if not novo:
                    continue
                novos_raw += 1

                fixture_id = resolver_fixture_id(entrada, aliases, fixtures)
                if fixture_id is None:
                    descartados_sem_fixture += 1
                    continue

                inserir_pick(cur, raw_pick_id, entrada, pagina, fixture_id)
                picks_criados += 1
        conn.commit()

    detalhe = {
        "entradas_coletadas": len(pares),
        "raw_picks_novos": novos_raw,
        "picks_criados": picks_criados,
        "descartados_sem_fixture_no_escopo": descartados_sem_fixture,
    }
    return ResultadoEtapa(status="ok", itens_ok=picks_criados, itens_erro=0, detalhe=detalhe)


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL vazia, abortando.")
        return 1
    resultado = executar()
    print(f"status={resultado.status} detalhe={resultado.detalhe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
