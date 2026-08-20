from decimal import Decimal

import pytest

from app.settlement.engine import FixtureEncerrada, FixtureStatTime, PickParaLiquidar, Resolution, liquidar


def _pick(mercado, selecao, linha=None, time_casa="Cruzeiro", time_fora="Mirassol") -> PickParaLiquidar:
    return PickParaLiquidar(
        pick_id="pick-1", mercado=mercado, selecao=selecao, linha=linha, time_casa=time_casa, time_fora=time_fora
    )


def _fixture(placar_casa, placar_fora, status="encerrada") -> FixtureEncerrada:
    return FixtureEncerrada(fixture_id="fix-1", status=status, placar_casa=placar_casa, placar_fora=placar_fora)


# --- dispatch: status incondicional e mercado sem resolver ------------------


@pytest.mark.parametrize("status", ["adiada", "cancelada"])
def test_liquidar_status_incondicional_e_void_mesmo_com_selecao_qualquer(status):
    pick = _pick("1x2", "isso nao deveria nem importar")
    resultado = liquidar(pick, _fixture(0, 0, status=status))
    assert resultado == Resolution("void", {"motivo": "fixture_status", "status": status})


def test_liquidar_mercado_sem_resolver_e_nao_liquidavel():
    pick = _pick("outro", "Escanteio do primeiro time a marcar")
    resultado = liquidar(pick, _fixture(1, 0))
    assert resultado.resultado == "nao_liquidavel"
    assert resultado.evidencia["motivo"] == "mercado_sem_resolver"


def test_liquidar_fixture_sem_placar_e_nao_liquidavel():
    pick = _pick("1x2", "Home win")
    resultado = liquidar(pick, _fixture(None, None))
    assert resultado.resultado == "nao_liquidavel"


@pytest.mark.parametrize("status", ["agendada", "ao_vivo"])
def test_liquidar_fixture_nao_encerrada_e_nao_liquidavel_mesmo_com_placar(status):
    # Defesa em profundidade (achado do code-reviewer): nao confiar so no
    # invariante de que collect_results.py so grava placar quando
    # status="encerrada" - esse modulo checa por conta propria.
    pick = _pick("1x2", "Home win")
    resultado = liquidar(pick, _fixture(1, 0, status=status))
    assert resultado.resultado == "nao_liquidavel"
    assert resultado.evidencia["motivo"] == "fixture_nao_encerrada"


def test_liquidar_selecao_nao_reconhecida_nunca_vira_red():
    pick = _pick("1x2", "texto sem padrao nenhum")
    resultado = liquidar(pick, _fixture(1, 0))
    assert resultado.resultado == "nao_liquidavel"


# --- 1x2 (incluindo dupla chance e DNB) --------------------------------------


def test_1x2_vitoria_casa_green():
    resultado = liquidar(_pick("1x2", "Home win"), _fixture(2, 1))
    assert resultado.resultado == "green"


def test_1x2_vitoria_casa_mas_selecao_era_fora_red():
    resultado = liquidar(_pick("1x2", "Away win"), _fixture(2, 1))
    assert resultado.resultado == "red"


def test_1x2_empate():
    resultado = liquidar(_pick("1x2", "Empate"), _fixture(1, 1))
    assert resultado.resultado == "green"


def test_1x2_vitoria_do_time_por_nome():
    resultado = liquidar(_pick("1x2", "Vitória do Cruzeiro"), _fixture(2, 0))
    assert resultado.resultado == "green"


@pytest.mark.parametrize(
    "par,placar,esperado",
    [
        ("1X", (1, 1), "green"),
        ("1X", (2, 0), "green"),
        ("1X", (0, 2), "red"),
        ("X2", (1, 1), "green"),
        ("X2", (0, 2), "green"),
        ("X2", (2, 0), "red"),
        ("12", (2, 0), "green"),
        ("12", (0, 2), "green"),
        ("12", (1, 1), "red"),
    ],
)
def test_1x2_dupla_chance(par, placar, esperado):
    resultado = liquidar(_pick("1x2", par), _fixture(*placar))
    assert resultado.resultado == esperado


