"""Metricas de extrato por usuario e periodo (Fase 6c) - funcao pura,
opera sobre `Aposta` (app.settlement.banca) ja calculadas, sem tocar
Postgres. Camada DB-shape em app.settlement.relatorio_usuario.

Regra dura da spec (secao 6c): "Se 20% dos palpites ficaram sem liquidar
e voce mostra o ROI dos 80% restantes, o numero esta viesado... Exiba
os dois juntos ou nao exiba nenhum." `Metricas.nao_liquidados_no_periodo`
e' sempre calculado e sempre exposto junto do ROI - nunca um sem o outro.

Decisoes desta sessao, sem confirmacao com o PM (documentadas aqui pra
nao virarem suposicao silenciosa):

- **Taxa de acerto exclui `void`** do numerador E do denominador - void
  devolve o stake sem nenhum risco assumido, nao e' nem acerto nem erro
  (convencao padrao de mercado de apostas). `meio_green` conta 0.5 no
  numerador e 1 no denominador (partial win, mas o denominador conta
  como aposta decidida); `meio_red` conta 0 no numerador e 1 no
  denominador. So a spec confirma "meio-green como 0,5"; o resto (void
  fora, meio_red no denominador) e' extrapolacao razoavel, nao literal.
- **Drawdown maximo em valor absoluto (R$), nao percentual** - consistente
  com `banca_atual`/`variacao_absoluta` ja serem money-denominated;
  percentual e' so dividir pelo pico depois, se um dia precisar.
- **Sequencia atual generaliza pra qualquer resultado, nao so
  green/red** - a spec fala "sequencia atual de greens ou reds", mas
  contar sequencia de `meio_green`/`meio_red`/`void` repetidos e' mais
  informativo e nao contradiz o pedido, so' generaliza.
- **Sequencia atual e' global, nunca recortada pro periodo** (achado do
  code-reviewer) - mesma logica de `banca_atual`: uma sequencia e'
  estado do "agora", nao um fluxo dentro da janela de `--periodo 7d/30d`.
  Recortar mostraria "3x green" pra alguem cuja sequencia real e' 10,
  so' porque os primeiros 7 greens ficaram fora da janela pedida.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from app.settlement.banca import Aposta, Resultado, calcular_taxa_acerto


@dataclass(frozen=True)
class ApostaComData:
    # Aposta (banca.py) nao carrega kickoff_utc - simular_extrato nao
    # precisa dele depois de ordenar. Metricas precisa, pra filtrar por
    # janela (7d/30d) e pra medir tempo de recuperacao do drawdown.
    aposta: Aposta
    kickoff_utc: datetime


@dataclass(frozen=True)
class Metricas:
    banca_atual: Decimal
    variacao_absoluta: Decimal
    variacao_percentual: Decimal | None
    total_apostado: Decimal
    lucro: Decimal
    roi: Decimal | None
    taxa_acerto: Decimal | None
    odd_media: Decimal | None
    drawdown_maximo: Decimal
    dias_para_recuperar: int | None
    sequencia_atual: tuple[Resultado, int] | None
    apostas_no_periodo: int
    nao_liquidados_no_periodo: int


def _banca_no_inicio_de(todas: Sequence[ApostaComData], desde: datetime | None, banca_inicial: Decimal) -> Decimal:
    if desde is None:
        return banca_inicial
    anteriores = [a for a in todas if a.kickoff_utc < desde]
    if not anteriores:
        return banca_inicial
    return anteriores[-1].aposta.banca_depois


def _taxa_acerto(apostas: Sequence[ApostaComData]) -> Decimal | None:
    return calcular_taxa_acerto([a.aposta.resultado for a in apostas])


def _drawdown_maximo_e_recuperacao(
    curva: list[tuple[datetime | None, Decimal]],
) -> tuple[Decimal, int | None]:
    # curva[0] e' o ponto de partida (kickoff_utc=None, banca no inicio
    # do periodo); os demais sao (kickoff_utc, banca_depois) de cada
    # aposta, em ordem. Varre a curva rastreando o pico corrente; toda
    # vez que o drawdown a partir do pico bate um novo maximo, guarda o
    # indice do pico e do vale pra depois medir a recuperacao.
    pico_valor = curva[0][1]
    pico_indice = 0
    maior_drawdown = Decimal("0")
    indice_pico_do_maior_drawdown = 0
    indice_vale_do_maior_drawdown = 0

    for indice, (_kickoff, banca) in enumerate(curva):
        if banca > pico_valor:
            pico_valor = banca
            pico_indice = indice
            continue
        drawdown = pico_valor - banca
        if drawdown > maior_drawdown:
            maior_drawdown = drawdown
            indice_pico_do_maior_drawdown = pico_indice
            indice_vale_do_maior_drawdown = indice

    if maior_drawdown == 0:
        return Decimal("0"), None

    pico_valor_do_maior_drawdown = curva[indice_pico_do_maior_drawdown][1]
    kickoff_vale = curva[indice_vale_do_maior_drawdown][0]
    for kickoff, banca in curva[indice_vale_do_maior_drawdown + 1 :]:
        if banca >= pico_valor_do_maior_drawdown:
            # kickoff_vale so' e' None se o vale for o proprio ponto de
            # partida (curva[0]) - so acontece se maior_drawdown ja
            # tivesse sido 0 (retorno antecipado acima), entao aqui
            # kickoff_vale e kickoff sao sempre timestamps reais.
            return maior_drawdown, (kickoff - kickoff_vale).days
    return maior_drawdown, None


def _sequencia_atual(apostas: Sequence[ApostaComData]) -> tuple[Resultado, int] | None:
    if not apostas:
        return None
    ultimo_resultado = apostas[-1].aposta.resultado
    contagem = 0
    for item in reversed(apostas):
        if item.aposta.resultado != ultimo_resultado:
            break
        contagem += 1
    return ultimo_resultado, contagem


def calcular_metricas(
    todas_apostas: Sequence[ApostaComData],
    *,
    banca_inicial: Decimal,
    desde: datetime | None,
    nao_liquidados_no_periodo: int,
) -> Metricas:
    banca_atual = todas_apostas[-1].aposta.banca_depois if todas_apostas else banca_inicial
    banca_inicio_periodo = _banca_no_inicio_de(todas_apostas, desde, banca_inicial)
    apostas_periodo = [a for a in todas_apostas if desde is None or a.kickoff_utc >= desde]

    variacao_absoluta = banca_atual - banca_inicio_periodo
    variacao_percentual = variacao_absoluta / banca_inicio_periodo if banca_inicio_periodo != 0 else None

    total_apostado = sum((a.aposta.stake_valor for a in apostas_periodo), Decimal("0"))
    retorno_total = sum((a.aposta.retorno for a in apostas_periodo), Decimal("0"))
    lucro = retorno_total - total_apostado
    roi = lucro / total_apostado if total_apostado != 0 else None

    odd_media = (
        sum((a.aposta.odd for a in apostas_periodo), Decimal("0")) / len(apostas_periodo)
        if apostas_periodo
        else None
    )

    curva = [(None, banca_inicio_periodo)] + [(a.kickoff_utc, a.aposta.banca_depois) for a in apostas_periodo]
    drawdown_maximo, dias_para_recuperar = _drawdown_maximo_e_recuperacao(curva)

    return Metricas(
        banca_atual=banca_atual,
        variacao_absoluta=variacao_absoluta,
        variacao_percentual=variacao_percentual,
        total_apostado=total_apostado,
        lucro=lucro,
        roi=roi,
        taxa_acerto=_taxa_acerto(apostas_periodo),
        odd_media=odd_media,
        drawdown_maximo=drawdown_maximo,
        dias_para_recuperar=dias_para_recuperar,
        # Global (todas_apostas), nao recortado pro periodo - achado do
        # code-reviewer: uma sequencia e' estado do "agora", igual
        # banca_atual (mesmo raciocinio, mesma escolha), nao um fluxo
        # dentro da janela. Recortar pro periodo subestimaria
        # silenciosamente uma sequencia longa que comecou antes da janela.
        sequencia_atual=_sequencia_atual(todas_apostas),
        apostas_no_periodo=len(apostas_periodo),
        nao_liquidados_no_periodo=nao_liquidados_no_periodo,
    )
