"""Resumo semanal (Fase 6e) - agregacao pura por usuario sobre uma janela
de 7 dias (segunda a domingo, ver app.pipeline.segunda_da_semana_anterior),
reaproveitando `Aposta` (app.settlement.banca) sem duplicar seu contrato.
Camada DB-shape em app/resumo_semanal_generator.py.

Greens/reds da mensagem semanal sao contagem simples (spec, secao 6e:
"{{ total_palpites }} palpites, {{ greens }} greens e {{ reds }} reds"),
diferente da taxa de acerto ponderada de app.settlement.metricas
(meio_green conta 0.5) - aqui meio_green conta como green e meio_red
conta como red (decisao desta sessao, sem confirmacao do PM: simplifica
a mensagem pro assinante, que nao precisa da nuance de meio-resultado
numa contagem de "quantos bateram"). `void` fica fora dos dois lados -
nao e' nem acerto nem erro, mesma convencao ja usada em
app.settlement.banca.calcular_taxa_acerto.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from app.settlement.banca import Aposta

_GREEN = {"green", "meio_green"}
_RED = {"red", "meio_red"}


@dataclass(frozen=True)
class ResumoSemanal:
    total_palpites: int
    greens: int
    reds: int
    banca_inicial: Decimal
    banca_atual: Decimal
    roi: Decimal | None
    nao_liquidados: int


def calcular_resumo_semanal(
    apostas_da_semana: Sequence[Aposta], *, banca_no_inicio_semana: Decimal, nao_liquidados: int
) -> ResumoSemanal:
    greens = sum(1 for a in apostas_da_semana if a.resultado in _GREEN)
    reds = sum(1 for a in apostas_da_semana if a.resultado in _RED)
    banca_atual = apostas_da_semana[-1].banca_depois if apostas_da_semana else banca_no_inicio_semana

    total_apostado = sum((a.stake_valor for a in apostas_da_semana), Decimal("0"))
    retorno_total = sum((a.retorno for a in apostas_da_semana), Decimal("0"))
    roi = (retorno_total - total_apostado) / total_apostado if total_apostado != 0 else None

    return ResumoSemanal(
        total_palpites=len(apostas_da_semana),
        greens=greens,
        reds=reds,
        banca_inicial=banca_no_inicio_semana,
        banca_atual=banca_atual,
        roi=roi,
        nao_liquidados=nao_liquidados,
    )
