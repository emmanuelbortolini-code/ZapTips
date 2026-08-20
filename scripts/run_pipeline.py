"""Orquestrador de pipeline (Fase 5a, ver CLAUDE.md) - liga em sequencia
os coletores/processadores das Fases 1 a 4, registrando cada etapa em
`pipeline_runs`/`pipeline_stages` (schema desde a Fase 0). So `fixtures`
aborta o run inteiro se falhar; as demais degradam e o run segue.

A logica de sequenciamento/degradacao/resume e pura (app/pipeline.py,
`avancar_etapas`) - este script so injeta os adaptadores reais (que
chamam `executar()` de cada script de etapa) e os callbacks de
persistencia, em transacoes curtas por etapa (nenhuma conexao fica
aberta durante o trabalho de rede de uma etapa - mesmo achado da Fase 1f
reaplicado aqui).

Resume automatico: reexecutar no mesmo dia pula etapas ja 'ok' (poupa
cota do OddsPapi) e retenta as que ficaram 'degradado'/'falhou'/'rodando'
(essa ultima e sinal de uma execucao anterior interrompida - resetada
pra 'pendente' antes de comecar).

Uso:
    uv run python -m scripts.run_pipeline
    uv run python -m scripts.run_pipeline --forcar-etapa odds --forcar-etapa slate
"""

import sys
from typing import Mapping

import structlog

import scripts.build_slate as build_slate
import scripts.collect_eagle_predict as collect_eagle_predict
import scripts.collect_fixtures as collect_fixtures
import scripts.collect_odds as collect_odds
import scripts.collect_sda as collect_sda
import scripts.extract_picks as extract_picks
import scripts.link_picks as link_picks
import scripts.resolve_odds as resolve_odds
from app.config import get_settings
from app.db import get_connection
from app.pipeline import Adaptador, EtapaSpec, ResultadoEtapa, avancar_etapas, consolidar_subetapas, data_operacional, degradar
from app.pipeline_runs import abrir_run, carregar_resultados, fechar_etapa, fechar_run, iniciar_etapa, resetar_etapas_travadas

log = structlog.get_logger()


def _rodar_subetapa(nome: str, fn) -> ResultadoEtapa:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - fronteira deliberada, isola sub-fontes entre si
        log.warning("subetapa_falhou", subetapa=nome, erro=type(exc).__name__)
        return degradar(exc)


def _adaptador_coleta(resultados: Mapping[str, ResultadoEtapa]) -> ResultadoEtapa:
    sub = {
        "eagle_predict": _rodar_subetapa("eagle_predict", collect_eagle_predict.executar),
        "sda": _rodar_subetapa("sda", collect_sda.executar),
    }
    return consolidar_subetapas(sub)


def _adaptador_odds(resultados: Mapping[str, ResultadoEtapa]) -> ResultadoEtapa:
    sub = {
        "collect_odds": _rodar_subetapa("collect_odds", collect_odds.executar),
        "resolve_odds": _rodar_subetapa("resolve_odds", resolve_odds.executar),
    }
    return consolidar_subetapas(sub)


def _adaptador_matching(resultados: Mapping[str, ResultadoEtapa]) -> ResultadoEtapa:
    # D2 (CLAUDE.md, Fase 5a): o contador de tentativas de picks_orfaos so
    # avanca quando a etapa fixtures trouxe partida nova nesta execucao -
    # senao uma semana sem fixture nova queimaria tentativas a toa.
    fixtures_resultado = resultados.get("fixtures")
    trouxe_novas = bool(fixtures_resultado and fixtures_resultado.detalhe.get("novas", 0) > 0)
    return link_picks.executar(contar_tentativa=trouxe_novas)


ADAPTADORES: dict[str, Adaptador] = {
    "fixtures": lambda resultados: collect_fixtures.executar(),
    "coleta": _adaptador_coleta,
    "extracao": lambda resultados: extract_picks.executar(),
    "matching": _adaptador_matching,
    "odds": _adaptador_odds,
    "slate": lambda resultados: build_slate.executar(),
}


def _parse_forcar_etapa(argv: list[str]) -> frozenset[str]:
    forcadas = []
    for i, arg in enumerate(argv):
        if arg == "--forcar-etapa" and i + 1 < len(argv):
            forcadas.append(argv[i + 1])
    return frozenset(forcadas)


def executar(forcadas: frozenset[str] = frozenset()) -> ResultadoEtapa:
    # Extraido de main() (Fase 7, achado real: era o UNICO script do
    # projeto sem essa separacao - o agendador (scripts/agendador.py)
    # precisa chamar isso programaticamente, sem depender de sys.argv,
    # mesmo padrao executar()/main() ja usado em todo o resto.
    data_ref = data_operacional()

    with get_connection() as conn:
        with conn.cursor() as cur:
            run_id, criado_agora = abrir_run(cur, data_ref)
            travadas = resetar_etapas_travadas(cur, run_id)
            resultados_iniciais = carregar_resultados(cur, run_id)
        conn.commit()

    if travadas:
        log.warning("etapas_travadas_resetadas", run_id=run_id, etapas=travadas)
    print(f"Run {data_ref} (id {run_id}){' - novo' if criado_agora else ' - retomado'}.")

    def ao_iniciar_etapa(etapa: EtapaSpec) -> None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                iniciar_etapa(cur, run_id, etapa)
            conn.commit()
        print(f"[{etapa.ordem}/6] {etapa.nome}...")

    def ao_fechar_etapa(etapa: EtapaSpec, resultado: ResultadoEtapa) -> None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                fechar_etapa(cur, run_id, etapa, resultado)
            conn.commit()
        print(f"    -> {resultado.status} (ok={resultado.itens_ok} erro={resultado.itens_erro})")

    resultados, status_final, etapa_atual = avancar_etapas(
        resultados_iniciais, ADAPTADORES, forcadas, ao_iniciar_etapa, ao_fechar_etapa
    )

    with get_connection() as conn:
        with conn.cursor() as cur:
            fechar_run(cur, run_id, status_final, etapa_atual)
        conn.commit()

    print(f"Run {data_ref} (id {run_id}) encerrado: {status_final}.")
    return ResultadoEtapa(status=status_final, detalhe={"run_id": run_id, "data": str(data_ref), "etapa_atual": etapa_atual})


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL vazia, abortando.")
        return 1

    forcadas = _parse_forcar_etapa(sys.argv[1:])
    resultado = executar(forcadas)
    if resultado.status == "falhou":
        log.error("pipeline_abortado", run_id=resultado.detalhe["run_id"], etapa=resultado.detalhe["etapa_atual"])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
