"""Backup diario do Postgres (Fase 7) - dump completo via pg_dump, num
processo so, sem servico de backup gerenciado ("Escala definida":
"Postgres e um processo so resolvem").

Prioriza a integridade do extrato de banca (spec: "O extrato de banca e
o dado mais dificil de reconstruir, priorize a integridade dele") - dump
completo em vez de so as tabelas de banca porque um dump parcial que
falhasse silenciosamente em incluir uma FK relacionada (picks, fixtures)
tornaria o extrato inutil de restaurar sozinho de qualquer forma.

Uso:
    uv run python -m scripts.backup
"""

import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.config import get_settings
from app.pipeline import ResultadoEtapa

BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"


def _sanitizar(texto: str, senha: str | None) -> str:
    # Mesma cautela ja aplicada em app/oddspapi.py (Fase 1g, CRITICAL: a
    # api key vazava pro log via str(exc) de uma chamada autenticada).
    # Redige a SENHA isolada, nao a database_url inteira (achado real
    # ao ajustar o teste desta funcao apos mover a senha pra PGPASSWORD:
    # comparar contra a URL completa e' fragil - pg_dump nem recebe mais
    # a URL inteira, entao um stderr que ecoasse so' a senha, formatada
    # de outro jeito, passaria batido por um replace exato da URL).
    if not senha:
        return texto
    return texto.replace(senha, "***senha_redacted***")


def executar() -> ResultadoEtapa:
    settings = get_settings()
    if not settings.database_url:
        return ResultadoEtapa(status="falhou", detalhe={"motivo": "database_url_vazia"})

    if shutil.which("pg_dump") is None:
        return ResultadoEtapa(status="falhou", detalhe={"motivo": "pg_dump_nao_encontrado_no_path"})

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destino = BACKUP_DIR / f"zaptips_{timestamp}.dump"

    # Senha via env (PGPASSWORD), nunca em argv (achado MEDIUM do
    # code-reviewer): um argumento de linha de comando fica visivel no
    # process list (Task Manager/`ps`) durante toda a execucao do
    # pg_dump - baixo risco dado o modelo de ameaca do projeto (maquina
    # local, um operador so), mas barato de evitar. .env ja documenta
    # que a senha real tem caracteres especiais URL-encoded na
    # connection string (Fase 0) - unquote() decodifica antes de virar
    # env var, que espera o valor literal, nao percent-encoded.
    partes = urlparse(settings.database_url)
    senha = unquote(partes.password) if partes.password else None
    env_pg_dump = {**os.environ}
    if senha:
        env_pg_dump["PGPASSWORD"] = senha

    args = ["pg_dump", "-h", partes.hostname or "", "-U", partes.username or "", "-Fc", "-f", str(destino)]
    if partes.port:
        args += ["-p", str(partes.port)]
    args.append((partes.path or "/").lstrip("/"))

    resultado = subprocess.run(args, capture_output=True, text=True, env=env_pg_dump)
    if resultado.returncode != 0:
        stderr_seguro = _sanitizar(resultado.stderr, senha)[-500:]
        return ResultadoEtapa(status="falhou", detalhe={"motivo": "pg_dump_falhou", "stderr": stderr_seguro})

    tamanho_mb = round(destino.stat().st_size / (1024 * 1024), 2)
    return ResultadoEtapa(status="ok", itens_ok=1, detalhe={"arquivo": str(destino), "tamanho_mb": tamanho_mb})


def main() -> int:
    resultado = executar()
    if resultado.status == "ok":
        print(f"Backup gravado: {resultado.detalhe['arquivo']} ({resultado.detalhe['tamanho_mb']} MB)")
        return 0
    print(f"Backup falhou: {resultado.detalhe.get('motivo')}")
    if "stderr" in resultado.detalhe:
        print(resultado.detalhe["stderr"])
    return 1


if __name__ == "__main__":
    sys.exit(main())
