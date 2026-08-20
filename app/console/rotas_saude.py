"""Rota da aba Saude (Fase 5c) - primeira tela ao abrir o console.
Le seis paineis; nao decide nada sozinha (decisao pura fica em
app/console/rules.py)."""

import threading

import psycopg
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.console.deps import checar_origin, estado_run_hoje, get_cursor
from app.console.queries import encerradas_sem_liquidacao, historico_coleta, mensagens_expiradas, orfaos_aguardando_partida, quota_mes
from app.console.rules import FONTES_COLETA, dias_fora_por_fonte, projetar_quota
from app.pipeline import ETAPAS, data_operacional
from app.subs import listar_vencendo

router = APIRouter()

# D6 (CLAUDE.md Fase 5c): app.subs.listar_vencendo ja existe desde a
# Fase 5b e a Aba 3/Envio (onde a spec original coloca esse painel) so
# chega na Fase 5d - reaproveitar aqui e 3 linhas, nao vale esperar.
DIAS_HISTORICO_COLETA = 14
NOMES_ETAPAS = frozenset(etapa.nome for etapa in ETAPAS)

# Achado do code-reviewer (botao de sincronizar, 2026-08-20): dois
# cliques rapidos no mesmo botao (ou um F5 antes do primeiro POST voltar)
# agendavam dois BackgroundTasks rodando a MESMA etapa em paralelo no
# mesmo processo - "a arquitetura ja exclui execucao concorrente"
# (app/pipeline_runs.py, scripts/build_slate.py) deixa de valer no
# instante em que o console passa a disparar `run_pipeline.executar()`
# a partir de um clique humano, nao so do agendador (que nunca dispara
# a mesma etapa duas vezes em paralelo). Sem essa trava, dois cliques em
# "sincronizar odds" dobrariam silenciosamente o consumo da cota paga
# da OddsPapi (250/mes) pro mesmo dado. `estado.etapas[].status ==
# 'rodando'` (usado pra desabilitar o botao no HTML) so e' escrito
# quando `avancar_etapas` de fato CHEGA nessa etapa - insuficiente
# sozinho, porque etapas anteriores ainda pendentes rodam antes dela.
# O set em memoria fecha essa janela na hora em que a requisicao e'
# aceita, antes mesmo do BackgroundTasks comecar.
_etapas_em_andamento: set[str] = set()
_trava_etapas_em_andamento = threading.Lock()


@router.get("/saude")
def ver_saude(
    request: Request,
    cur: psycopg.Cursor = Depends(get_cursor),
    estado=Depends(estado_run_hoje),
):
    from app.console.main import templates  # import tardio - ver nota em main.py
    from app.console.queries import carregar_dashboard_saude

    dashboard = carregar_dashboard_saude(cur, data_operacional(), estado)
    return templates.TemplateResponse(request, "saude.html", {"request": request, **dashboard})


def _disparar_sincronizacao(etapa: str) -> None:
    # Funcao a parte (nao inline no route handler) so pra testes poderem
    # monkeypatchar sem precisar de Postgres real nem esperar a etapa
    # rodar de verdade - a rota so agenda esta chamada via BackgroundTasks.
    # finally garante que a etapa sai de _etapas_em_andamento mesmo se
    # run_pipeline.executar() levantar (nao deveria, mas travaria o
    # botao pra sempre se acontecesse sem isso).
    try:
        import scripts.run_pipeline as run_pipeline  # noqa: PLC0415 - mesmo motivo do import tardio de templates acima: scripts/ e a camada de CLI/orquestracao, app/console e a unica excecao que chama pra dentro dela (mesmo papel operacional de scripts/agendador.py, que ja faz essa mesma chamada)

        run_pipeline.executar(forcadas=frozenset({etapa}))
    finally:
        with _trava_etapas_em_andamento:
            _etapas_em_andamento.discard(etapa)


@router.post("/saude/sincronizar/{etapa}", dependencies=[Depends(checar_origin)])
def post_sincronizar_etapa(etapa: str, background_tasks: BackgroundTasks) -> RedirectResponse:
    # Roda em background (nao bloqueia a resposta): uma etapa sozinha
    # ainda pode levar alguns segundos a dezenas de segundos (rate limit
    # de rede da ESPN/OddsPapi/SDA) - a mesma preocupacao que fez a Fase
    # 5c decidir "sem botao rodar agora" pro pipeline inteiro (6 etapas)
    # nao se aplica igual aqui: uma etapa isolada e bem mais curta, e
    # devolver a resposta na hora (o operador ve "rodando" no proximo
    # refresh, o mesmo estado que scripts/run_pipeline.py ja persiste em
    # pipeline_stages) evita segurar a requisicao HTTP presa.
    if etapa not in NOMES_ETAPAS:
        raise HTTPException(status_code=404, detail=f"etapa desconhecida: {etapa!r}")

    with _trava_etapas_em_andamento:
        if etapa in _etapas_em_andamento:
            raise HTTPException(status_code=409, detail=f"etapa {etapa!r} ja esta sincronizando")
        _etapas_em_andamento.add(etapa)

    background_tasks.add_task(_disparar_sincronizacao, etapa)
    return RedirectResponse(url="/saude", status_code=303)
