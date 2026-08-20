"""Console local (Fase 5c) - FastAPI + Jinja2, sem autenticacao, so
`127.0.0.1` (ver app.console.deps, ORIGENS_PERMITIDAS). Duas abas nesta
fase: Saude e Curadoria - Envio e modo sessao ficam pra Fase 5d.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import StrictUndefined

_DIR = Path(__file__).parent

# Autoescape ON - diverge de app/messaging.py (autoescape=False) de
# proposito: la o corpo e texto puro de WhatsApp; aqui e HTML servido
# num navegador, com campos vindos de texto raspado de Telegram/
# WordPress (raw_picks/sources) - dado nao confiavel. Nunca desligar
# isso nem usar `| safe` em campo vindo dessas tabelas.
templates = Jinja2Templates(directory=str(_DIR / "templates"))
templates.env.undefined = StrictUndefined


def create_app() -> FastAPI:
    app = FastAPI(title="ZapTips Console")
    app.mount("/static", StaticFiles(directory=str(_DIR / "static")), name="static")

    from app.console.rotas_curadoria import router as router_curadoria  # noqa: PLC0415
    from app.console.rotas_envio import router as router_envio  # noqa: PLC0415
    from app.console.rotas_saude import router as router_saude  # noqa: PLC0415

    app.include_router(router_saude)
    app.include_router(router_curadoria)
    app.include_router(router_envio)

    @app.get("/")
    def raiz() -> RedirectResponse:
        return RedirectResponse(url="/saude", status_code=303)

    @app.exception_handler(Exception)
    def erro_handler(request: Request, exc: Exception):
        return templates.TemplateResponse(request, "erro.html", {"erro": type(exc).__name__}, status_code=500)

    return app
