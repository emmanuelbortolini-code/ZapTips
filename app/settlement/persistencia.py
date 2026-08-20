"""Camada DB-shape do motor de liquidacao (Fase 6a) - le picks vinculados
ou descartados (Fase 6d, ver `_SQL_PENDENTES`) com fixture encerrada e
grava o resultado em `pick_results` (tabela que
existe desde a Fase 0, ja usada pela metrica "encerradas_sem_liquidacao"
do console - `app/console/queries.py`). Achado do code-reviewer: uma
primeira versao desta sessao criou uma tabela nova, `pick_liquidacoes`,
sem notar que `pick_results` ja cobria exatamente esse papel - revertida
em migrations/0024_drop_pick_liquidacoes.sql.

`pick_results.resultado` aceita `nao_liquidavel` (CHECK da migration
0001) - diferente da tentativa anterior desta sessao, um pick SEMPRE
ganha uma linha aqui assim que o motor tenta liquida-lo, mesmo quando o
resultado e' `nao_liquidavel`. Isso bate com o design ja existente:
`encerradas_sem_liquidacao` mede "o pipeline ainda nem tentou" (ausencia
de linha), e `revisado_por_humano` mede "um humano corrigiu depois" -
duas perguntas diferentes, cada uma com seu proprio sinal.
"""

import json
from collections.abc import Sequence
from decimal import Decimal
from typing import NamedTuple

import psycopg

from app.settlement.engine import FixtureEncerrada, FixtureStatTime, PickParaLiquidar, Resolution

_SQL_PENDENTES = """
    select p.id, p.mercado, p.selecao, p.linha, p.time_casa, p.time_fora, p.fixture_id,
           f.status, f.placar_casa, f.placar_fora
    from picks p
    join fixtures f on f.id = p.fixture_id
    left join pick_results pr on pr.pick_id = p.id
    where p.status in ('vinculado', 'descartado')
      and f.status = 'encerrada'
      and pr.id is null
"""
# 'descartado' entra desde a Fase 6d ("todos os palpites liquidados,
# publicados ou nao... palpites cortados por conflito e... que o filtro
# de piso rejeitou") - um pick so vira 'descartado' depois de ja ter
# passado por 'vinculado' (piso: scripts/resolve_odds.py; conflito:
# app.slate/app.console.acoes), entao sempre tem fixture_id resolvido.
# 'sem_odd' fica de fora de proposito - sem odd nenhuma, nao ha o que
# comparar contra pra reportar ROI (a spec conta esse volume separado,
# nunca tenta liquida-lo). 'revisao_manual' tambem fica de fora - e' um
# empate de conflito ainda sem uma unica selecao definida pra liquidar.


def buscar_picks_pendentes(cur: psycopg.Cursor) -> list[tuple[PickParaLiquidar, FixtureEncerrada]]:
    cur.execute(_SQL_PENDENTES)
    pares = []
    for row in cur.fetchall():
        pick_id, mercado, selecao, linha, time_casa, time_fora, fixture_id, status, placar_casa, placar_fora = row
        pick = PickParaLiquidar(
            pick_id=str(pick_id),
            mercado=mercado,
            selecao=selecao,
            linha=Decimal(str(linha)) if linha is not None else None,
            time_casa=time_casa,
            time_fora=time_fora,
        )
        fixture = FixtureEncerrada(
            fixture_id=str(fixture_id), status=status, placar_casa=placar_casa, placar_fora=placar_fora
        )
        pares.append((pick, fixture))
    return pares


def buscar_stats_por_fixture(cur: psycopg.Cursor, fixture_ids: Sequence[str]) -> dict[str, list[FixtureStatTime]]:
    # Busca em lote (nao 1 query por fixture) - mesmo cuidado de N+1 ja
    # aplicado no resto do projeto (ex.: app.odds_resolution carrega
    # odds_referencia inteira de uma vez, nao por pick).
    if not fixture_ids:
        return {}
    cur.execute(
        "select fixture_id, escanteios, cartoes_amarelos, cartoes_vermelhos "
        "from fixture_stats where fixture_id = any(%s::uuid[])",
        (list(fixture_ids),),
    )
    stats: dict[str, list[FixtureStatTime]] = {}
    for fixture_id, escanteios, amarelos, vermelhos in cur.fetchall():
        stats.setdefault(str(fixture_id), []).append(
            FixtureStatTime(escanteios=escanteios, cartoes_amarelos=amarelos, cartoes_vermelhos=vermelhos)
        )
    return stats


def gravar_resultado(
    cur: psycopg.Cursor,
    pick_id: str,
    fixture_id: str,
    resolution: Resolution,
    *,
    resolver: str,
    revisado_por_humano: bool = False,
) -> None:
    cur.execute(
        """
        insert into pick_results (pick_id, fixture_id, resultado, resolver, evidencia_json, liquidado_em, revisado_por_humano)
        values (%s::uuid, %s::uuid, %s, %s, %s::jsonb, now(), %s)
        on conflict (pick_id) do update set
            resultado = excluded.resultado,
            resolver = excluded.resolver,
            evidencia_json = excluded.evidencia_json,
            liquidado_em = excluded.liquidado_em,
            revisado_por_humano = excluded.revisado_por_humano
        """,
        (pick_id, fixture_id, resolution.resultado, resolver, json.dumps(resolution.evidencia), revisado_por_humano),
    )


def gravar_revisao_manual(cur: psycopg.Cursor, pick_id: str, fixture_id: str, resultado: str, motivo: str) -> None:
    resolution = Resolution(resultado, {"motivo": "revisao_manual", "detalhe": motivo})
    gravar_resultado(cur, pick_id, fixture_id, resolution, resolver="revisao_manual", revisado_por_humano=True)


class PendenteRevisao(NamedTuple):
    pick_id: str
    fixture_id: str
    mercado: str
    selecao: str
    motivo: str | None


def listar_pendentes_revisao(cur: psycopg.Cursor) -> list[PendenteRevisao]:
    # nao_liquidavel sempre ganha uma linha em pick_results (ver
    # docstring do modulo) - a fila de revisao e' so um filtro sobre ela,
    # nao um recalculo ao vivo do motor.
    cur.execute(
        """
        select p.id, pr.fixture_id, p.mercado, p.selecao, pr.evidencia_json ->> 'motivo'
        from pick_results pr
        join picks p on p.id = pr.pick_id
        where pr.resultado = 'nao_liquidavel' and pr.revisado_por_humano = false
        """
    )
    return [
        PendenteRevisao(pick_id=str(row[0]), fixture_id=str(row[1]), mercado=row[2], selecao=row[3], motivo=row[4])
        for row in cur.fetchall()
    ]
