"""Rota da aba Relatorios (pendencia 8, CLAUDE.md): expoe no console a
mesma performance por fonte que `scripts/relatorio.py fontes` ja calcula
via linha de comando - nunca uma segunda implementacao da mesma
pergunta, so reaproveita `app.console.queries.carregar_relatorio_fontes_30d`.

Relatorio de usuario (tambem CLI-only hoje) fica de fora por decisao
desta sessao: exige `--user-id`, e nao existe seletor/lista de
assinantes na UI - escopo maior, registrado a parte no CLAUDE.md."""

import psycopg
from fastapi import APIRouter, Depends, Request

from app.console.deps import get_cursor

router = APIRouter()


@router.get("/relatorios")
def ver_relatorios(request: Request, cur: psycopg.Cursor = Depends(get_cursor)):
    from app.console.main import templates  # import tardio - ver nota em main.py
    from app.console.queries import carregar_relatorio_fontes_30d

    metricas, quarentena_por_fonte = carregar_relatorio_fontes_30d(cur)
    metricas_ordenadas = sorted(metricas, key=lambda m: m.chave)
    return templates.TemplateResponse(
        request,
        "relatorios.html",
        {
            "request": request,
            "metricas": metricas_ordenadas,
            "quarentena_por_fonte": quarentena_por_fonte,
        },
    )
