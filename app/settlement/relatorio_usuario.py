"""Camada DB-shape do relatorio de metricas por usuario (Fase 6c) - le
`bets` (ja materializado por app.settlement.extrato_usuario) + conta
`nao_liquidavel` do periodo, e entrega pro calculo puro em
app.settlement.metricas.
"""

from datetime import datetime
from decimal import Decimal

import psycopg

from app.settlement.banca import Aposta
from app.settlement.extrato_usuario import buscar_config_banca
from app.settlement.metricas import ApostaComData, Metricas, calcular_metricas

_SQL_APOSTAS_DO_USUARIO = """
    select b.pick_id, b.fixture_id, b.message_id, b.odd, b.stake_valor, b.stake_pct,
           b.resultado, b.retorno, b.banca_antes, b.banca_depois, b.sequencia, f.kickoff_utc
    from bets b
    join fixtures f on f.id = b.fixture_id
    where b.user_id = %s::uuid
    order by b.sequencia
"""

# Mesmo criterio de "efetivamente enviado" ja usado em
# app.settlement.master_ledger/extrato_usuario, escopado a este usuario
# e restrito a picks que o motor de liquidacao (Fase 6a) marcou
# nao_liquidavel - "sempre exibido junto do ROI" (spec, secao 6c), nunca
# omitido.
_SQL_NAO_LIQUIDADOS_PERIODO = """
    select count(distinct p.id)
    from messages m
    join fixtures f on f.id = m.fixture_id
    join picks p on p.fixture_id = f.id and p.id = any(m.pick_ids)
    join pick_results pr on pr.pick_id = p.id and pr.resultado = 'nao_liquidavel'
    where m.user_id = %s::uuid
      and m.status = 'enviada'
      and m.enviada_em is not null
      and m.enviada_em < f.kickoff_utc
      and (%s::timestamptz is null or f.kickoff_utc >= %s::timestamptz)
"""


def buscar_apostas_do_usuario(cur: psycopg.Cursor, user_id: str) -> list[ApostaComData]:
    cur.execute(_SQL_APOSTAS_DO_USUARIO, (user_id,))
    resultado = []
    for pick_id, fixture_id, message_id, odd, stake_valor, stake_pct, resultado_bet, retorno, banca_antes, banca_depois, sequencia, kickoff_utc in cur.fetchall():
        aposta = Aposta(
            pick_id=str(pick_id), fixture_id=str(fixture_id), message_id=str(message_id) if message_id else None,
            odd=Decimal(str(odd)), stake_valor=Decimal(str(stake_valor)), stake_pct=Decimal(str(stake_pct)),
            resultado=resultado_bet, retorno=Decimal(str(retorno)), banca_antes=Decimal(str(banca_antes)),
            banca_depois=Decimal(str(banca_depois)), sequencia=sequencia,
        )
        resultado.append(ApostaComData(aposta=aposta, kickoff_utc=kickoff_utc))
    return resultado


def contar_nao_liquidados_periodo(cur: psycopg.Cursor, user_id: str, desde: datetime | None) -> int:
    cur.execute(_SQL_NAO_LIQUIDADOS_PERIODO, (user_id, desde, desde))
    return cur.fetchone()[0]


def gerar_relatorio_usuario(cur: psycopg.Cursor, user_id: str, desde: datetime | None, settings) -> Metricas:
    todas_apostas = buscar_apostas_do_usuario(cur, user_id)
    banca_inicial, _stake_pct, _modo_stake = buscar_config_banca(cur, user_id, settings)
    nao_liquidados = contar_nao_liquidados_periodo(cur, user_id, desde)

    return calcular_metricas(
        todas_apostas, banca_inicial=banca_inicial, desde=desde, nao_liquidados_no_periodo=nao_liquidados
    )
