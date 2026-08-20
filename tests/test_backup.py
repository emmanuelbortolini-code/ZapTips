import subprocess
from dataclasses import dataclass

import scripts.backup as backup


@dataclass
class _SettingsFake:
    database_url: str = "postgresql://user:senha_secreta@host:5432/db"


def test_sanitizar_remove_a_database_url_do_texto():
    texto = "connection failed: postgresql://user:senha_secreta@host/db"
    assert "senha_secreta" not in backup._sanitizar(texto, "postgresql://user:senha_secreta@host/db")


def test_executar_sem_database_url_falha_sem_chamar_pg_dump(monkeypatch):
    monkeypatch.setattr(backup, "get_settings", lambda: _SettingsFake(database_url=""))
    resultado = backup.executar()
    assert resultado.status == "falhou"
    assert resultado.detalhe["motivo"] == "database_url_vazia"


def test_executar_sem_pg_dump_no_path_falha(monkeypatch):
    monkeypatch.setattr(backup, "get_settings", lambda: _SettingsFake())
    monkeypatch.setattr(backup.shutil, "which", lambda nome: None)
    resultado = backup.executar()
    assert resultado.status == "falhou"
    assert resultado.detalhe["motivo"] == "pg_dump_nao_encontrado_no_path"


def test_executar_senha_vai_por_env_nunca_por_argv(monkeypatch, tmp_path):
    # Achado MEDIUM do code-reviewer: a senha nao pode aparecer em argv
    # (visivel no process list durante a execucao do pg_dump) - so via
    # PGPASSWORD no ambiente do subprocesso.
    monkeypatch.setattr(backup, "get_settings", lambda: _SettingsFake())
    monkeypatch.setattr(backup.shutil, "which", lambda nome: "/usr/bin/pg_dump")
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path)

    capturado = {}

    def _fake_run(args, capture_output, text, env):
        capturado["args"] = args
        capturado["env"] = env
        destino = args[args.index("-f") + 1]
        with open(destino, "wb") as f:
            f.write(b"conteudo de teste do dump")
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(backup.subprocess, "run", _fake_run)

    backup.executar()

    assert not any("senha_secreta" in arg for arg in capturado["args"])
    assert capturado["env"]["PGPASSWORD"] == "senha_secreta"
    assert "-h" in capturado["args"] and "host" in capturado["args"]
    assert "-U" in capturado["args"] and "user" in capturado["args"]
    assert "db" in capturado["args"]


def test_executar_pg_dump_falha_sanitiza_stderr(monkeypatch, tmp_path):
    monkeypatch.setattr(backup, "get_settings", lambda: _SettingsFake())
    monkeypatch.setattr(backup.shutil, "which", lambda nome: "/usr/bin/pg_dump")
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path)

    def _fake_run(args, capture_output, text, env):
        return subprocess.CompletedProcess(
            args, returncode=1, stdout="", stderr="erro: postgresql://user:senha_secreta@host/db inacessivel"
        )

    monkeypatch.setattr(backup.subprocess, "run", _fake_run)

    resultado = backup.executar()

    assert resultado.status == "falhou"
    assert resultado.detalhe["motivo"] == "pg_dump_falhou"
    assert "senha_secreta" not in resultado.detalhe["stderr"]


def test_executar_sucesso_grava_arquivo_e_reporta_tamanho(monkeypatch, tmp_path):
    monkeypatch.setattr(backup, "get_settings", lambda: _SettingsFake())
    monkeypatch.setattr(backup.shutil, "which", lambda nome: "/usr/bin/pg_dump")
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path)

    def _fake_run(args, capture_output, text, env):
        destino = args[args.index("-f") + 1]
        with open(destino, "wb") as f:
            f.write(b"conteudo de teste do dump")
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(backup.subprocess, "run", _fake_run)

    resultado = backup.executar()

    assert resultado.status == "ok"
    assert resultado.itens_ok == 1
    assert resultado.detalhe["tamanho_mb"] >= 0
