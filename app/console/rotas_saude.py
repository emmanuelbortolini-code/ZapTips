"""Rota da aba Saude (Fase 5c) - primeira tela ao abrir o console.
Le seis paineis; nao decide nada sozinha (decisao pura fica em
app/console/rules.py)."""

import psycopg
from fastapi import APIRouter, Depends, Request

from app.console.deps import estado_run_hoje, get_cursor
from app.console.queries import encerradas_sem_liquidacao, historico_coleta, mensagens_expiradas, orfaos_aguardando_partida, quota_mes
from app.console.rules import FONTES_COLETA, dias_fora_por_fonte, projetar_quota
from app.pipeline import data_operacional
from app.subs import listar_vencendo

router = APIRouter()

# D6 (CLAUDE.md Fase 5c): app.subs.listar_vencendo ja existe desde a
# Fase 5b e a Aba 3/Envio (onde a spec original coloca esse painel) so
# chega na Fase 5d - reaproveitar aqui e 3 linhas, nao vale esperar.
DIAS_HISTORICO_COLETA = 14


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