def test_1x2_dnb_empate_e_void():
    resultado = liquidar(_pick("1x2", "Cruzeiro DNB"), _fixture(1, 1))
    assert resultado.resultado == "void"


def test_1x2_dnb_lado_vence_e_green():
    resultado = liquidar(_pick("1x2", "Cruzeiro DNB"), _fixture(2, 0))
    assert resultado.resultado == "green"


def test_1x2_dnb_lado_perde_e_red():
    resultado = liquidar(_pick("1x2", "Cruzeiro DNB"), _fixture(0, 2))
    assert resultado.resultado == "red"


def test_1x2_evidencia_traz_placar_e_vencedor():
    resultado = liquidar(_pick("1x2", "Home win"), _fixture(3, 1))
    assert resultado.evidencia["placar_casa"] == 3
    assert resultado.evidencia["placar_fora"] == 1
    assert resultado.evidencia["vencedor"] == "casa"


# --- ambas marcam -------------------------------------------------------------


def test_ambas_marcam_sim_e_bate():
    resultado = liquidar(_pick("ambas_marcam", "Ambas Marcam - Sim"), _fixture(1, 1))
    assert resultado.resultado == "green"


def test_ambas_marcam_sim_mas_um_time_nao_marcou():
    resultado = liquidar(_pick("ambas_marcam", "Ambas Marcam - Sim"), _fixture(1, 0))
    assert resultado.resultado == "red"


def test_ambas_marcam_nao_e_bate():
    resultado = liquidar(_pick("ambas_marcam", "Ambas Marcam - Não"), _fixture(1, 0))
    assert resultado.resultado == "green"


def test_ambas_marcam_selecao_ambigua_nao_liquidavel():
    resultado = liquidar(_pick("ambas_marcam", "BTTS"), _fixture(1, 0))
    assert resultado.resultado == "nao_liquidavel"


def test_ambas_marcam_fixture_sem_placar_nao_liquidavel():
    resultado = liquidar(_pick("ambas_marcam", "Ambas Marcam - Sim"), _fixture(None, None))
    assert resultado.resultado == "nao_liquidavel"


# --- over/under gols -----------------------------------------------------------


def test_over_under_linha_meia_ganha():
    resultado = liquidar(_pick("over_under", "Mais de 2.5 gols"), _fixture(2, 1))
    assert resultado.resultado == "green"


def test_over_under_linha_meia_perde():
    resultado = liquidar(_pick("over_under", "Mais de 2.5 gols"), _fixture(1, 1))
    assert resultado.resultado == "red"


def test_over_under_linha_inteira_void_na_linha_exata():
    resultado = liquidar(_pick("over_under", "Mais de 2 gols"), _fixture(1, 1))
    assert resultado.resultado == "void"


def test_over_under_linha_inteira_ganha_acima():
    resultado = liquidar(_pick("over_under", "Mais de 2 gols"), _fixture(2, 1))
    assert resultado.resultado == "green"


def test_over_under_linha_quebrada_275_meio_green():
    # Achado real da spec (secao SDA): "Mais 2.75 gols" com 3 gols e'
    # meio green - metade da aposta bate a linha 2.5, metade empurra na 3.0.
    resultado = liquidar(_pick("over_under", "Mais de 2.75 gols"), _fixture(2, 1))
    assert resultado.resultado == "meio_green"


def test_over_under_linha_quebrada_225_under_meio_green():
    resultado = liquidar(_pick("over_under", "Menos de 2.25 gols"), _fixture(1, 1))
    assert resultado.resultado == "meio_green"


def test_over_under_linha_quebrada_225_under_red_quando_total_estoura():
    resultado = liquidar(_pick("over_under", "Menos de 2.25 gols"), _fixture(2, 1))
    assert resultado.resultado == "red"


