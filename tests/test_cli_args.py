import argparse
from datetime import date

import pytest

from scripts._cli_args import data_arg, resultado_liquidacao_arg, uuid_arg


def test_uuid_arg_aceita_uuid_valido():
    assert uuid_arg("ed3b6eae-2fe7-4491-9fac-949678f9f38a") == "ed3b6eae-2fe7-4491-9fac-949678f9f38a"


def test_uuid_arg_normaliza_maiusculas():
    assert uuid_arg("ED3B6EAE-2FE7-4491-9FAC-949678F9F38A") == "ed3b6eae-2fe7-4491-9fac-949678f9f38a"


def test_uuid_arg_invalido_levanta_argumenttypeerror_nao_deixa_vazar_traceback_cru():
    # Achado real da validacao contra o Postgres (Fase 5b): --user-id sem
    # validacao deixava um psycopg.errors.InvalidTextRepresentation vazar
    # como traceback bruto pro operador - mesma classe de bug ja corrigida
    # pra referencia_pagamento duplicada.
    with pytest.raises(argparse.ArgumentTypeError):
        uuid_arg("nao-e-um-uuid")


def test_uuid_arg_string_vazia_invalida():
    with pytest.raises(argparse.ArgumentTypeError):
        uuid_arg("")


def test_data_arg_aceita_iso():
    assert data_arg("2026-08-11") == date(2026, 8, 11)


def test_data_arg_invalida_levanta_argumenttypeerror():
    with pytest.raises(argparse.ArgumentTypeError):
        data_arg("11/08/2026")


@pytest.mark.parametrize("resultado", ["green", "meio_green", "void", "meio_red", "red"])
def test_resultado_liquidacao_arg_aceita_valores_validos(resultado):
    assert resultado_liquidacao_arg(resultado) == resultado


def test_resultado_liquidacao_arg_nao_aceita_nao_liquidavel():
    # Revisao manual marca um resultado real, nunca reafirma que nao da
    # pra liquidar - "nao_liquidavel" fica de fora de proposito.
    with pytest.raises(argparse.ArgumentTypeError):
        resultado_liquidacao_arg("nao_liquidavel")


def test_resultado_liquidacao_arg_invalido_levanta_argumenttypeerror():
    with pytest.raises(argparse.ArgumentTypeError):
        resultado_liquidacao_arg("greeen")
