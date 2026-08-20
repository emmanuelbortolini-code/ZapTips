import sys
from dataclasses import dataclass
from datetime import date

import scripts.gerar_resumo_semanal as gerar_resumo_semanal


@dataclass
class _SettingsFake:
    database_url: str = "postgresql://user:senha@host:5432/db"
    rodape_legal: str = "18+."


class _ConexaoFake:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self

    def commit(self):
        pass


def test_executar_com_inicio_semana_explicito_usa_a_data_direto_sem_normalizar(monkeypatch):
    # Achado HIGH do code-reviewer: `executar()` so pode normalizar
    # (segunda_da_semana_anterior) quando `inicio_semana` NAO e' passado -
    # normalizar de novo uma data ja explicita desloca a semana gerada.
    monkeypatch.setattr(gerar_resumo_semanal, "get_settings", lambda: _SettingsFake())
    monkeypatch.setattr(gerar_resumo_semanal, "get_connection", lambda: _ConexaoFake())
    capturado = {}
    monkeypatch.setattr(
        gerar_resumo_semanal, "gerar_resumos_semanais",
        lambda cur, inicio_semana, rodape, settings: capturado.setdefault("inicio_semana", inicio_semana) or 0,
    )

    resultado = gerar_resumo_semanal.executar(date(2026, 8, 10))

    assert capturado["inicio_semana"] == date(2026, 8, 10)
    assert resultado.detalhe["inicio_semana"] == "2026-08-10"


def test_main_com_flag_inicio_semana_nao_normaliza_duas_vezes(monkeypatch, capsys):
    # Regressao direta do bug: `main()` chamava
    # segunda_da_semana_anterior(args.inicio_semana) e depois `executar()`
    # normalizava de novo - `--inicio-semana 2026-08-10` (semana de
    # 10-16/08) gerava silenciosamente a semana de 03-09/08.
    monkeypatch.setattr(gerar_resumo_semanal, "get_settings", lambda: _SettingsFake())
    monkeypatch.setattr(gerar_resumo_semanal, "get_connection", lambda: _ConexaoFake())
    capturado = {}
    monkeypatch.setattr(
        gerar_resumo_semanal, "gerar_resumos_semanais",
        lambda cur, inicio_semana, rodape, settings: capturado.setdefault("inicio_semana", inicio_semana) or 0,
    )
    monkeypatch.setattr(sys, "argv", ["prog", "--inicio-semana", "2026-08-10"])

    gerar_resumo_semanal.main()

    assert capturado["inicio_semana"] == date(2026, 8, 10)


def test_executar_sem_inicio_semana_normaliza_a_partir_de_hoje(monkeypatch):
    monkeypatch.setattr(gerar_resumo_semanal, "get_settings", lambda: _SettingsFake())
    monkeypatch.setattr(gerar_resumo_semanal, "get_connection", lambda: _ConexaoFake())
    monkeypatch.setattr(gerar_resumo_semanal, "data_operacional", lambda: date(2026, 8, 17))  # segunda-feira
    capturado = {}
    monkeypatch.setattr(
        gerar_resumo_semanal, "gerar_resumos_semanais",
        lambda cur, inicio_semana, rodape, settings: capturado.setdefault("inicio_semana", inicio_semana) or 0,
    )

    gerar_resumo_semanal.executar(None)

    assert capturado["inicio_semana"] == date(2026, 8, 10)
