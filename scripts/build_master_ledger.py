"""CLI que reconstroi `master_ledger` (Fase 6b) do zero a partir de
`pick_results` + `slate_picks`/`daily_slates` + `messages` - ver
app/settlement/master_ledger.py pro criterio de elegibilidade completo.

Fica fora das 6 etapas do run_pipeline.py de proposito, mesma familia de
decisao que scripts/liquidar_picks.py (Fase 6a) - depende de liquidacao
E envio ja terem acontecido, timing que ainda nao foi desenhado como job
recorrente (Fase 7).

Uso:
    uv run python -m scripts.build_master_ledger
"""

import sys

from app.db import get_connection
from app.settlement.master_ledger import reconstruir


def executar() -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            total = reconstruir(cur)
        conn.commit()
    return total


def main() -> int:
    total = executar()
    print(f"master_ledger reconstruido: {total} entrada(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
