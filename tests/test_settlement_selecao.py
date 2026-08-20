from decimal import Decimal

import pytest

from app.settlement.selecao import (
    IntencaoAmbasMarcam,
    IntencaoDNB,
    IntencaoDuplaChance,
    IntencaoHandicap,
    IntencaoTotal,
    Intencao1x2,
    eh_condicao_por_time,
    parse_1x2_ou_variantes,
    parse_ambas_marcam,
    parse_handicap,
    parse_total,
)


# --- parse_1x2_ou_variantes -------------------------------------------------


@pytest.mark.parametrize("selecao,par", [("1X", "1X"), ("X1", "1X"), ("X2", "X2"), ("2X", "X2"), ("12", "12"), ("21", "12")])
def test_parse_1x2_dupla_chance_codigos(selecao, par):
    assert parse_1x2_ou_variantes(selecao, None, None) == IntencaoDuplaChance(par=par)


def test_parse_1x2_dupla_chance_ignora_espacos():
    assert parse_1x2_ou_variantes("1 X", None, None) == IntencaoDuplaChance(par="1X")


def test_parse_1x2_home_win_literal():
    assert parse_1x2_ou_variantes("Home win", "Cruzeiro", "Mirassol") == Intencao1x2(lado="casa")


def test_parse_1x2_vitoria_do_time_da_casa():
    assert parse_1x2_ou_variantes("Vitória do Fluminense", "Fluminense", "Palmeiras") == Intencao1x2(lado="casa")


def test_parse_1x2_empate():
    assert parse_1x2_ou_variantes("Empate", None, None) == Intencao1x2(lado="empate")


def test_parse_1x2_fora_de_escopo_primeiro_tempo():
    assert parse_1x2_ou_variantes("Al Hilal vence o 1o tempo", "Al Hilal", "Zenit") is None


def test_parse_1x2_fora_de_escopo_classificacao():
    assert parse_1x2_ou_variantes("Senegal se classifica", "Senegal", "Egito") is None


def test_parse_1x2_fora_de_escopo_agregado():
    assert parse_1x2_ou_variantes("Real Madrid vence no agregado", "Real Madrid", "Man City") is None


def test_parse_1x2_fora_de_escopo_penaltis():
    assert parse_1x2_ou_variantes("Brasil vence nos penaltis", "Brasil", "Argentina") is None


def test_parse_1x2_fora_de_escopo_prorrogacao():
    assert parse_1x2_ou_variantes("Decide na prorrogacao", "Brasil", "Argentina") is None


def test_parse_1x2_dnb_time_casa_por_frase():
    resultado = parse_1x2_ou_variantes("Itabaiana para ganhar ou empatar contra Confiança", "Itabaiana", "Confiança")
    assert resultado == IntencaoDNB(lado="casa")


def test_parse_1x2_dnb_time_fora_por_frase():
    resultado = parse_1x2_ou_variantes("Confiança para ganhar ou empatar contra Itabaiana", "Itabaiana", "Confiança")
    assert resultado == IntencaoDNB(lado="fora")


def test_parse_1x2_dnb_sigla_com_nome_do_time():
    assert parse_1x2_ou_variantes("Palmeiras DNB", "Palmeiras", "Santos") == IntencaoDNB(lado="casa")


def test_parse_1x2_dnb_draw_no_bet_por_extenso():
    assert parse_1x2_ou_variantes("Santos draw no bet", "Palmeiras", "Santos") == IntencaoDNB(lado="fora")


def test_parse_1x2_dnb_empate_anula():
    assert parse_1x2_ou_variantes("Palmeiras empate anula", "Palmeiras", "Santos") == IntencaoDNB(lado="casa")


def test_parse_1x2_dnb_sem_time_identificavel_nao_chuta():
    assert parse_1x2_ou_variantes("DNB", None, None) is None


def test_parse_1x2_dnb_nenhum_time_bate_nao_chuta():
    assert parse_1x2_ou_variantes("Timão para ganhar ou empatar contra Coringão", "Palmeiras", "Santos") is None


def test_parse_1x2_texto_sem_padrao_reconhecido_nao_chuta():
    assert parse_1x2_ou_variantes("Ambas marcam", "Palmeiras", "Santos") is None


# --- parse_ambas_marcam -----------------------------------------------------


def test_parse_ambas_marcam_sim():
    assert parse_ambas_marcam("Ambas Marcam - Sim") == IntencaoAmbasMarcam(sim=True)


def test_parse_ambas_marcam_yes():
    assert parse_ambas_marcam("BTTS - Yes") == IntencaoAmbasMarcam(sim=True)


def test_parse_ambas_marcam_nao():
    assert parse_ambas_marcam("Ambas Marcam - Não") == IntencaoAmbasMarcam(sim=False)


def test_parse_ambas_marcam_no():
    assert parse_ambas_marcam("BTTS - No") == IntencaoAmbasMarcam(sim=False)


def test_parse_ambas_marcam_sem_separador():
    assert parse_ambas_marcam("Sim") == IntencaoAmbasMarcam(sim=True)


def test_parse_ambas_marcam_btts_sozinho_nao_chuta():
    # "BTTS" sozinho, sem sim/nao explicito, e' ambiguo - nunca presumir
    # que significa "sim".
    assert parse_ambas_marcam("BTTS") is None


