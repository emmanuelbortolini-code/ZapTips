"""Parsing do bloco nativo de odds da ESPN - nivel 3 da hierarquia (ver
app/odds_resolution.py), usado so quando os niveis 1 (fonte) e 2
(OddsPapi) nao resolveram odd pra um pick de mercado 1x2.

Dois achados reais de uma sonda ao vivo desta sessao (2026-08-20, 7
ligas: bra.1, bra.2, eng.1, esp.1, uefa.champions, ita.1, ger.1),
contra a API de verdade, nao contra suposicao do documento original:

1. **Formato e' odds americanas (moneyline)**, nao decimais - ex.
   `"homeTeamOdds": {"moneyLine": -240}`. A sonda original da Fase 1a so
   descrevia a PRESENCA do bloco de odds, nunca confirmou o formato
   numerico. `_moneyline_para_decimal` converte antes de qualquer uso.
2. **O unico provider observado nas 7 ligas testadas foi a DraftKings**,
   casa americana NAO licenciada no Brasil - a sonda da Fase 1a (2026-08-10,
   temporada anterior) tinha visto Bet365 em parte da amostra, mas isso
   nao se reproduziu na amostra ao vivo de hoje. Por isso `casas_licenciadas
   _normalizadas` e' sempre um filtro real, nao cosmetico: o caso comum
   hoje (DraftKings) e' descartado sem erro, silenciosamente - exatamente
   o comportamento esperado quando o nivel 3 nao tem casa licenciada
   disponivel pra aquela partida.

`hasOdds` (campo top-level de /summary) NAO e' confiavel (achado
original da Fase 1a, reconfirmado na sonda de hoje: veio `False` com o
array `odds` de fato preenchido) - este modulo nunca olha pra ele,
so inspeciona o array `odds` (identico a `pickcenter` no payload real,
confirmado por comparacao direta - so um precisa ser lido).
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

# "casa"/"fora"/"empate" - mesmo vocabulario de app.odds_resolution.Selecao1x2,
# mas nao importado daqui pra evitar import circular (odds_resolution
# importa deste modulo, nao o contrario).
_CAMPO_POR_SELECAO = {"casa": "homeTeamOdds", "fora": "awayTeamOdds", "empate": "drawOdds"}


@dataclass(frozen=True)
class OddEspnEncontrada:
    valor: float
    casa_nome: str


def normalizar_nome_casa(nome: str) -> str:
    return "".join(nome.lower().split())


def _moneyline_para_decimal(moneyline: float) -> float | None:
    if moneyline == 0:
        return None
    # Decimal, nao float puro - mesma cautela ja aplicada em
    # calcular_odd_minima (app/odds_resolution.py) contra ruido binario.
    ml = Decimal(str(moneyline))
    if ml > 0:
        bruta = Decimal("1") + ml / Decimal("100")
    else:
        bruta = Decimal("1") + Decimal("100") / abs(ml)
    return float(bruta.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def extrair_odds_licenciadas(
    payload_summary: dict, selecao: str, casas_licenciadas_normalizadas: set[str]
) -> list[OddEspnEncontrada]:
    """Devolve, pra `selecao` ('casa'/'empate'/'fora'), toda odd decimal
    convertida de um provider do bloco `odds` que bater com uma casa
    licenciada (match por nome normalizado - sem espaco, sem case; o
    payload real usa nomes como "DraftKings"/"Bet 365" e `casas.aliases`
    ainda esta vazio, entao normalizar e' o unico jeito de bater "Bet 365"
    contra a casa cadastrada como "Bet365").

    Entrada malformada (provider ausente, campo de odds nulo, moneyline
    nao numerico) e' pulada sem quebrar as demais - mesma politica ja
    usada em espn_fixtures/espn_summary/oddspapi pra um payload sem
    contrato de estabilidade."""
    campo = _CAMPO_POR_SELECAO[selecao]
    encontradas: list[OddEspnEncontrada] = []

    for entrada in payload_summary.get("odds") or []:
        if not isinstance(entrada, dict):
            # Mesma classe de bug ja corrigida em espn_fixtures/espn_summary
            # (Fase 1e/1f): um item `null` explicito na lista (nao so um
            # campo interno nulo) nao pode derrubar o parsing das demais
            # entradas - payload sem contrato de estabilidade.
            continue
        provider = entrada.get("provider") or {}
        provider_nome = provider.get("name")
        if not provider_nome:
            continue

        if normalizar_nome_casa(provider_nome) not in casas_licenciadas_normalizadas:
            continue

        bloco = entrada.get(campo) or {}
        moneyline = bloco.get("moneyLine")
        if moneyline is None:
            continue
        try:
            moneyline_float = float(moneyline)
        except (TypeError, ValueError):
            continue

        valor = _moneyline_para_decimal(moneyline_float)
        if valor is None:
            continue

        encontradas.append(OddEspnEncontrada(valor=valor, casa_nome=provider_nome))

    return encontradas
