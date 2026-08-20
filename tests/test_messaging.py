from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.messaging import (
    SAUDACOES,
    ContextoFechamento,
    ContextoMensagem,
    ContextoResumoSemanal,
    PalpiteFechado,
    PalpiteNaMensagem,
    formatar_horario_local,
    formatar_variacao_sinalizada,
    renderizar_fechamento,
    renderizar_mensagem,
    renderizar_resumo_semanal,
    sortear_saudacao,
)


def _palpite(**overrides) -> PalpiteNaMensagem:
    base = dict(selecao="Menos de 2.5 gols", odd_referencia=1.85, odd_minima=1.77, fonte_publica=False, fonte=None)
    base.update(overrides)
    return PalpiteNaMensagem(**base)


def _contexto(**overrides) -> ContextoMensagem:
    base = dict(
        primeiro_nome="Emmanuel",
        time_casa="Goiás",
        time_fora="Londrina",
        competicao="Série B",
        kickoff_utc=datetime(2026, 8, 10, 22, 30, tzinfo=timezone.utc),
        fuso_horario="America/Sao_Paulo",
        transmissao="Premiere",
        palpites=(_palpite(),),
        rodape_legal="18+. Aposte com responsabilidade. Responda SAIR pra cancelar.",
    )
    base.update(overrides)
    return ContextoMensagem(**base)


def test_formatar_horario_local_converte_utc_para_fuso_do_usuario():
    kickoff = datetime(2026, 8, 10, 22, 30, tzinfo=timezone.utc)

    assert formatar_horario_local(kickoff, "America/Sao_Paulo") == "10/08 19:30"


def test_sortear_saudacao_retorna_uma_das_opcoes():
    assert sortear_saudacao() in SAUDACOES


def test_renderizar_mensagem_inclui_campos_essenciais():
    corpo = renderizar_mensagem(_contexto(), saudacao_template=SAUDACOES[0])

    assert "Goiás x Londrina" in corpo
    assert "Série B" in corpo
    assert "10/08 19:30" in corpo
    assert "Menos de 2.5 gols" in corpo
    assert "1.85" in corpo
    assert "1.77" in corpo
    assert "Emmanuel" in corpo


def test_renderizar_mensagem_rodape_legal_sempre_presente():
    corpo = renderizar_mensagem(_contexto(), saudacao_template=SAUDACOES[0])

    assert "18+. Aposte com responsabilidade. Responda SAIR pra cancelar." in corpo


def test_renderizar_mensagem_sem_rodape_legal_levanta_erro():
    contexto = _contexto(rodape_legal="")

    with pytest.raises(ValueError, match="rodape_legal"):
        renderizar_mensagem(contexto)


def test_renderizar_mensagem_sem_palpite_nenhum_levanta_erro():
    contexto = _contexto(palpites=())

    with pytest.raises(ValueError, match="palpite"):
        renderizar_mensagem(contexto)


def test_renderizar_mensagem_fonte_so_aparece_quando_fonte_publica():
    sem_fonte = renderizar_mensagem(
        _contexto(palpites=(_palpite(fonte_publica=False, fonte="Eagle Predict"),)), saudacao_template=SAUDACOES[0]
    )
    com_fonte = renderizar_mensagem(
        _contexto(palpites=(_palpite(fonte_publica=True, fonte="Eagle Predict"),)), saudacao_template=SAUDACOES[0]
    )

    assert "Fonte:" not in sem_fonte
    assert "Fonte: Eagle Predict" in com_fonte


def test_renderizar_mensagem_usa_saudacao_sorteada_quando_nao_especificada(monkeypatch):
    monkeypatch.setattr("app.messaging.sortear_saudacao", lambda: SAUDACOES[2])

    corpo = renderizar_mensagem(_contexto())

    assert "Separei esse aqui pra você" in corpo


def test_renderizar_mensagem_transmissao_none_omite_a_linha():
    corpo = renderizar_mensagem(_contexto(transmissao=None), saudacao_template=SAUDACOES[0])

    assert "Onde assistir" not in corpo


def test_renderizar_mensagem_agrupa_multiplos_palpites_da_mesma_fixture():
    palpites = (
        _palpite(selecao="Menos de 2.5 gols", odd_referencia=1.85, odd_minima=1.77),
        _palpite(selecao="Ambas marcam - Nao", odd_referencia=1.60, odd_minima=1.53),
    )
    corpo = renderizar_mensagem(_contexto(palpites=palpites), saudacao_template=SAUDACOES[0])

    assert "Menos de 2.5 gols" in corpo
    assert "Ambas marcam - Nao" in corpo
    assert corpo.count("Palpite:") == 2
    assert corpo.count("Odd aproximada:") == 2


