"""CLI que roda o motor de liquidacao (Fase 6a, app.settlement.engine)
contra picks vinculados cuja fixture ja encerrou. Fica fora das 6 etapas
do run_pipeline.py (Fase 5a) de proposito - mesma decisao ja tomada pra
collect_results.py (D5, Fase 5a): o timing de "liquidar horas depois do
kickoff" ainda nao foi desenhado como job proprio.

Todo pick tentado ganha uma linha em `pick_results`, mesmo quando o
resultado e' `nao_liquidavel` - e' isso que impede o pipeline de
reprocessar o mesmo pick pra sempre (`buscar_picks_pendentes` so traz o
que ainda nao tem linha). Picks ambiguos ficam visiveis em
`scripts/liquidacao.py listar`, pra revisao manual.

Uso:
    uv run python -m scripts.liquidar_picks
"""

import sys

import structlog

from app.db import get_connection
from app.pipeline import ResultadoEtapa
from app.settlement.engine import liquidar
from app.settlement.persistencia import buscar_picks_pendentes, buscar_stats_por_fixture, gravar_resultado

log = structlog.get_logger()


def executar() -> ResultadoEtapa:
    with get_connection() as conn:
        with conn.cursor() as cur:
            pendentes = buscar_picks_pendentes(cur)
            stats_por_fixture = buscar_stats_por_fixture(cur, [fixture.fixture_id for _, fixture in pendentes])

    contagem = {"liquidado": 0, "nao_liquidavel": 0}
    with get_connection() as conn:
        with conn.cursor() as cur:
            for pick, fixture in pendentes:
                resolution = liquidar(pick, fixture, stats_por_fixture.get(fixture.fixture_id, ()))
                gravar_resultado(cur, pick.pick_id, fixture.fixture_id, resolution, resolver=pick.mercado)
                if resolution.resultado == "nao_liquidavel":
                    contagem["nao_liquidavel"] += 1
                    log.info(
                        "pick_nao_liquidavel",
                        pick_id=pick.pick_id,
                        motivo=resolution.evidencia.get("motivo"),
                    )
                else:
                    contagem["liquidado"] += 1
        conn.commit()

    detalhe = {"pendentes": len(pendentes), **contagem}
    return ResultadoEtapa(
        status="ok", itens_ok=contagem["liquidado"], itens_erro=contagem["nao_liquidavel"], detalhe=detalhe
    )


def main() -> int:
    resultado = executar()
    print(f"{resultado.detalhe['pendentes']} pick(s) vinculado(s) com fixture encerrada pra liquidar.")
    print(f"liquidado: {resultado.detalhe['liquidado']} | nao_liquidavel: {resultado.detalhe['nao_liquidavel']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
