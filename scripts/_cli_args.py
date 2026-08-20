"""Conversores de argumento compartilhados entre CLIs argparse de
scripts/ (nao e um script em si - underscore no nome, mesmo padrao de
tests/_fakes.py - nao coletado pelo pytest nem invocavel via -m)."""

import argparse
from datetime import date
from uuid import UUID


def uuid_arg(bruto: str) -> str:
    try:
        return str(UUID(bruto))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"uuid invalido: {bruto!r}") from exc


def data_arg(bruto: str) -> date:
    try:
        return date.fromisoformat(bruto)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"data invalida, use AAAA-MM-DD: {bruto!r}") from exc


_RESULTADOS_LIQUIDACAO_VALIDOS = ("green", "meio_green", "void", "meio_red", "red")


def resultado_liquidacao_arg(bruto: str) -> str:
    # 'nao_liquidavel' de proposito fora da lista - revisao manual marca
    # um resultado real, nunca reafirma "nao da pra liquidar".
    if bruto not in _RESULTADOS_LIQUIDACAO_VALIDOS:
        raise argparse.ArgumentTypeError(
            f"resultado invalido: {bruto!r} - use um de {', '.join(_RESULTADOS_LIQUIDACAO_VALIDOS)}"
        )
    return bruto
