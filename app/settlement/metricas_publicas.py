"""Metricas da pagina publica de performance (Fase 7) - reaproveita
`app.settlement.metricas.calcular_metricas` (Fase 6c) sobre o extrato
MESTRE (`master_ledger`, simulado com a banca/stake DEFAULT do produto,
nunca a config de um assinante individual - spec: "Essa pagina usa o
extrato mestre completo, nunca o de um assinante. Nao exponha dado
individual").

Nao duplica a formula de ROI/taxa de acerto/drawdown - so decide QUAIS
tres periodos mostrar (spec: "Quebra por periodo: 7 dias, 30 dias, desde
o inicio") e monta a curva de banca ponto a ponto pro grafico da pagina.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Mapping, Sequence

from app.settlement.metricas import ApostaComData, Metricas, calcular_metricas


@dataclass(frozen=True)
class PeriodoPublico:
    nome: str
    metricas: Metricas


def montar_curva_banca(
    banca_inicial: Decimal, todas_apostas: Sequence[ApostaComData]
) -> list[tuple[datetime | None, Decimal]]:
    # Primeiro ponto (kickoff=None) e' o inicio da operacao, banca
    # inicial - mesma convencao ja usada internamente por
    # app.settlement.metricas._drawdown_maximo_e_recuperacao pra curva.
    return [(None, banca_inicial)] + [(a.kickoff_utc, a.aposta.banca_depois) for a in todas_apostas]


# Nomes usados como chave em `nao_liquidados_por_periodo` (o chamador
# DB-shape busca a contagem de cada um separadamente, ver
# app.relatorio_publico) - centralizados aqui pra nao divergir entre
# quem gera os periodos e quem busca os dados pra eles.
NOME_7_DIAS = "7 dias"
NOME_30_DIAS = "30 dias"
NOME_DESDE_O_INICIO = "Desde o início"


def limites_dos_periodos(agora: datetime) -> dict[str, datetime | None]:
    return {
        NOME_7_DIAS: agora - timedelta(days=7),
        NOME_30_DIAS: agora - timedelta(days=30),
        NOME_DESDE_O_INICIO: None,
    }


def montar_periodos_publicos(
    todas_apostas: Sequence[ApostaComData],
    *,
    banca_inicial: Decimal,
    agora: datetime,
    nao_liquidados_por_periodo: Mapping[str, int],
) -> list[PeriodoPublico]:
    periodos = []
    for nome, desde in limites_dos_periodos(agora).items():
        metricas = calcular_metricas(
            todas_apostas, banca_inicial=banca_inicial, desde=desde,
            nao_liquidados_no_periodo=nao_liquidados_por_periodo[nome],
        )
        periodos.append(PeriodoPublico(nome=nome, metricas=metricas))
    return periodos