@pytest.mark.parametrize(
    "linha_texto,total,esperado",
    [
        ("0.25", 0, "meio_red"), ("0.25", 1, "green"),
        ("0.75", 0, "red"), ("0.75", 1, "meio_green"),
        ("1.25", 1, "meio_red"), ("1.25", 2, "green"),
        ("1.75", 1, "red"), ("1.75", 2, "meio_green"),
        ("4.75", 4, "red"), ("4.75", 5, "meio_green"),
    ],
)
def test_over_under_todos_os_quartos_de_linha(linha_texto, total, esperado):
    # Spec: "Escreva teste para cada quarto de linha entre 0.25 e 4.75".
    placar_casa = total // 2
    placar_fora = total - placar_casa
    resultado = liquidar(_pick("over_under", f"Mais de {linha_texto} gols"), _fixture(placar_casa, placar_fora))
    assert resultado.resultado == esperado


def test_over_under_fixture_sem_placar_nao_liquidavel():
    resultado = liquidar(_pick("over_under", "Mais de 2.5 gols"), _fixture(None, None))
    assert resultado.resultado == "nao_liquidavel"


def test_over_under_selecao_sem_linha_nao_liquidavel():
    resultado = liquidar(_pick("over_under", "Ambas marcam sim"), _fixture(1, 1))
    assert resultado.resultado == "nao_liquidavel"


def test_over_under_linha_da_coluna_pick_tem_prioridade_sobre_texto():
    # pick.linha e' a fonte de verdade quando presente; o texto de
    # `selecao` so fornece a direcao aqui.
    pick = _pick("over_under", "Mais de 999 gols", linha=Decimal("2.5"))
    resultado = liquidar(pick, _fixture(2, 1))
    assert resultado.resultado == "green"
    assert resultado.evidencia["linha"] == "2.5"


def test_over_under_linha_malformada_nao_chuta():
    pick = _pick("over_under", "Mais de 2.1 gols")
    resultado = liquidar(pick, _fixture(3, 0))
    assert resultado.resultado == "nao_liquidavel"
    assert resultado.evidencia["motivo"] == "linha_malformada"


# --- handicap (europeu e asiatico) --------------------------------------------


def test_handicap_fixture_sem_placar_nao_liquidavel():
    resultado = liquidar(_pick("handicap", "casa -1"), _fixture(None, None))
    assert resultado.resultado == "nao_liquidavel"


def test_handicap_europeu_push_na_linha_exata():
    # Casa -1, vence por exatamente 1 -> devolve o stake.
    resultado = liquidar(_pick("handicap", "casa -1"), _fixture(2, 1))
    assert resultado.resultado == "void"


def test_handicap_europeu_ganha_cobrindo_a_linha():
    resultado = liquidar(_pick("handicap", "casa -1"), _fixture(3, 1))
    assert resultado.resultado == "green"


def test_handicap_europeu_perde_sem_cobrir():
    resultado = liquidar(_pick("handicap", "casa -1"), _fixture(1, 1))
    assert resultado.resultado == "red"


def test_handicap_asiatico_meio_red_no_quarto_inferior():
    # Casa -1.25, vence por 1: cobre a metade -1.0 (push) mas nao a -1.5
    # (perde) -> meio red.
    resultado = liquidar(_pick("handicap", "casa -1.25"), _fixture(2, 1))
    assert resultado.resultado == "meio_red"


def test_handicap_asiatico_meio_green_no_quarto_superior():
    # Casa -0.75, vence por 1: a metade -1.00 e' push exato (venceu por
    # exatamente 1), a metade -0.50 ganha -> meio green, nao green cheio.
    resultado = liquidar(_pick("handicap", "casa -0.75"), _fixture(2, 1))
    assert resultado.resultado == "meio_green"


