"""CLI de geracao da pagina publica de performance (Fase 7, spec "Pagina
publica de performance") - le o extrato MESTRE (`master_ledger`, ja
reconstruido por `scripts/build_master_ledger.py`) e escreve dois
arquivos estaticos em `public/`: `index.html` (arquivo unico, sem
servidor) e `resumo.txt` (pronto pra colar no WhatsApp). Regenera do
zero a cada execucao - os dois arquivos sao sempre sobrescritos no mesmo
caminho, nunca versionados por timestamp (diferente de
`scripts/backup.py`), porque a pagina precisa de uma URL estavel pra
poder ser hospedada/compartilhada de novo sem re-configurar nada.

Publicar o arquivo (upload pra Netlify Drop, GitHub Pages, etc.) e' um
passo manual do operador - o script so' gera o artefato local, mesmo
"eu posso hospedar em qualquer lugar" que a spec ja antecipa. Este
projeto nao tem repositorio git nem credencial de hospedagem
configurados ainda.

Uso:
    uv run python -m scripts.gerar_pagina_publica
"""

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.config import get_settings
from app.db import get_connection
from app.pagina_publica import renderizar_html_publico, renderizar_texto_publico
from app.pipeline import ResultadoEtapa
from app.relatorio_publico import gerar_dados_publicos

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"


def executar() -> ResultadoEtapa:
    settings = get_settings()
    agora = datetime.now(timezone.utc)

    with get_connection() as conn:
        with conn.cursor() as cur:
            dados = gerar_dados_publicos(cur, settings, agora)

    stake_pct = Decimal(str(settings.stake_pct_padrao))
    html = renderizar_html_publico(dados, settings.rodape_legal, stake_pct)
    texto = renderizar_texto_publico(dados, settings.rodape_legal, stake_pct)

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DIR / "index.html").write_text(html, encoding="utf-8")
    (PUBLIC_DIR / "resumo.txt").write_text(texto, encoding="utf-8")

    return ResultadoEtapa(
        status="ok", itens_ok=1,
        detalhe={"arquivo_html": str(PUBLIC_DIR / "index.html"), "arquivo_texto": str(PUBLIC_DIR / "resumo.txt")},
    )


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL vazia, abortando.")
        return 1

    resultado = executar()
    print(f"Pagina publica gerada: {resultado.detalhe['arquivo_html']}")
    print(f"Resumo em texto gerado: {resultado.detalhe['arquivo_texto']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
