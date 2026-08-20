"""CLI de assinaturas manuais via Pix (Fase 5b, ver app/subs.py pra
logica e docstring completos). main()/subcomandos nao sao testados
(convencao do projeto). Mesma decisao de layering de scripts/users.py:
o documento original nomeia isso `python -m app.subs`, mas o projeto
mantem toda logica de negocio em app/ sem CLI la dentro.

Uso:
    uv run python -m scripts.subs registrar --user-id <uuid> --inicio 2026-08-01 --fim 2026-08-31 --valor 49.90 --ref "E12345..."
    uv run python -m scripts.subs vencendo [--dias 5]
"""

import argparse
import sys
from decimal import Decimal, InvalidOperation

from app.config import get_settings
from app.db import get_connection
from app.pipeline import data_operacional
from app.subs import (
    DIAS_AVISO_VENCIMENTO,
    PeriodoInvalido,
    ReferenciaPagamentoDuplicada,
    TetoExcedido,
    UsuarioInexistente,
    UsuarioOptOut,
    listar_vencendo,
    registrar_assinatura,
)
from scripts._cli_args import data_arg, uuid_arg


def _decimal_arg(bruto: str) -> Decimal:
    try:
        return Decimal(bruto)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"valor monetario invalido: {bruto!r}") from exc


def _cmd_registrar(args: argparse.Namespace) -> int:
    settings = get_settings()
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                sub_id = registrar_assinatura(
                    cur, user_id=args.user_id, inicio=args.inicio, fim=args.fim, valor=args.valor,
                    meio_pagamento=args.meio, referencia_pagamento=args.ref, registrado_por=args.registrado_por,
                    teto=settings.max_assinantes_ativos,
                )
            except TetoExcedido as exc:
                print(f"Recusado: teto de {exc.teto} assinantes ativos seria excedido em {exc.dia} ({exc.quantidade} assinantes).")
                return 1
            except (UsuarioInexistente, UsuarioOptOut, PeriodoInvalido, ReferenciaPagamentoDuplicada) as exc:
                print(f"Erro: {exc}")
                return 1
        conn.commit()
    print(f"Assinatura registrada: {sub_id}")
    return 0


def _cmd_vencendo(args: argparse.Namespace) -> int:
    hoje = data_operacional()
    with get_connection() as conn:
        with conn.cursor() as cur:
            vencendo = listar_vencendo(cur, hoje=hoje, dias=args.dias)

    if not vencendo:
        print(f"Nenhuma assinatura vencendo nos proximos {args.dias} dias.")
        return 0

    for item in vencendo:
        renovado = " (ja renovado)" if item.ja_renovado else ""
        print(f"{item.nome or item.telefone_e164} | vence {item.fim} (em {item.dias_restantes}d) | R$ {item.valor}{renovado}")
    return 0


def _montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.subs")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_registrar = sub.add_parser("registrar")
    p_registrar.add_argument("--user-id", dest="user_id", required=True, type=uuid_arg)
    p_registrar.add_argument("--inicio", required=True, type=data_arg)
    p_registrar.add_argument("--fim", required=True, type=data_arg)
    p_registrar.add_argument("--valor", required=True, type=_decimal_arg)
    p_registrar.add_argument("--meio", default="pix", choices=("pix", "transferencia", "outro"))
    p_registrar.add_argument("--ref", dest="ref", default=None)
    p_registrar.add_argument("--registrado-por", dest="registrado_por", default="pm")
    p_registrar.set_defaults(func=_cmd_registrar)

    p_vencendo = sub.add_parser("vencendo")
    p_vencendo.add_argument("--dias", type=int, default=DIAS_AVISO_VENCIMENTO)
    p_vencendo.set_defaults(func=_cmd_vencendo)

    return parser


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL vazia, abortando.")
        return 1

    args = _montar_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