def test_handicap_asiatico_time_de_fora_favorito_com_linha_negativa():
    # Fora -1.25, vence por 2: margem (2) cobre as duas metades (-1.00 e
    # -1.50) com folga -> green cheio.
    resultado = liquidar(_pick("handicap", "fora -1.25"), _fixture(0, 2))
    assert resultado.resultado == "green"


def test_handicap_time_azarao_com_linha_positiva_ganha_perdendo_dentro_da_margem():
    resultado = liquidar(_pick("handicap", "fora +1.5"), _fixture(2, 1))
    assert resultado.resultado == "green"


def test_handicap_selecao_ambigua_nao_liquidavel():
    pick = _pick("handicap", "Atletico -1.5", time_casa="Atletico-MG", time_fora="Atletico-GO")
    resultado = liquidar(pick, _fixture(2, 0))
    assert resultado.resultado == "nao_liquidavel"


def test_handicap_linha_da_coluna_pick_tem_prioridade_sobre_texto():
    # Mesmo helper (_linha_efetiva) que over/under usa - regressao
    # dedicada pedida na revisao, ja que handicap e' o mercado onde um
    # sinal errado entre `linha` e `lado` seria mais facil de passar
    # despercebido quando a coluna picks.linha comecar a ser escrita.
    pick = _pick("handicap", "casa -1", linha=Decimal("-1.5"))
    resultado = liquidar(pick, _fixture(2, 1))
    assert resultado.resultado == "red"
    assert resultado.evidencia["linha"] == "-1.5"


def test_handicap_linha_malformada_nao_chuta():
    pick = _pick("handicap", "casa -1.1")
    resultado = liquidar(pick, _fixture(2, 0))
    assert resultado.resultado == "nao_liquidavel"
    assert resultado.evidencia["motivo"] == "linha_malformada"


# --- escanteios e cartoes (fixture_stats) --------------------------------------


def _stat(escanteios=None, amarelos=None, vermelhos=None) -> FixtureStatTime:
    return FixtureStatTime(escanteios=escanteios, cartoes_amarelos=amarelos, cartoes_vermelhos=vermelhos)


def test_escanteios_linha_meia_ganha():
    stats = [_stat(escanteios=5), _stat(escanteios=4)]
    resultado = liquidar(_pick("escanteios", "Mais de 8.5 escanteios"), _fixture(1, 0), stats)
    assert resultado.resultado == "green"
    assert resultado.evidencia["total"] == "9"


def test_escanteios_linha_meia_perde():
    stats = [_stat(escanteios=4), _stat(escanteios=4)]
    resultado = liquidar(_pick("escanteios", "Mais de 8.5 escanteios"), _fixture(1, 0), stats)
    assert resultado.resultado == "red"


def test_escanteios_linha_quebrada_meio_green():
    stats = [_stat(escanteios=5), _stat(escanteios=4)]
    resultado = liquidar(_pick("escanteios", "Mais de 8.75 escanteios"), _fixture(1, 0), stats)
    assert resultado.resultado == "meio_green"


def test_escanteios_sem_stats_nao_liquidavel():
    resultado = liquidar(_pick("escanteios", "Mais de 8.5 escanteios"), _fixture(1, 0), [])
    assert resultado.resultado == "nao_liquidavel"
    assert resultado.evidencia["motivo"] == "stats_incompletos"


def test_escanteios_cobertura_parcial_um_time_faltando_nao_liquidavel():
    # "depende de cobertura" (spec) - um time sem o stat nunca vira
    # total parcial silencioso.
    stats = [_stat(escanteios=5), _stat(escanteios=None)]
    resultado = liquidar(_pick("escanteios", "Mais de 8.5 escanteios"), _fixture(1, 0), stats)
    assert resultado.resultado == "nao_liquidavel"
    assert resultado.evidencia["motivo"] == "stats_incompletos"