# --- renderizar_fechamento (Fase 6e) -------------------------------------------


def _palpite_fechado(**overrides) -> PalpiteFechado:
    base = dict(selecao="Menos de 2.5 gols", odd=Decimal("1.77"), resultado="green")
    base.update(overrides)
    return PalpiteFechado(**base)


def _contexto_fechamento(**overrides) -> ContextoFechamento:
    base = dict(
        time_casa="Goiás", time_fora="Londrina", placar_casa=1, placar_fora=0,
        palpites=(_palpite_fechado(),), banca_atual=Decimal("1017.70"), variacao=Decimal("17.70"),
        rodape_legal="18+. Aposte com responsabilidade. Responda SAIR pra cancelar.",
    )
    base.update(overrides)
    return ContextoFechamento(**base)


def test_formatar_variacao_sinalizada_positiva_tem_sinal_de_mais():
    assert formatar_variacao_sinalizada(Decimal("17.70")) == "+R$ 17.70"


def test_formatar_variacao_sinalizada_negativa_usa_sinal_do_decimal():
    assert formatar_variacao_sinalizada(Decimal("-8.00")) == "R$ -8.00"


def test_formatar_variacao_sinalizada_zero_sem_sinal():
    assert formatar_variacao_sinalizada(Decimal("0.00")) == "R$ 0.00"


def test_renderizar_fechamento_inclui_placar_e_times():
    corpo = renderizar_fechamento(_contexto_fechamento())
    assert "Goiás 1 x 0 Londrina" in corpo


def test_renderizar_fechamento_periodo_coberto_e_a_propria_partida():
    # Regra dura da spec: "resultado passado aparece sempre com o
    # periodo que ele cobre". Pra fechamento (diferente de um resumo
    # semanal, que cobriria uma janela de dias), o "periodo" e' a
    # propria partida - identificada de forma inequivoca por
    # time_casa/placar/time_fora, sempre presentes. Sem essa
    # identificacao, "Banca simulada: R$ 1017.70" ficaria sem contexto
    # de qual evento causou a mudanca.
    corpo = renderizar_fechamento(_contexto_fechamento(time_casa="Goiás", time_fora="Londrina", placar_casa=1, placar_fora=0))
    assert "Goiás" in corpo and "Londrina" in corpo and "1" in corpo and "0" in corpo


def test_renderizar_fechamento_banca_sempre_qualificada_como_simulada():
    # Regra dura da spec: "A palavra 'simulada' acompanha toda mencao a
    # banca" - obrigatoria no template, nao configuravel.
    corpo = renderizar_fechamento(_contexto_fechamento())
    assert "Banca simulada: R$ 1017.70" in corpo
    assert "Banca:" not in corpo  # nunca sem o qualificador


def test_renderizar_fechamento_mostra_variacao_sinalizada():
    corpo = renderizar_fechamento(_contexto_fechamento(variacao=Decimal("17.70")))
    assert "+R$ 17.70" in corpo


@pytest.mark.parametrize(
    "resultado,emoji,texto",
    [
        ("green", "✅", "Green"),
        ("meio_green", "🟢", "Meio Green"),
        ("void", "↩️", "Void"),
        ("meio_red", "🟠", "Meio Red"),
        ("red", "❌", "Red"),
    ],
)
def test_renderizar_fechamento_emoji_e_texto_por_resultado(resultado, emoji, texto):
    corpo = renderizar_fechamento(_contexto_fechamento(palpites=(_palpite_fechado(resultado=resultado),)))
    assert emoji in corpo
    assert texto in corpo


def test_renderizar_fechamento_agrupa_multiplos_palpites_da_mesma_fixture():
    palpites = (
        _palpite_fechado(selecao="Menos de 2.5 gols", resultado="green"),
        _palpite_fechado(selecao="Ambas marcam - Nao", resultado="red"),
    )
    corpo = renderizar_fechamento(_contexto_fechamento(palpites=palpites))
    assert "Menos de 2.5 gols" in corpo
    assert "Ambas marcam - Nao" in corpo
    assert corpo.count("Palpite:") == 2


def test_renderizar_fechamento_rodape_legal_sempre_presente():
    corpo = renderizar_fechamento(_contexto_fechamento())
    assert "18+. Aposte com responsabilidade. Responda SAIR pra cancelar." in corpo


def test_renderizar_fechamento_sem_rodape_legal_levanta_erro():
    with pytest.raises(ValueError, match="rodape_legal"):
        renderizar_fechamento(_contexto_fechamento(rodape_legal=""))


def test_renderizar_fechamento_sem_palpite_nenhum_levanta_erro():
    with pytest.raises(ValueError, match="palpite"):
        renderizar_fechamento(_contexto_fechamento(palpites=()))


