"""Camada DB-shape do relatorio de performance por fonte (Fase 6d). Le
TODO pick que passou por scripts/resolve_odds.py (tem `odd_minima`
sombra, publicado ou nao - `status in ('vinculado', 'descartado')`) com
fixture encerrada, junta o resultado em `pick_results` quando existir
(`nao_liquidavel` conta como nao liquidado, mesmo tratamento de
ausencia de linha), e agrupa via app.settlement.performance_fonte.

`sem_odd` e' contado com a MESMA granularidade de tipster/mercado que o
resto (nao so por fonte) - caso contrario, agrupar por (fonte, mercado)
ou (fonte, tipster) atribuiria o volume `sem_odd` inteiro da fonte a
CADA sub-grupo, contando o mesmo pick varias vezes.

`desde` (opcional) filtra por `fixtures.kickoff_utc` - o CLI usa isso
pro `--days N` de exibicao, e `app.settlement.performance_fonte.
sugerir_acoes` precisa de uma janela FIXA de 60 dias (spec) pra decidir
desativacao/promocao, independente do que o operador pediu pra ver.
"""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Callable, Sequence

import psycopg

from app.settlement.performance_fonte import MetricasGrupo, PickComOdd, calcular_metricas_grupo

_SQL_PICKS_COM_ODD = """
    select p.id, s.nome, p.tipster, p.mercado, pr.resultado, p.odd_minima, p.odd_citada, p.odd_referencia
    from picks p
    join fixtures f on f.id = p.fixture_id
    join raw_picks rp on rp.id = p.raw_pick_id
    join sources s on s.id = rp.source_id
    left join pick_results pr on pr.pick_id = p.id
    where p.status in ('vinculado', 'descartado')
      and f.status = 'encerrada'
      and p.odd_minima is not null
      and (%s::timestamptz is null or f.kickoff_utc >= %s::timestamptz)
"""

_SQL_VOLUME_SEM_ODD = """
    select s.nome, p.tipster, p.mercado, count(*)
    from picks p
    join fixtures f on f.id = p.fixture_id
    join raw_picks rp on rp.id = p.raw_pick_id
    join sources s on s.id = rp.source_id
    where p.status = 'sem_odd'
      and f.status = 'encerrada'
      and (%s::timestamptz is null or f.kickoff_utc >= %s::timestamptz)
    group by s.nome, p.tipster, p.mercado
"""

ChaveDe = Callable[[str, str | None, str], tuple[str, ...]]


def buscar_picks_com_odd(
    cur: psycopg.Cursor, desde: datetime | None = None
) -> list[tuple[str, str | None, str, PickComOdd]]:
    cur.execute(_SQL_PICKS_COM_ODD, (desde, desde))
    resultado = []
    for pick_id, fonte, tipster, mercado, resultado_bruto, odd_minima, odd_citada, odd_referencia in cur.fetchall():
        # 'nao_liquidavel' e ausencia de linha em pick_results contam
        # igual aqui - as duas sao "nao liquidado" pra efeito do
        # relatorio (ver docstring do modulo).
        resultado_liquidacao = resultado_bruto if resultado_bruto not in (None, "nao_liquidavel") else None
        pick = PickComOdd(
            pick_id=str(pick_id),
            resultado=resultado_liquidacao,
            odd_minima=Decimal(str(odd_minima)),
            odd_citada=Decimal(str(odd_citada)) if odd_citada is not None else None,
            odd_referencia=Decimal(str(odd_referencia)) if odd_referencia is not None else None,
        )
        resultado.append((fonte, tipster, mercado, pick))
    return resultado


def buscar_volume_sem_odd(cur: psycopg.Cursor, desde: datetime | None = None) -> list[tuple[str, str | None, str, int]]:
    cur.execute(_SQL_VOLUME_SEM_ODD, (desde, desde))
    return [(fonte, tipster, mercado, total) for fonte, tipster, mercado, total in cur.fetchall()]


def buscar_quarentena_por_fonte(cur: psycopg.Cursor) -> dict[str, bool]:
    cur.execute("select nome, quarentena from sources")
    return {nome: quarentena for nome, quarentena in cur.fetchall()}


def agrupar(
    linhas: Sequence[tuple[str, str | None, str, PickComOdd]],
    volume_sem_odd: Sequence[tuple[str, str | None, str, int]],
    chave_de: ChaveDe,
) -> list[MetricasGrupo]:
    picks_por_chave: dict[tuple[str, ...], list[PickComOdd]] = defaultdict(list)
    for fonte, tipster, mercado, pick in linhas:
        picks_por_chave[chave_de(fonte, tipster, mercado)].append(pick)

    sem_odd_por_chave: dict[tuple[str, ...], int] = defaultdict(int)
    for fonte, tipster, mercado, total in volume_sem_odd:
        sem_odd_por_chave[chave_de(fonte, tipster, mercado)] += total

    # Uniao das duas fontes de chave - um grupo pode existir so' em
    # sem_odd (uma fonte/mercado onde NENHUM pick jamais teve odd
    # resolvida) e ainda assim precisa aparecer no relatorio.
    todas_as_chaves = set(picks_por_chave) | set(sem_odd_por_chave)

    return [
        calcular_metricas_grupo(chave, picks_por_chave.get(chave, []), volume_sem_odd=sem_odd_por_chave.get(chave, 0))
        for chave in todas_as_chaves
    ]


def gerar_relatorio_por_fonte(cur: psycopg.Cursor, desde: datetime | None = None) -> list[MetricasGrupo]:
    linhas = buscar_picks_com_odd(cur, desde)
    sem_odd = buscar_volume_sem_odd(cur, desde)
    return agrupar(linhas, sem_odd, lambda fonte, tipster, mercado: (fonte,))


def gerar_relatorio_por_fonte_e_mercado(cur: psycopg.Cursor, desde: datetime | None = None) -> list[MetricasGrupo]:
    linhas = buscar_picks_com_odd(cur, desde)
    sem_odd = buscar_volume_sem_odd(cur, desde)
    return agrupar(linhas, sem_odd, lambda fonte, tipster, mercado: (fonte, mercado))


def gerar_relatorio_por_fonte_e_tipster(cur: psycopg.Cursor, desde: datetime | None = None) -> list[MetricasGrupo]:
    linhas = buscar_picks_com_odd(cur, desde)
    sem_odd = buscar_volume_sem_odd(cur, desde)
    return agrupar(linhas, sem_odd, lambda fonte, tipster, mercado: (fonte, tipster or "?"))
