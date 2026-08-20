from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.pagina_publica import renderizar_html_publico, renderizar_texto_publico
from app.relatorio_publico import DadosPublicos
from app.settlement.banca import Aposta
from app.settlement.metricas import ApostaComData, calcular_metricas
from app.settlement.metricas_publicas import (
    NOME_7_DIAS,
    NOME_30_DIAS,
    NOME_DESDE_O_INICIO,
    PeriodoPublico,
    montar_curva_banca,
)

_RODAPE = "18+. Aposte com responsabilidade. Responda SAIR pra cancelar."
_GERADO_EM = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


def _aposta(pick_id, dia, odd, resultado, stake, retorno, banca_depois, seq=1) -> ApostaComData:
    aposta = Aposta(
        pick_id=pick_id, fixture_id=f"fix-{pick_id}", message_id=None, odd=Decimal(str(odd)),
        stake_valor=Decimal(str(stake)), stake_pct=Decimal("0.02"), resultado=resultado,
        retorno=Decimal(str(retorno)), banca_antes=Decimal("0"), banca_depois=Decimal(str(banca_depois)),
        sequencia=seq,
    )
    return ApostaComData(aposta=aposta, kickoff_utc=datetime(2026, 8, dia, 20, 0, tzinfo=timezone.utc))


def _dados_publicos(apostas=None, nao_liquidados=0) -> DadosPublicos:
    apostas = apostas or []
    banca_inicial = Decimal("1000")
    periodos = tuple(
        PeriodoPublico(
            nome=nome,
            metricas=calcular_metricas(apostas, banca_inicial=banca_inicial, desde=None, nao_liquidados_no_periodo=nao_liquidados),
        )
        for nome in (NOME_7_DIAS, NOME_30_DIAS, NOME_DESDE_O_INICIO)
    )
    curva = tuple(montar_curva_banca(banca_inicial, apostas))
    return DadosPublicos(periodos=periodos, curva_banca=curva, banca_inicial=banca_inicial, gerado_em=_GERADO_EM)


def test_renderizar_html_publico_banca_sempre_qualificada_como_simulada():
    html = renderizar_html_publico(_dados_publicos(), _RODAPE, Decimal("0.02"))
    assert "Banca simulada" in html
    assert "banca simulada inicial" in html.lower()


def test_renderizar_html_publico_mostra_metodologia_do_piso_publicado():
    html = renderizar_html_publico(_dados_publicos(), _RODAPE, Decimal("0.02"))
    assert "PISO publicado" in html
    assert "nunca na odd real" in html


def test_renderizar_html_publico_todo_numero_vem_com_o_periodo():
    apostas = [_aposta("p1", 10, 2.0, "green", 20, 40, 1020)]
    html = renderizar_html_publico(_dados_publicos(apostas), _RODAPE, Decimal("0.02"))
    for nome in (NOME_7_DIAS, NOME_30_DIAS, NOME_DESDE_O_INICIO):
        assert f"ROI ({nome})" in html
        assert f"Nao liquidados ({nome})" in html
        assert f"Volume ({nome})" in html


def test_renderizar_html_publico_mostra_nao_liquidados_ao_lado_do_roi():
    html = renderizar_html_publico(_dados_publicos(nao_liquidados=3), _RODAPE, Decimal("0.02"))
    assert html.count("Nao liquidados") == 3  # um por periodo
    assert ">3<" in html


def test_renderizar_html_publico_mostra_ultima_atualizacao():
    html = renderizar_html_publico(_dados_publicos(), _RODAPE, Decimal("0.02"))
    assert "18/08/2026 12:00 UTC" in html


def test_renderizar_html_publico_rodape_legal_sempre_presente():
    html = renderizar_html_publico(_dados_publicos(), _RODAPE, Decimal("0.02"))
    assert _RODAPE in html


def test_renderizar_html_publico_sem_rodape_legal_levanta_erro():
    with pytest.raises(ValueError, match="rodape_legal"):
        renderizar_html_publico(_dados_publicos(), "", Decimal("0.02"))


def test_renderizar_html_publico_sem_apostas_nao_quebra():
    html = renderizar_html_publico(_dados_publicos(), _RODAPE, Decimal("0.02"))
    assert "<svg" in html


def test_renderizar_html_publico_com_apostas_desenha_polyline():
    apostas = [_aposta("p1", 10, 2.0, "green", 20, 40, 1020), _aposta("p2", 11, 2.0, "red", 20, 0, 1000, seq=2)]
    html = renderizar_html_publico(_dados_publicos(apostas), _RODAPE, Decimal("0.02"))
    assert "<polyline" in html


_TERMOS_DE_PROJECAO_PROIBIDOS = (
    "vai ", "vamos ", "vai continuar", "vai crescer", "vai subir", "vai render",
    "garantid", "garantia", "previsão", "previsao", "projeção", "projecao", "expectativa",
)


def test_renderizar_html_publico_nunca_usa_linguagem_de_projecao():
    html = renderizar_html_publico(_dados_publicos(), _RODAPE, Decimal("0.02")).lower()
    for termo in _TERMOS_DE_PROJECAO_PROIBIDOS:
        assert termo not in html, f"linguagem de projecao encontrada: {termo!r}"


# --- renderizar_texto_publico -----------------------------------------------


def test_renderizar_texto_publico_banca_sempre_qualificada_como_simulada():
    texto = renderizar_texto_publico(_dados_publicos(), _RODAPE, Decimal("0.02"))
    assert "Banca simulada" in texto


def test_renderizar_texto_publico_todo_numero_vem_com_o_periodo():
    texto = renderizar_texto_publico(_dados_publicos(), _RODAPE, Decimal("0.02"))
    for nome in (NOME_7_DIAS, NOME_30_DIAS, NOME_DESDE_O_INICIO):
        assert f"ROI ({nome})" in texto


def test_renderizar_texto_publico_rodape_legal_sempre_presente():
    texto = renderizar_texto_publico(_dados_publicos(), _RODAPE, Decimal("0.02"))
    assert _RODAPE in texto


def test_renderizar_texto_publico_sem_rodape_legal_levanta_erro():
    with pytest.raises(ValueError, match="rodape_legal"):
        renderizar_texto_publico(_dados_publicos(), "", Decimal("0.02"))


def test_renderizar_texto_publico_nunca_usa_linguagem_de_projecao():
    texto = renderizar_texto_publico(_dados_publicos(), _RODAPE, Decimal("0.02")).lower()
    for termo in _TERMOS_DE_PROJECAO_PROIBIDOS:
        assert termo not in texto, f"linguagem de projecao encontrada: {termo!r}"