def test_escanteios_apenas_um_time_no_stats_nao_liquidavel():
    stats = [_stat(escanteios=9)]
    resultado = liquidar(_pick("escanteios", "Mais de 8.5 escanteios"), _fixture(1, 0), stats)
    assert resultado.resultado == "nao_liquidavel"
    assert resultado.evidencia["motivo"] == "stats_incompletos"


def test_escanteios_mais_de_duas_linhas_de_stats_nao_liquidavel():
    # Achado do code-reviewer: `stats` nao carrega identidade de time,
    # entao mais de 2 linhas (ex.: fan-out de join, duplicata de time)
    # nunca deve ser somado como se fosse um total valido.
    stats = [_stat(escanteios=5), _stat(escanteios=4), _stat(escanteios=3)]
    resultado = liquidar(_pick("escanteios", "Mais de 8.5 escanteios"), _fixture(1, 0), stats)
    assert resultado.resultado == "nao_liquidavel"
    assert resultado.evidencia["motivo"] == "stats_incompletos"


def test_cartoes_total_soma_amarelo_e_vermelho_dos_dois_times():
    stats = [_stat(amarelos=2, vermelhos=0), _stat(amarelos=1, vermelhos=1)]
    resultado = liquidar(_pick("cartoes", "Mais de 3.5 cartões"), _fixture(1, 0), stats)
    assert resultado.resultado == "green"
    assert resultado.evidencia["total"] == "4"


def test_cartoes_linha_quebrada_meio_green():
    stats = [_stat(amarelos=2, vermelhos=0), _stat(amarelos=1, vermelhos=1)]
    resultado = liquidar(_pick("cartoes", "Mais de 3.75 cartões"), _fixture(1, 0), stats)
    assert resultado.resultado == "meio_green"


def test_cartoes_cobertura_parcial_nao_liquidavel():
    stats = [_stat(amarelos=2, vermelhos=0), _stat(amarelos=1, vermelhos=None)]
    resultado = liquidar(_pick("cartoes", "Mais de 3.5 cartões"), _fixture(1, 0), stats)
    assert resultado.resultado == "nao_liquidavel"
    assert resultado.evidencia["motivo"] == "stats_incompletos"


def test_escanteios_direcao_under():
    stats = [_stat(escanteios=4), _stat(escanteios=4)]
    resultado = liquidar(_pick("escanteios", "Menos de 8.5 escanteios"), _fixture(1, 0), stats)
    assert resultado.resultado == "green"


def test_escanteios_selecao_nao_reconhecida_nao_liquidavel():
    stats = [_stat(escanteios=5), _stat(escanteios=4)]
    resultado = liquidar(_pick("escanteios", "Ambas marcam sim"), _fixture(1, 0), stats)
    assert resultado.resultado == "nao_liquidavel"
    assert resultado.evidencia["motivo"] == "selecao_nao_reconhecida"


def test_escanteios_linha_malformada_nao_chuta():
    stats = [_stat(escanteios=5), _stat(escanteios=4)]
    resultado = liquidar(_pick("escanteios", "Mais de 8.1 escanteios"), _fixture(1, 0), stats)
    assert resultado.resultado == "nao_liquidavel"
    assert resultado.evidencia["motivo"] == "linha_malformada"


def test_cartoes_condicao_por_time_nunca_liquida_como_total():
    stats = [_stat(amarelos=2, vermelhos=0), _stat(amarelos=2, vermelhos=0)]
    pick = _pick("cartoes", "Ambas as equipes recebem 2 cartões ou mais")
    resultado = liquidar(pick, _fixture(1, 0), stats)
    assert resultado.resultado == "nao_liquidavel"
    assert resultado.evidencia["motivo"] == "condicao_por_time_nao_suportada"


# --- determinismo ---------------------------------------------------------------


def test_liquidar_e_puro_mesmo_input_mesmo_resultado():
    pick = _pick("over_under", "Mais de 2.75 gols")
    fixture = _fixture(2, 1)
    assert liquidar(pick, fixture) == liquidar(pick, fixture)
