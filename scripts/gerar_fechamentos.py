"""CLI de geracao de mensagens de fechamento do palpite (Fase 6e, ver
app/fechamento_generator.py). Fica fora das 6 etapas do run_pipeline.py
de proposito - mesma familia de decisao ja tomada pra
scripts/liquidar_picks.py/build_master_ledger.py/build_bets.py: depende
de liquidacao E do extrato do usuario (Fase 6b) ja terem rodado.

Uso:
    uv run python -m scripts.gerar_fechamentos [--data AAAA-MM-DD]
"""

import sys

from app.config import get_settings
from app.db import get_connection
from app.fechamento_generator import gerar_fechamentos
from app.pipeline import ResultadoEtapa, data_operacional
from scripts._cli_args import data_arg


def executar(data=None) -> ResultadoEtapa:
    settings = get_settings()
    data_ref = data if data is not None else data_operacional()

    with get_connection() as conn:
        with conn.cursor() as cur:
            total = gerar_fechamentos(cur, data_ref, settings.rodape_legal)
        conn.commit()

    return ResultadoEtapa(status="ok", itens_ok=total, detalhe={"data": str(data_ref), "gerados": total})


def main() -> int:
    import argparse

    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL vazia, abortando.")
        return 1

    parser = argparse.ArgumentParser(prog="python -m scripts.gerar_fechamentos")
    parser.add_argument("--data", type=data_arg, default=None)
    args = parser.parse_args()

    resultado = executar(args.data)
    print(f"{resultado.detalhe['data']}: {resultado.detalhe['gerados']} mensagem(ns) de fechamento nova(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
