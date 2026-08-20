"""Performance por fonte (Fase 6d) - mesmo motor da Fase 6a/6c, escopo
maior: TODOS os picks liquidados, publicados ou nao (inclui quarentena,
cortados por conflito, removidos na curadoria, rejeitados pelo piso de
odd). Funcao pura - agrupa e agrega, sem tocar Postgres. Camada DB-shape
em app.settlement.relatorio_fonte.

"Comparabilidade" (spec): fonte publicada e fonte em quarentena sao
medidas sobre a MESMA base - mesma formula de piso, mesma origem de
odd, mesmo motor de liquidacao. E' por isso que o ROI aqui usa
`odd_minima` (a mesma odd sombra que Fase 6b usa pra picks publicados,
gravada em TODO pick que passa por scripts/resolve_odds.py - inclusive
os rejeitados pelo piso, desde a correcao desta sessao), nunca
`odd_citada`/`odd_referencia` direto.

ROI aqui usa stake unitario (1 por pick) - nao ha banca/usuario
envolvido nesse relatorio, so' comparacao de qualidade de fonte, entao
"quanto retornaria por unidade apostada" e' a metrica certa, nao uma
simulacao de banca completa (essa e' o trabalho da Fase 6b).

Regra dura da spec: "nenhuma taxa de acerto e exibida sem o ROI ao
lado" - reforcada em `MetricasGrupo` carregando os dois sempre juntos
(nunca uma funcao que devolve so um dos dois).

**Leitura importante pra quem olhar este relatorio** (achado do
code-reviewer): pra todo pick com `status='descartado'` rejeitado pelo
PISO de odd (nao por conflito), `odd_minima` e' sempre exatamente igual
a `ODD_MINIMA_ABSOLUTA` - `calcular_odd_minima` nunca escolhe outro
valor quando a odd de referencia ja' esta abaixo do piso (ver comentario
em scripts/resolve_odds.py). Isso e' intencional: o ROI desse pick
responde "se tivesse batido nosso piso exato, seria lucro?", nao tenta
reconstruir a odd real de mercado (que nunca foi oferecida a ninguem).
Nao confundir esse numero com odd de mercado real ao comparar fontes.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from app.settlement.banca import Resultado, calcular_fator_retorno, calcular_taxa_acerto


@dataclass(frozen=True)
class PickComOdd:
    # Um pick que passou por resolve_odds.py (tem odd_minima sombra),
    # liquidado (resultado != None) ou nao_liquidavel (resultado None -
    # o motor tentou e nao conseguiu, diferente de sem_odd, que nunca
    # chega aqui por nao ter odd_minima nenhuma).
    pick_id: str
    resultado: Resultado | None
    odd_minima: Decimal
    odd_citada: Decimal | None
    odd_referencia: Decimal | None


@dataclass(frozen=True)
class MetricasGrupo:
    chave: tuple[str, ...]
    volume_liquidado: int
    volume_nao_liquidado: int
    volume_sem_odd: int
    percentual_nao_liquidados: Decimal | None
    roi: Decimal | None
    taxa_acerto: Decimal | None
    odd_media: Decimal | None
    diferenca_media_odd: Decimal | None


def calcular_metricas_grupo(
    chave: tuple[str, ...], picks_com_odd: Sequence[PickComOdd], *, volume_sem_odd: int
) -> MetricasGrupo:
    liquidados = [p for p in picks_com_odd if p.resultado is not None]
    nao_liquidados = [p for p in picks_com_odd if p.resultado is None]

    total_tentado = len(liquidados) + len(nao_liquidados)
    percentual_nao_liquidados = Decimal(len(nao_liquidados)) / total_tentado if total_tentado else None

    roi = None
    if liquidados:
        # stake unitario - lucro por unidade apostada, media entre os picks.
        fatores = [calcular_fator_retorno(p.resultado, p.odd_minima) for p in liquidados]
        roi = (sum(fatores, Decimal("0")) - len(liquidados)) / len(liquidados)

    odd_media = (
        sum((p.odd_minima for p in picks_com_odd), Decimal("0")) / len(picks_com_odd) if picks_com_odd else None
    )

    diferencas = [
        p.odd_citada - p.odd_referencia
        for p in picks_com_odd
        if p.odd_citada is not None and p.odd_referencia is not None
    ]
    diferenca_media = sum(diferencas, Decimal("0")) / len(diferencas) if diferencas else None

    return MetricasGrupo(
        chave=chave,
        volume_liquidado=len(liquidados),
        volume_nao_liquidado=len(nao_liquidados),
        volume_sem_odd=volume_sem_odd,
        percentual_nao_liquidados=percentual_nao_liquidados,
        roi=roi,
        taxa_acerto=calcular_taxa_acerto([p.resultado for p in liquidados]),
        odd_media=odd_media,
        diferenca_media_odd=diferenca_media,
    )


@dataclass(frozen=True)
class SugestaoFonte:
    chave: tuple[str, ...]
    tipo: str  # "desativacao" | "promocao"
    roi: Decimal
    volume: int


def sugerir_acoes(
    metricas_por_grupo: Sequence[MetricasGrupo], *, quarentena_por_fonte: dict[str, bool], volume_minimo: int = 30
) -> list[SugestaoFonte]:
    # "Fonte com ROI negativo por 60 dias e volume acima de 30 palpites
    # deve aparecer com sugestao de desativacao. Fonte em quarentena com
    # ROI positivo consistente aparece com sugestao de promocao, sempre
    # por mercado." - o chamador e' responsavel por passar metricas ja
    # calculadas sobre a janela de 60 dias (esta funcao nao sabe de
    # tempo, so' avalia o que recebeu).
    sugestoes = []
    for m in metricas_por_grupo:
        if m.roi is None or m.volume_liquidado < volume_minimo:
            continue
        fonte = m.chave[0]
        em_quarentena = quarentena_por_fonte.get(fonte, False)
        if not em_quarentena and m.roi < 0:
            sugestoes.append(SugestaoFonte(chave=m.chave, tipo="desativacao", roi=m.roi, volume=m.volume_liquidado))
        elif em_quarentena and m.roi > 0:
            sugestoes.append(SugestaoFonte(chave=m.chave, tipo="promocao", roi=m.roi, volume=m.volume_liquidado))
    return sugestoes
