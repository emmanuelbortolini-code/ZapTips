"""CLI de revisao manual de liquidacao (Fase 6a). O documento original
nomeia isso `python -m app.settlement review`; renomeado pra scripts/,
mesma decisao D1 ja tomada em scripts/users.py/scripts/subs.py - o
projeto mantem toda logica de negocio/CLI fora de app/.

`listar` mostra os picks que `scripts/liquidar_picks.py` gravou como
`nao_liquidavel` em `pick_results` e que ninguem revisou ainda
(`revisado_por_humano = false`) - nao recalcula nada, so le o que o
pipeline automatico ja registrou.

`marcar` sobrescreve essa linha com o resultado decidido a mao,
gravando `revisado_por_humano = true`.

Uso:
    uv run python -m scripts.liquidacao listar
    uv run python -m scripts.liquidacao marcar --pick-id <uuid> --resultado green --motivo "..."
"""

import argparse
import sys

from app.config import get_settings
from app.db import get_connection
from app.settlement.persistencia import gravar_revisao_manual, listar_pendentes_revisao
from scripts._cli_args import resultado_liquidacao_arg, uuid_arg


def _cmd_listar(args: argparse.Namespace) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            pendentes = listar_pendentes_revisao(cur)

    if not pendentes:
        print("Nenhum pick pendente de revisao manual.")
        return 0

    for item in pendentes:
        print(
            f"pick {item.pick_id} | fixture {item.fixture_id} | mercado {item.mercado} "
            f"| selecao {item.selecao!r} | motivo {item.motivo}"
        )
    return 0


def _cmd_marcar(args: argparse.Namespace) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Inner join: pick sem fixture vinculada (fixture_id nulo,
            # status != vinculado) simplesmente nao aparece, em vez de
            # virar um None disfarcado de string "None" no insert
            # seguinte (achado do code-reviewer contra a 1a versao desta
            # rotina).
            cur.execute(
                "select p.fixture_id, p.status, f.status "
                "from picks p join fixtures f on f.id = p.fixture_id "
                "where p.id = %s::uuid",
                (args.pick_id,),
            )
            row = cur.fetchone()
            if row is None:
                print(f"Erro: pick {args.pick_id} nao encontrado ou sem fixture vinculada.")
                return 1

            fixture_id, pick_status, fixture_status = row
            if pick_status != "vinculado" or fixture_status != "encerrada":
                print(
                    f"Erro: pick {args.pick_id} nao esta pronto pra liquidacao "
                    f"(status do pick: {pick_status}, status da fixture: {fixture_status})."
                )
                return 1

            gravar_revisao_manual(cur, args.pick_id, str(fixture_id), args.resultado, args.motivo)
        conn.commit()

    print(f"Pick {args.pick_id} marcado como {args.resultado} (revisao manual).")
    return 0


def _montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.liquidacao")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_listar = sub.add_parser("listar")
    p_listar.set_defaults(func=_cmd_listar)

    p_marcar = sub.add_parser("marcar")
    p_marcar.add_argument("--pick-id", dest="pick_id", required=True, type=uuid_arg)
    p_marcar.add_argument("--resultado", required=True, type=resultado_liquidacao_arg)
    p_marcar.add_argument("--motivo", required=True)
    p_marcar.set_defaults(func=_cmd_marcar)

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
