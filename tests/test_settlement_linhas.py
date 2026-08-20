from decimal import Decimal

import pytest

from app.settlement.linhas import combinar, dividir_linha, eh_quarto, fracao_valida, metade_por_diferenca


@pytest.mark.parametrize(
    "linha,esperado",
    [
        (Decimal("2.00"), True), (Decimal("2.25"), True), (Decimal("2.50"), True), (Decimal("2.75"), True),
        (Decimal("-1.00"), True), (Decimal("-1.25"), True), (Decimal("-1.50"), True), (Decimal("-1.75"), True),
        (Decimal("0.00"), True),
        (Decimal("2.10"), False), (Decimal("-0.90"), False), (Decimal("1.33"), False),
    ],
)
def test_fracao_valida(linha, esperado):
    assert fracao_valida(linha) is esperado


@pytest.mark.parametrize(
    "linha,esperado",
    [
        (Decimal("2.25"), True), (Decimal("2.75"), True), (Decimal("-1.25"), True), (Decimal("-1.75"), True),
        (Decimal("0.25"), True), (Decimal("-0.25"), True), (Decimal("0.75"), True), (Decimal("-0.75"), True),
        (Decimal("2.00"), False), (Decimal("2.50"), False), (Decimal("-1.00"), False), (Decimal("-1.50"), False),
        (Decimal("0.00"), False),
    ],
)
def test_eh_quarto(linha, esperado):
    assert eh_quarto(linha) is esperado


@pytest.mark.parametrize(
    "linha,esperado",
    [
        (Decimal("2.75"), (Decimal("2.50"), Decimal("3.00"))),
        (Decimal("2.25"), (Decimal("2.00"), Decimal("2.50"))),
        (Decimal("-1.25"), (Decimal("-1.50"), Decimal("-1.00"))),
        (Decimal("-0.75"), (Decimal("-1.00"), Decimal("-0.50"))),
        (Decimal("0.25"), (Decimal("0.00"), Decimal("0.50"))),
        (Decimal("-0.25"), (Decimal("-0.50"), Decimal("0.00"))),
        (Decimal("2.00"), (Decimal("2.00"),)),
        (Decimal("2.50"), (Decimal("2.50"),)),
        (Decimal("-1.00"), (Decimal("-1.00"),)),
        (Decimal("0.00"), (Decimal("0.00"),)),
    ],
)
def test_dividir_linha(linha, esperado):
    assert dividir_linha(linha) == esperado


@pytest.mark.parametrize(
    "diferenca,esperado",
    [(Decimal("1"), "ganha"), (Decimal("0.5"), "ganha"), (Decimal("0"), "push"), (Decimal("-0.5"), "perde"), (Decimal("-1"), "perde")],
)
def test_metade_por_diferenca(diferenca, esperado):
    assert metade_por_diferenca(diferenca) == esperado


def test_combinar_uma_metade_ganha_e_green():
    assert combinar(("ganha",)) == "green"


def test_combinar_uma_metade_push_e_void():
    assert combinar(("push",)) == "void"


def test_combinar_uma_metade_perde_e_red():
    assert combinar(("perde",)) == "red"


def test_combinar_duas_metades_ganha_ganha_e_green():
    assert combinar(("ganha", "ganha")) == "green"


def test_combinar_duas_metades_push_push_e_void():
    assert combinar(("push", "push")) == "void"


def test_combinar_duas_metades_perde_perde_e_red():
    assert combinar(("perde", "perde")) == "red"


def test_combinar_duas_metades_ganha_push_e_meio_green():
    assert combinar(("ganha", "push")) == "meio_green"
    assert combinar(("push", "ganha")) == "meio_green"


def test_combinar_duas_metades_perde_push_e_meio_red():
    assert combinar(("perde", "push")) == "meio_red"
    assert combinar(("push", "perde")) == "meio_red"


def test_combinar_duas_metades_ganha_perde_e_defesa_nao_liquidavel():
    # Impossivel para linha legal (fracao_valida) com totais/margens
    # inteiros - fica so como defesa em profundidade, nunca chuta lado.
    assert combinar(("ganha", "perde")) == "nao_liquidavel"
