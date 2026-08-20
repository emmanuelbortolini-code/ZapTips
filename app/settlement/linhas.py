"""Kernel de linha quebrada (Fase 6a) - o unico modulo que sabe dividir
uma linha .25/.75 em duas metades e combinar o resultado de cada uma.
Serve over/under (gols/escanteios) e handicap asiatico ao mesmo tempo:
os dois sao "compara um numero contra uma linha", so a origem do numero
muda (total de gols/escanteios vs margem de gols ajustada pela linha).

Achado real da spec (secao SDA, "Linhas asiaticas quebradas em gols"):
"Mais 2.75 gols"/"Menos 2.25 gols" apareceram em casas diferentes - nao e
anomalia de uma casa, e tratar como over/under 2.5 comum superestima o
resultado silenciosamente. Este kernel existe pra nunca deixar isso
passar batido.
"""

from collections import Counter
from decimal import Decimal
from typing import Literal, Sequence

Metade = Literal["ganha", "push", "perde"]
Resultado = Literal["green", "meio_green", "void", "meio_red", "red", "nao_liquidavel"]

_QUARTO = Decimal("0.25")
_UNIDADE = Decimal("25")


def fracao_valida(linha: Decimal) -> bool:
    """True para linha em .00/.25/.50/.75 (com sinal) - qualquer outra
    fracao (ex.: .10) e linha malformada, nunca chutada."""
    resto = (abs(linha) * 100) % _UNIDADE
    return resto == 0


def eh_quarto(linha: Decimal) -> bool:
    """True para linha em .25 ou .75 (com sinal) - as que precisam ser
    divididas em duas metades."""
    resto = (abs(linha) * 100) % 50
    return resto == 25


def dividir_linha(linha: Decimal) -> tuple[Decimal, ...]:
    """Linha .25/.75 vira duas metades meio-ponto abaixo/acima (ex.: 2.75
    -> (2.50, 3.00); -1.25 -> (-1.50, -1.00)); qualquer outra linha e uma
    metade so, ela mesma."""
    if eh_quarto(linha):
        return (linha - _QUARTO, linha + _QUARTO)
    return (linha,)


def metade_por_diferenca(diferenca: Decimal) -> Metade:
    """diferenca > 0 -> o lado apostado ganhou aquela metade; == 0 ->
    push (linha exata); < 0 -> perdeu. O chamador monta `diferenca` do
    jeito certo pro mercado (over/under: total - linha, ou linha - total
    pra under; handicap: margem ajustada pela linha)."""
    if diferenca > 0:
        return "ganha"
    if diferenca == 0:
        return "push"
    return "perde"


def combinar(metades: Sequence[Metade]) -> Resultado:
    """Combina 1 ou 2 metades no resultado final. Com linha legal
    (fracao_valida) e totais/margens inteiros, {ganha, perde} nunca
    ocorre nas duas metades de uma linha .25/.75 - fica so como defesa
    em profundidade (nunca chuta um lado)."""
    if len(metades) == 1:
        (unica,) = metades
        if unica == "ganha":
            return "green"
        if unica == "push":
            return "void"
        return "red"

    contagem = Counter(metades)
    if contagem["ganha"] == 2:
        return "green"
    if contagem["push"] == 2:
        return "void"
    if contagem["perde"] == 2:
        return "red"
    if contagem["ganha"] == 1 and contagem["push"] == 1:
        return "meio_green"
    if contagem["perde"] == 1 and contagem["push"] == 1:
        return "meio_red"
    return "nao_liquidavel"  # {ganha, perde} - impossivel para linha legal, defesa
