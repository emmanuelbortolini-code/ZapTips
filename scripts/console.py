"""Launcher do console local (Fase 5c, ver app/console/). main() nao e
testado (so wiring de infra - subir o servidor), convencao do projeto.

Uso:
    uv run python -m scripts.console
"""

import sys

import uvicorn

from app.config import get_settings
from app.console.main import create_app


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL vazia, abortando.")
        return 1

    # 127.0.0.1, nunca 0.0.0.0 - console sem autenticacao, "so na minha
    # maquina" (CLAUDE.md, "Ambiente de execucao"). Expor na LAN seria
    # dar acesso de aprovacao de slate a qualquer dispositivo na rede.
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
    return 0


if __name__ == "__main__":
    sys.exit(main())
