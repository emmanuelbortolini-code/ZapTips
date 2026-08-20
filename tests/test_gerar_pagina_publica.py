from dataclasses import dataclass
from datetime import datetime, timezone

import scripts.gerar_pagina_publica as gerar_pagina_publica
from app.relatorio_publico import DadosPublicos
from app.settlement.metricas_publicas import montar_periodos_publicos


@dataclass
class _SettingsFake:
    database_url: str = "postgresql://user:senha@host:5432/db"
    rodape_legal: str = "18+."
    banca_inicial_padrao: float = 1000
    stake_pct_padrao: float = 0.02
    stake_modo_padrao: str = "fixo"


class _ConexaoFake:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self


def _dados_publicos_vazios() -> DadosPublicos:
    from decimal import Decimal

    from app.settlement.metricas_publicas import NOME_7_DIAS, NOME_30_DIAS, NOME_DESDE_O_INICIO

    agora = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    periodos = montar_periodos_publicos(
        [], banca_inicial=Decimal("1000"), agora=agora,
        nao_liquidados_por_periodo={NOME_7_DIAS: 0, NOME_30_DIAS: 0, NOME_DESDE_O_INICIO: 0},
    )
    return DadosPublicos(periodos=tuple(periodos), curva_banca=((None, Decimal("1000")),), banca_inicial=Decimal("1000"), gerado_em=agora)


def test_executar_escreve_html_e_texto_no_diretorio_public(monkeypatch, tmp_path):
    monkeypatch.setattr(gerar_pagina_publica, "get_settings", lambda: _SettingsFake())
    monkeypatch.setattr(gerar_pagina_publica, "get_connection", lambda: _ConexaoFake())
    monkeypatch.setattr(gerar_pagina_publica, "gerar_dados_publicos", lambda cur, settings, agora: _dados_publicos_vazios())
    monkeypatch.setattr(gerar_pagina_publica, "PUBLIC_DIR", tmp_path)

    resultado = gerar_pagina_publica.executar()

    assert resultado.status == "ok"
    html_path = tmp_path / "index.html"
    texto_path = tmp_path / "resumo.txt"
    assert html_path.exists()
    assert texto_path.exists()
    assert "Banca simulada" in html_path.read_text(encoding="utf-8")
    assert "Banca simulada" in texto_path.read_text(encoding="utf-8")
    assert resultado.detalhe["arquivo_html"] == str(html_path)


def test_executar_sobrescreve_arquivos_existentes(monkeypatch, tmp_path):
    monkeypatch.setattr(gerar_pagina_publica, "get_settings", lambda: _SettingsFake())
    monkeypatch.setattr(gerar_pagina_publica, "get_connection", lambda: _ConexaoFake())
    monkeypatch.setattr(gerar_pagina_publica, "gerar_dados_publicos", lambda cur, settings, agora: _dados_publicos_vazios())
    monkeypatch.setattr(gerar_pagina_publica, "PUBLIC_DIR", tmp_path)
    (tmp_path).mkdir(exist_ok=True)
    (tmp_path / "index.html").write_text("conteudo antigo", encoding="utf-8")

    gerar_pagina_publica.executar()

    assert "conteudo antigo" not in (tmp_path / "index.html").read_text(encoding="utf-8")