# Regra dura da spec (secao 6e): "Nenhum texto de projecao, previsao ou
# expectativa de retorno futuro" - restricao motivada por regulacao de
# publicidade de apostas no Brasil, nao so estilo. Guarda estrutural
# contra uma edicao futura do template introduzir esse tipo de
# linguagem sem querer (achado MEDIUM do code-reviewer: essa regra so
# valia "por a template ser estatica hoje", sem nenhum teste proprio).
_TERMOS_DE_PROJECAO_PROIBIDOS = (
    "vai ", "vamos ", "vai continuar", "vai crescer", "vai subir", "vai render",
    "garantid", "garantia", "previsão", "previsao", "projeção", "projecao", "expectativa",
)


def test_renderizar_fechamento_template_nunca_usa_linguagem_de_projecao():
    corpo = renderizar_fechamento(_contexto_fechamento())
    corpo_normalizado = corpo.lower()
    for termo in _TERMOS_DE_PROJECAO_PROIBIDOS:
        assert termo not in corpo_normalizado, f"linguagem de projecao encontrada: {termo!r}"


# --- renderizar_resumo_semanal (Fase 6e) ---------------------------------------


def _contexto_resumo_semanal(**overrides) -> ContextoResumoSemanal:
    base = dict(
        primeiro_nome="Emmanuel", inicio_semana="10/08", fim_semana="16/08",
        total_palpites=5, greens=3, reds=2, banca_inicial=Decimal("1000"), banca_atual=Decimal("1040"),
        roi=Decimal("0.08"), nao_liquidados=0,
        rodape_legal="18+. Aposte com responsabilidade. Responda SAIR pra cancelar.",
    )
    base.update(overrides)
    return ContextoResumoSemanal(**base)


def test_renderizar_resumo_semanal_inclui_contagem_de_palpites_greens_reds():
    corpo = renderizar_resumo_semanal(_contexto_resumo_semanal())
    assert "5 palpites, 3 greens e 2 reds" in corpo


def test_renderizar_resumo_semanal_periodo_coberto_e_a_janela_da_semana():
    corpo = renderizar_resumo_semanal(_contexto_resumo_semanal(inicio_semana="10/08", fim_semana="16/08"))
    assert "10/08" in corpo and "16/08" in corpo


def test_renderizar_resumo_semanal_banca_sempre_qualificada_como_simulada():
    corpo = renderizar_resumo_semanal(_contexto_resumo_semanal())
    assert "Banca simulada: R$ 1000.00 -> R$ 1040.00" in corpo
    assert "Banca:" not in corpo


def test_renderizar_resumo_semanal_mostra_roi_formatado_em_percentual():
    corpo = renderizar_resumo_semanal(_contexto_resumo_semanal(roi=Decimal("0.08")))
    assert "ROI: 8.00%" in corpo


def test_renderizar_resumo_semanal_sem_roi_omite_a_linha():
    corpo = renderizar_resumo_semanal(_contexto_resumo_semanal(roi=None))
    assert "ROI" not in corpo


def test_renderizar_resumo_semanal_mostra_nao_liquidados_quando_houver():
    corpo = renderizar_resumo_semanal(_contexto_resumo_semanal(nao_liquidados=2))
    assert "2 palpites sem resultado confirmado" in corpo


def test_renderizar_resumo_semanal_omite_linha_de_nao_liquidados_quando_zero():
    corpo = renderizar_resumo_semanal(_contexto_resumo_semanal(nao_liquidados=0))
    assert "sem resultado confirmado" not in corpo


def test_renderizar_resumo_semanal_rodape_legal_sempre_presente():
    corpo = renderizar_resumo_semanal(_contexto_resumo_semanal())
    assert "18+. Aposte com responsabilidade. Responda SAIR pra cancelar." in corpo


def test_renderizar_resumo_semanal_sem_rodape_legal_levanta_erro():
    with pytest.raises(ValueError, match="rodape_legal"):
        renderizar_resumo_semanal(_contexto_resumo_semanal(rodape_legal=""))


def test_renderizar_resumo_semanal_sem_palpite_nenhum_levanta_erro():
    with pytest.raises(ValueError, match="palpite"):
        renderizar_resumo_semanal(_contexto_resumo_semanal(total_palpites=0))


def test_renderizar_resumo_semanal_template_nunca_usa_linguagem_de_projecao():
    corpo = renderizar_resumo_semanal(_contexto_resumo_semanal())
    corpo_normalizado = corpo.lower()
    for termo in _TERMOS_DE_PROJECAO_PROIBIDOS:
        assert termo not in corpo_normalizado, f"linguagem de projecao encontrada: {termo!r}"