def test_parse_ambas_marcam_texto_nao_reconhecido():
    assert parse_ambas_marcam("Mais de 2.5 gols") is None


# --- parse_total -------------------------------------------------------------


def test_parse_total_mais_de_ponto():
    assert parse_total("Mais de 2.5 gols") == IntencaoTotal(direcao="over", linha=Decimal("2.5"))


def test_parse_total_menos_de_virgula():
    assert parse_total("Menos de 2,25") == IntencaoTotal(direcao="under", linha=Decimal("2.25"))


def test_parse_total_over():
    assert parse_total("Over 2.5") == IntencaoTotal(direcao="over", linha=Decimal("2.5"))


def test_parse_total_under():
    assert parse_total("Under 1.5") == IntencaoTotal(direcao="under", linha=Decimal("1.5"))


def test_parse_total_acima_de_escanteios():
    assert parse_total("Acima de 8.5 escanteios") == IntencaoTotal(direcao="over", linha=Decimal("8.5"))


def test_parse_total_abaixo_de_cartoes():
    assert parse_total("Abaixo de 3.5 cartões") == IntencaoTotal(direcao="under", linha=Decimal("3.5"))


def test_parse_total_linha_quebrada_quarto():
    assert parse_total("Mais de 2.75 gols") == IntencaoTotal(direcao="over", linha=Decimal("2.75"))
    assert parse_total("Menos de 2.25 gols") == IntencaoTotal(direcao="under", linha=Decimal("2.25"))


def test_parse_total_sem_numero_nao_chuta():
    assert parse_total("Ambas marcam sim") is None


def test_parse_total_numero_malformado_nao_chuta():
    assert parse_total("Mais de . gols") is None


def test_parse_total_fora_de_escopo_primeiro_tempo_nao_chuta():
    # Achado do code-reviewer (Fase 6a): sem essa guarda, "Mais de 0.5
    # gols no 1o tempo" seria liquidado contra o placar do jogo inteiro.
    assert parse_total("Mais de 0.5 gols no 1o tempo") is None


def test_parse_total_fora_de_escopo_prorrogacao_nao_chuta():
    assert parse_total("Mais de 1.5 gols na prorrogacao") is None


# --- parse_handicap ------------------------------------------------------


def test_parse_handicap_home_win_com_sigla_hc():
    assert parse_handicap("Home win HC-1.5", None, None) == IntencaoHandicap(lado="casa", linha=Decimal("-1.5"))


def test_parse_handicap_away_win_com_sigla_ha():
    assert parse_handicap("Away win HA+1.5", None, None) == IntencaoHandicap(lado="fora", linha=Decimal("1.5"))


def test_parse_handicap_literal_casa():
    assert parse_handicap("casa -1.5", None, None) == IntencaoHandicap(lado="casa", linha=Decimal("-1.5"))


def test_parse_handicap_literal_fora():
    assert parse_handicap("fora +1.5", None, None) == IntencaoHandicap(lado="fora", linha=Decimal("1.5"))


def test_parse_handicap_nome_do_time_casa():
    assert parse_handicap("Cruzeiro -1,5", "Cruzeiro", "Mirassol") == IntencaoHandicap(lado="casa", linha=Decimal("-1.5"))


def test_parse_handicap_nome_do_time_fora():
    assert parse_handicap("Palmeiras +1.5", "Fluminense", "Palmeiras") == IntencaoHandicap(lado="fora", linha=Decimal("1.5"))


def test_parse_handicap_ambiguidade_dois_times_batem_nao_chuta():
    # Mesma familia de ambiguidade ja documentada em app.odds_resolution:
    # "Atletico-MG"/"Atletico-GO" normalizam pro mesmo "atletico".
    resultado = parse_handicap("Atletico -1.5", "Atletico-MG", "Atletico-GO")
    assert resultado is None


def test_parse_handicap_nenhum_time_bate_nao_chuta():
    assert parse_handicap("Timão -1.5", "Palmeiras", "Santos") is None


def test_parse_handicap_sem_numero_no_final_nao_chuta():
    assert parse_handicap("Cruzeiro sem linha definida", "Cruzeiro", "Mirassol") is None


def test_parse_handicap_linha_inteira():
    assert parse_handicap("casa -2", None, None) == IntencaoHandicap(lado="casa", linha=Decimal("-2"))


def test_parse_handicap_fora_de_escopo_primeiro_tempo_nao_chuta():
    assert parse_handicap("Cruzeiro -1.5 no 1o tempo", "Cruzeiro", "Mirassol") is None


# --- eh_condicao_por_time ------------------------------------------------------


@pytest.mark.parametrize(
    "selecao",
    [
        "Ambas as equipes recebem 2 cartões ou mais",
        "Ambas equipes com mais de 1 cartao",
        "Cada time recebe pelo menos 2 cartões",
        "Cada equipe com 1+ cartão",
        "Os dois times recebem cartão",
    ],
)
def test_eh_condicao_por_time_detecta_marcadores(selecao):
    assert eh_condicao_por_time(selecao) is True


def test_eh_condicao_por_time_total_da_partida_nao_e_condicao_por_time():
    assert eh_condicao_por_time("Mais de 4,5 cartões mostrados") is False
