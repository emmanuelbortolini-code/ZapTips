"""CLI que reconstroi o extrato (`bets`) de cada usuario que ja teve
assinatura, a partir de `master_ledger` - ver
app/settlement/extrato_usuario.py. Roda depois de
scripts/build_master_ledger.py (precisa do mestre atualizado pra
recortar).

Uso:
    uv run python -m scripts.build_bets
"""

import sys

from app.config import get_settings
from app.db import get_connection
from app.settlement.extrato_usuario import reconstruir_extrato_usuario


def buscar_usuarios_com_assinatura(cur) -> list[str]:
    cur.execute("select distinct user_id from subscriptions")
    return [str(row[0]) for row in cur.fetchall()]


def executar() -> dict[str, int]:
    settings = get_settings()

    with get_connection() as conn:
        with conn.cursor() as cur:
            usuarios = buscar_usuarios_com_assinatura(cur)

    resultado: dict[str, int] = {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            for user_id in usuarios:
                resultado[user_id] = reconstruir_extrato_usuario(cur, user_id, settings)
        conn.commit()
    return resultado


def main() -> int:
    resultado = executar()
    total_apostas = sum(resultado.values())
    print(f"{len(resultado)} usuario(s) com assinatura | {total_apostas} aposta(s) gravada(s) no total.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
