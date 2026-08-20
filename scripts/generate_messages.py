"""CLI de geracao de mensagens (Fase 5d, ver app/messages_generator.py).

Nao e uma 7a etapa do pipeline (D1, Fase 5d): a spec fala em "etapa
slate" gerando mensagem, mas o slate so vira mensagem depois de aprovado
no console, e a aprovacao e manual - uma etapa automatica de madrugada
geraria mensagem de um slate que ainda nem foi aprovado, ou so no dia
seguinte. Geracao acontece na aprovacao mesma (rotas_curadoria.py::
post_aprovar_slate, mesma transacao). Este CLI e o caminho de
recuperacao manual - reprocessar um dia sem passar pelo console de novo,
ou o uso futuro do scheduler da Fase 7.

Uso:
    uv run python -m scripts.generate_messages [--data AAAA-MM-DD]
"""

import sys
from datetime import datetime, timezone

from app.config import get_settings
from app.db import get_connection
from app.messages_generator import gerar_mensagens
from app.pipeline import ResultadoEtapa, data_operacional
from scripts._cli_args import data_arg


def executar(data=None) -> ResultadoEtapa:
    settings = get_settings()
    data_ref = data if data is not None else data_operacional()
    agora = datetime.now(timezone.utc)

    with get_connection() as conn:
        with conn.cursor() as cur:
            relatorio = gerar_mensagens(cur, data_ref, agora, settings)
        conn.commit()

    if relatorio.status == "pulado":
        return ResultadoEtapa(status="ok", detalhe={"pulado": relatorio.motivo_pulo, "data": str(data_ref)})

    detalhe = {
        "data": str(data_ref), "gerados": relatorio.gerados, "ja_existentes": relatorio.ja_existentes,
        "pulados_antecedencia": relatorio.pulados_antecedencia,
    }
    return ResultadoEtapa(status="ok", itens_ok=relatorio.gerados, itens_erro=relatorio.pulados_antecedencia, detalhe=detalhe)


def main() -> int:
    import argparse

    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL vazia, abortando.")
        return 1

    parser = argparse.ArgumentParser(prog="python -m scripts.generate_messages")
    parser.add_argument("--data", type=data_arg, default=None)
    args = parser.parse_args()

    resultado = executar(args.data)
    if resultado.detalhe.get("pulado"):
        print(f"Geracao pulada pra {resultado.detalhe['data']}: {resultado.detalhe['pulado']}.")
        return 0

    print(
        f"{resultado.detalhe['data']}: {resultado.detalhe['gerados']} mensagem(ns) nova(s), "
        f"{resultado.detalhe['ja_existentes']} ja existente(s), "
        f"{resultado.detalhe['pulados_antecedencia']} pulada(s) por antecedencia minima."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
