"""CLI de geracao de mensagens de resumo semanal (Fase 6e, ultimo pedaco
- ver app/resumo_semanal_generator.py). Fica fora das 6 etapas do
run_pipeline.py, mesma familia de decisao ja tomada pra
scripts/gerar_fechamentos.py - depende do extrato do usuario (Fase 6b)
ja ter rodado pra semana inteira.

Uso:
    uv run python -m scripts.gerar_resumo_semanal [--inicio-semana AAAA-MM-DD]

`--inicio-semana` espera a propria segunda-feira da semana desejada,
passada direto pra `gerar_resumos_semanais` sem normalizacao (mesmo
padrao de `--data` em scripts/gerar_fechamentos.py) - normalizar aqui E
de novo dentro de `executar()` foi um bug real (achado HIGH do
code-reviewer): a primeira normalizacao via
`segunda_da_semana_anterior` ja transforma a data pedida na segunda da
semana ANTERIOR a ela, entao um `--inicio-semana 2026-08-10` (intencao:
gerar a semana de 10-16/08) gerava silenciosamente a semana de 03-09/08
em vez disso. Sem o flag, `executar()` calcula a partir de hoje (a
semana que acabou de fechar) via `segunda_da_semana_anterior` - essa e a
UNICA normalizacao que deve existir, e so se aplica no caminho default.
"""

import sys

from app.config import get_settings
from app.db import get_connection
from app.pipeline import ResultadoEtapa, data_operacional, segunda_da_semana_anterior
from app.resumo_semanal_generator import gerar_resumos_semanais
from scripts._cli_args import data_arg


def executar(inicio_semana=None) -> ResultadoEtapa:
    settings = get_settings()
    inicio_ref = inicio_semana if inicio_semana is not None else segunda_da_semana_anterior(data_operacional())

    with get_connection() as conn:
        with conn.cursor() as cur:
            total = gerar_resumos_semanais(cur, inicio_ref, settings.rodape_legal, settings)
        conn.commit()

    return ResultadoEtapa(status="ok", itens_ok=total, detalhe={"inicio_semana": str(inicio_ref), "gerados": total})


def main() -> int:
    import argparse

    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL vazia, abortando.")
        return 1

    parser = argparse.ArgumentParser(prog="python -m scripts.gerar_resumo_semanal")
    parser.add_argument("--inicio-semana", dest="inicio_semana", type=data_arg, default=None)
    args = parser.parse_args()

    resultado = executar(args.inicio_semana)
    print(f"semana de {resultado.detalhe['inicio_semana']}: {resultado.detalhe['gerados']} resumo(s) semanal(is) novo(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
