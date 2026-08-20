"""Camada DB-shape da pagina publica de performance (Fase 7 - spec,
"Pagina publica de performance"). Le `master_ledger` (extrato MESTRE,
Fase 6b) inteiro, simula com a banca/stake DEFAULT do produto
(`app.config`, nunca `user_bankroll_config` de um assinante) e entrega
pra `app.settlement.metricas_publicas` calcular os 3 periodos + a curva
de banca. `app.pagina_publica` renderiza o HTML/texto a partir daqui.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import psycopg

from app.settlement.banca import Aposta, EntradaLedger, ordenar_deterministico, simular_extrato
from app.settlement.metricas import ApostaComData
from app.settlement.metricas_publicas import PeriodoPublico, limites_dos_periodos, montar_curva_banca, montar_periodos_publicos

_SQL_ENTRADAS_MESTRE = """
    select ml.pick_id, ml.fixture_id, f.kickoff_utc, ml.odd, ml.resultado, ml.fator_retorno
    from master_ledger ml
    join fixtures f on f.id = ml.fixture_id
"""

# Mesmo criterio de elegibilidade de app.settlement.master_ledger
# (aprovado + efetivamente enviado a alguem + antes do kickoff), so que
# sem escopo de usuario - "nao liquidado" aqui significa "publicado e
# enviado, mas o resultado ainda nao fechou de forma limpa"
# (pr.id is null) ou "fechou ambiguo" (resultado='nao_liquidavel', que
# master_ledger.buscar_candidatos ja exclui do proprio extrato).
_SQL_NAO_LIQUIDADOS_MESTRE = """
    select count(distinct p.id)
    from messages m
    join picks p on p.id = any(m.pick_ids)
    join fixtures f on f.id = p.fixture_id
    join slate_picks sp on sp.pick_id = p.id
    join daily_slates ds on ds.id = sp.slate_id and ds.status = 'aprovado'
    left join pick_results pr on pr.pick_id = p.id
    where m.status = 'enviada' and m.enviada_em is not null and m.enviada_em < f.kickoff_utc
      and (pr.id is null or pr.resultado = 'nao_liquidavel')
      and (%s::timestamptz is null or f.kickoff_utc >= %s::timestamptz)
"""


def buscar_entradas_mestre(cur: psycopg.Cursor) -> list[EntradaLedger]:
    cur.execute(_SQL_ENTRADAS_MESTRE)
    return [
        EntradaLedger(
            pick_id=str(pick_id), fixture_id=str(fixture_id), kickoff_utc=kickoff_utc,
            odd=Decimal(str(odd)), resultado=resultado, fator_retorno=Decimal(str(fator_retorno)),
        )
        for pick_id, fixture_id, kickoff_utc, odd, resultado, fator_retorno in cur.fetchall()
    ]


def contar_nao_liquidados_mestre(cur: psycopg.Cursor, desde: datetime | None) -> int:
    cur.execute(_SQL_NAO_LIQUIDADOS_MESTRE, (desde, desde))
    return cur.fetchone()[0]


@dataclass(frozen=True)
class DadosPublicos:
    periodos: tuple[PeriodoPublico, ...]
    curva_banca: tuple[tuple[datetime | None, Decimal], ...]
    banca_inicial: Decimal
    gerado_em: datetime


def gerar_dados_publicos(cur: psycopg.Cursor, settings, agora: datetime) -> DadosPublicos:
    entradas = buscar_entradas_mestre(cur)
    banca_inicial = Decimal(str(settings.banca_inicial_padrao))
    stake_pct = Decimal(str(settings.stake_pct_padrao))
    apostas: list[Aposta] = simular_extrato(
        entradas, banca_inicial=banca_inicial, stake_pct=stake_pct, modo_stake=settings.stake_modo_padrao
    )
    # simular_extrato itera sobre ordenar_deterministico(entradas) - a
    # mesma chamada aqui reproduz exatamente essa ordem, entao
    # apostas[i] e ordenadas[i] sao garantidamente o mesmo pick.
    ordenadas = ordenar_deterministico(entradas)
    todas_apostas = [ApostaComData(aposta=a, kickoff_utc=e.kickoff_utc) for a, e in zip(apostas, ordenadas)]

    nao_liquidados_por_periodo = {
        nome: contar_nao_liquidados_mestre(cur, desde) for nome, desde in limites_dos_periodos(agora).items()
    }
    periodos = montar_periodos_publicos(
        todas_apostas, banca_inicial=banca_inicial, agora=agora, nao_liquidados_por_periodo=nao_liquidados_por_periodo
    )
    curva = montar_curva_banca(banca_inicial, todas_apostas)

    return DadosPublicos(periodos=tuple(periodos), curva_banca=tuple(curva), banca_inicial=banca_inicial, gerado_em=agora)
