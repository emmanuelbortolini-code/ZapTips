"""CLI de identidade/consentimento de assinantes (Fase 5b, ver
app/users.py pra logica e docstring completos). main()/subcomandos nao
sao testados (convencao do projeto - so parse/chama/imprime aqui, nada
de decisao de negocio).

O documento original nomeia esses comandos como `python -m app.users`,
mas o projeto separa logica pura (app/) de CLI (scripts/) em todo o
resto do codigo - nenhum modulo em app/ tem argparse ou main() (ver
CLAUDE.md, Fase 5b). Este script preserva a logica em app/users.py e so
adapta o caminho do comando.

Uso:
    uv run python -m scripts.users cadastrar --telefone +5511999991111 --nome "Fulano" --opt-in-origem "whatsapp direto" --opt-in-evidencia "print da conversa 2026-08-11"
    uv run python -m scripts.users optin --telefone +5511999991111 --opt-in-origem "voltou via whatsapp" --opt-in-evidencia "print novo"
    uv run python -m scripts.users optout --telefone +5511999991111
    uv run python -m scripts.users export --user-id <uuid> [--stdout]
"""

import argparse
import json
import sys
from datetime import datetime, timezone

from app.config import get_settings
from app.db import get_connection
from app.users import (
    TelefoneInvalido,
    TelefoneJaCadastrado,
    criar_usuario,
    exportar_dados_usuario,
    mascarar_telefone,
    registrar_opt_in_novamente,
    registrar_opt_out,
)
from scripts._cli_args import uuid_arg


def _cmd_cadastrar(args: argparse.Namespace) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                user_id = criar_usuario(
                    cur, nome=args.nome, telefone_e164=args.telefone, fuso_horario=args.fuso_horario,
                    idioma=args.idioma, opt_in_origem=args.opt_in_origem, opt_in_evidencia=args.opt_in_evidencia,
                )
            except (TelefoneInvalido, TelefoneJaCadastrado) as exc:
                print(f"Erro: {exc}")
                return 1
        conn.commit()
    print(f"Usuario cadastrado: {user_id} ({mascarar_telefone(args.telefone)})")
    return 0


def _cmd_optin(args: argparse.Namespace) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                user_id = registrar_opt_in_novamente(
                    cur, args.telefone, opt_in_origem=args.opt_in_origem, opt_in_evidencia=args.opt_in_evidencia,
                )
            except TelefoneInvalido as exc:
                print(f"Erro: {exc}")
                return 1
        conn.commit()
    if user_id is None:
        print("Nenhum usuario encontrado com esse telefone.")
        return 1
    print(f"Opt-in registrado de novo: {user_id}")
    return 0


def _cmd_optout(args: argparse.Namespace) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                quantidade = registrar_opt_out(cur, args.telefone)
            except TelefoneInvalido as exc:
                print(f"Erro: {exc}")
                return 1
        conn.commit()
    if quantidade is None:
        print("Ja estava fora da lista.")
        return 0
    print(f"Opt-out registrado. {quantidade} mensagem(ns) pendente(s) invalidada(s).")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            dados = exportar_dados_usuario(cur, args.user_id)

    texto = json.dumps(dados, indent=2, ensure_ascii=False)
    if args.stdout:
        print(texto)
        return 0

    nome_arquivo = f"export_{args.user_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(nome_arquivo, "w", encoding="utf-8") as arquivo:
        arquivo.write(texto)
    print(f"Exportado para {nome_arquivo}")
    return 0


def _montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.users")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_cadastrar = sub.add_parser("cadastrar")
    p_cadastrar.add_argument("--telefone", required=True)
    p_cadastrar.add_argument("--nome")
    p_cadastrar.add_argument("--fuso-horario", dest="fuso_horario", default="America/Sao_Paulo")
    p_cadastrar.add_argument("--idioma", default="pt-BR")
    p_cadastrar.add_argument("--opt-in-origem", dest="opt_in_origem", required=True)
    p_cadastrar.add_argument("--opt-in-evidencia", dest="opt_in_evidencia", required=True)
    p_cadastrar.set_defaults(func=_cmd_cadastrar)

    p_optin = sub.add_parser("optin")
    p_optin.add_argument("--telefone", required=True)
    p_optin.add_argument("--opt-in-origem", dest="opt_in_origem", required=True)
    p_optin.add_argument("--opt-in-evidencia", dest="opt_in_evidencia", required=True)
    p_optin.set_defaults(func=_cmd_optin)

    p_optout = sub.add_parser("optout")
    p_optout.add_argument("--telefone", required=True)
    p_optout.set_defaults(func=_cmd_optout)

    p_export = sub.add_parser("export")
    p_export.add_argument("--user-id", dest="user_id", required=True, type=uuid_arg)
    p_export.add_argument("--stdout", action="store_true")
    p_export.set_defaults(func=_cmd_export)

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
