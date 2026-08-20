from app.odds_resolution import (
    PickParaResolverOdds,
    calcular_odd_minima,
    normalizar_selecao_1x2,
    normalizar_selecao_ambas_marcam,
    normalizar_selecao_over_under,
    resolver_odd_espn,
    resolver_odd_referencia,
)


def _pick(**overrides) -> PickParaResolverOdds:
    base = dict(
        pick_id="p1", fixture_id="fix-1", mercado="1x2", selecao="Home win",
        time_casa="Goiás", time_fora="Londrina", casa_id=None, odd_citada=None,
    )
    base.update(overrides)
    return PickParaResolverOdds(**base)


def test_normalizar_selecao_1x2_literais():
    assert normalizar_selecao_1x2("Home win", None, None) == "casa"
    assert normalizar_selecao_1x2("Away win", None, None) == "fora"
    assert normalizar_selecao_1x2("Empate", None, None) == "empate"
    assert normalizar_selecao_1x2("Draw", None, None) == "empate"


def test_normalizar_selecao_1x2_vitoria_do_time():
    assert normalizar_selecao_1x2("Vitória do Real Madrid", "Real Madrid", "Athletic Club") == "casa"
    assert normalizar_selecao_1x2("Vitória do Brighton", "Leeds", "Brighton") == "fora"
    assert normalizar_selecao_1x2("Fluminense vence", "Fluminense", "Palmeiras") == "casa"


def test_normalizar_selecao_1x2_nome_substring_do_adversario_nao_chuta():
    # Achado real do code-reviewer: "Gremio" e' substring normalizada de
    # "Gremio Novorizontino" - preferir casa cegamente classificaria uma
    # vitoria do time de fora como vitoria da casa.
    assert normalizar_selecao_1x2("Vitória do Grêmio Novorizontino", "Grêmio", "Grêmio Novorizontino") is None


def test_normalizar_selecao_1x2_times_normalizam_igual_nao_chuta():
    # "Atletico-MG" e "Atletico-GO" colapsam pro mesmo "atletico" depois
    # do sufixo de estado (mesma ambiguidade ja documentada em
    # CLAUDE.md/Fase 1g para o matcher de times).
    assert normalizar_selecao_1x2("Vitória do Atlético", "Atlético-MG", "Atlético-GO") is None


def test_normalizar_selecao_1x2_dupla_chance_nao_resolve():
    # "1X"/"X2"/"12" nao mapeiam pra uma unica linha de odds_referencia -
    # deliberadamente nao resolvido, nunca chuta.
    assert normalizar_selecao_1x2("1X", "A", "B") is None
    assert normalizar_selecao_1x2("X2", "A", "B") is None


def test_normalizar_selecao_ambas_marcam_literais_portugues():
    assert normalizar_selecao_ambas_marcam("Ambas as equipes marcam: sim") == "sim"
    assert normalizar_selecao_ambas_marcam("Ambas as equipes marcam: não") == "nao"
    assert normalizar_selecao_ambas_marcam("Ambos os times marcam - sim") == "sim"


def test_normalizar_selecao_ambas_marcam_literais_ingles():
    assert normalizar_selecao_ambas_marcam("BTTS") == "sim"
    assert normalizar_selecao_ambas_marcam("Yes") == "sim"


def test_normalizar_selecao_ambas_marcam_nao_confunde_preposicao_no_com_negativa():
    # Achado real (Fase 3): "Benfica marca no 1o e 2o tempo" tem "no"
    # como preposicao em portugues, nao como resposta "no" em ingles -
    # bare "no" e' deliberadamente fora do reconhecimento.
    assert normalizar_selecao_ambas_marcam("Benfica marca no 1º e 2º tempo") is None


def test_normalizar_selecao_ambas_marcam_texto_combinado_nao_resolve():
    # Mercado combinado (ex.: "Ambas as equipes marcam e Total de gols")
    # nao tem "sim"/"nao"/"btts"/"yes" isolados - nunca chuta.
    assert normalizar_selecao_ambas_marcam("Ambas as equipes marcam e Total de gols") is None


def test_normalizar_selecao_ambas_marcam_fora_de_escopo_nao_resolve():
    # Achado do code-reviewer (2026-08-20, mesma classe de bug ja
    # corrigida em app.settlement.selecao): "Ambas marcam no 1o tempo"
    # nao pode resolver contra a odd de jogo inteiro - mercado diferente.
    assert normalizar_selecao_ambas_marcam("Ambas as equipes marcam no 1º tempo: sim") is None


def test_normalizar_selecao_ambas_marcam_btts_no_e_negativo():
    # Achado do code-reviewer: sem essa checagem, "BTTS No"/"BTTS: No"
    # batia so no "btts" isolado do _SIM_RE e respondia "sim" - o oposto
    # do texto real (Eagle Predict, em ingles).
    assert normalizar_selecao_ambas_marcam("BTTS No") == "nao"
    assert normalizar_selecao_ambas_marcam("BTTS: No") == "nao"


def test_normalizar_selecao_over_under_com_de():
    assert normalizar_selecao_over_under("Menos de 2.5 gols") == ("under", 2.5)
    assert normalizar_selecao_over_under("Mais de 2.5 gols") == ("over", 2.5)


def test_normalizar_selecao_over_under_sem_de():
    assert normalizar_selecao_over_under("Menos 3.5 gols") == ("under", 3.5)
    assert normalizar_selecao_over_under("Menos 4 gols") == ("under", 4.0)


def test_normalizar_selecao_over_under_ingles():
    assert normalizar_selecao_over_under("Over 1.5") == ("over", 1.5)
    assert normalizar_selecao_over_under("Under 3.5") == ("under", 3.5)


def test_normalizar_selecao_over_under_virgula_decimal():
    assert normalizar_selecao_over_under("Menos de 2,5 gols") == ("under", 2.5)


def test_normalizar_selecao_over_under_sem_numero_nao_resolve():
    assert normalizar_selecao_over_under("Poucos gols esperados") is None


def test_normalizar_selecao_over_under_fora_de_escopo_nao_resolve():
    # Achado do code-reviewer (2026-08-20, mesma classe de bug ja
    # corrigida em app.settlement.selecao, Fase 6a): "Mais de 0.5 gols no
    # 1o tempo" batia no regex de linha (0.5) e resolveria contra a odd
    # de jogo inteiro - mercado errado, odd errada mostrada ao assinante.
    assert normalizar_selecao_over_under("Mais de 0.5 gols no 1º tempo") is None
    assert normalizar_selecao_over_under("Menos de 2.5 gols na prorrogação") is None


def test_calcular_odd_minima_usa_margem_quando_acima_do_piso():
    # 2.00 * (1 - 0.04) = 1.92, acima do piso 1.40
    assert calcular_odd_minima(2.00, margem_pct=0.04, odd_minima_absoluta=1.40) == 1.92


def test_calcular_odd_minima_usa_piso_absoluto_quando_margem_fica_abaixo():
    # 1.40 * 0.96 = 1.344, abaixo do piso -> usa o piso
    assert calcular_odd_minima(1.40, margem_pct=0.04, odd_minima_absoluta=1.40) == 1.40


def test_calcular_odd_minima_arredonda_sempre_pra_baixo():
    # 1.4499... nunca pode virar 1.45 (arredondar pra cima quebra a promessa)
    assert calcular_odd_minima(1.4499, margem_pct=0.0, odd_minima_absoluta=1.0) == 1.44


def test_calcular_odd_minima_nao_sofre_imprecisao_de_binario_float():
    # odd_referencia=2.75 com margem=0.04: 2.75 * 0.96 = 2.64 exato, mas
    # em float essa multiplicacao produz 2.6399999999999997 - a
    # implementacao antiga (math.floor(bruta*100)/100) cortava pra baixo
    # por acidente de representacao binaria (2.63, errado), nao por
    # decisao de negocio. Decimal(str(x)) evita isso (achado real do
    # code-reviewer, com caso reproduzido por busca exaustiva).
    assert calcular_odd_minima(2.75, margem_pct=0.04, odd_minima_absoluta=1.40) == 2.64
    assert calcular_odd_minima(9.50, margem_pct=0.04, odd_minima_absoluta=1.40) == 9.12


def test_resolver_odd_referencia_nivel_1_fonte_licenciada():
    pick = _pick(mercado="over_under", selecao="Under 2.5", casa_id="casa-1", odd_citada=1.85)

    resultado = resolver_odd_referencia(pick, casas_licenciadas={"casa-1"}, odds_por_fixture_mercado_selecao={})

    assert resultado.valor == 1.85
    assert resultado.origem == "fonte"


def test_resolver_odd_referencia_nivel_1_ignora_casa_nao_licenciada():
    pick = _pick(mercado="1x2", casa_id="casa-nao-licenciada", odd_citada=1.85)

    resultado = resolver_odd_referencia(pick, casas_licenciadas={"outra-casa"}, odds_por_fixture_mercado_selecao={})

    assert resultado is None


def test_resolver_odd_referencia_nivel_2_usa_o_minimo_entre_casas():
    pick = _pick(mercado="1x2", selecao="Home win")
    odds = {("fix-1", "1x2", "casa", None): [1.90, 1.75, 1.88]}

    resultado = resolver_odd_referencia(pick, casas_licenciadas=set(), odds_por_fixture_mercado_selecao=odds)

    assert resultado.valor == 1.75
    assert resultado.origem == "oddspapi"


def test_resolver_odd_referencia_nivel_1_tem_prioridade_sobre_nivel_2():
    pick = _pick(mercado="1x2", selecao="Home win", casa_id="casa-1", odd_citada=2.10)
    odds = {("fix-1", "1x2", "casa", None): [1.90]}

    resultado = resolver_odd_referencia(pick, casas_licenciadas={"casa-1"}, odds_por_fixture_mercado_selecao=odds)

    assert resultado.valor == 2.10
    assert resultado.origem == "fonte"


def test_resolver_odd_referencia_mercado_ainda_sem_cobertura_no_nivel_2():
    # handicap/escanteios/cartoes ainda nao tem cobertura no OddsPapi -
    # diferente de over_under/ambas_marcam (cobertos desde 2026-08-20),
    # esses seguem sem tentativa nenhuma de nivel 2.
    pick = _pick(mercado="handicap", selecao="Casa -1.5")
    odds = {("fix-1", "handicap", "casa", -1.5): [1.80]}  # nao existe de verdade, so pra provar que nao e' usado

    resultado = resolver_odd_referencia(pick, casas_licenciadas=set(), odds_por_fixture_mercado_selecao=odds)

    assert resultado is None


def test_resolver_odd_referencia_sem_nenhum_nivel_disponivel():
    pick = _pick(mercado="1x2", selecao="1X")  # dupla chance, nao resolve nivel 2

    resultado = resolver_odd_referencia(pick, casas_licenciadas=set(), odds_por_fixture_mercado_selecao={})

    assert resultado is None


def test_resolver_odd_referencia_ambas_marcam_nivel_2():
    pick = _pick(mercado="ambas_marcam", selecao="Ambas as equipes marcam: sim")
    odds = {("fix-1", "ambas_marcam", "sim", None): [1.90, 1.83]}

    resultado = resolver_odd_referencia(pick, casas_licenciadas=set(), odds_por_fixture_mercado_selecao=odds)

    assert resultado.valor == 1.83
    assert resultado.origem == "oddspapi"


def test_resolver_odd_referencia_ambas_marcam_nao_resolve_selecao_ambigua():
    pick = _pick(mercado="ambas_marcam", selecao="Total de gols e ambas marcam")  # combinado, nunca chuta
    odds = {("fix-1", "ambas_marcam", "sim", None): [1.90]}

    resultado = resolver_odd_referencia(pick, casas_licenciadas=set(), odds_por_fixture_mercado_selecao=odds)

    assert resultado is None


def test_resolver_odd_referencia_over_under_nivel_2():
    pick = _pick(mercado="over_under", selecao="Menos de 2.5 gols")
    odds = {("fix-1", "over_under", "under", 2.5): [1.60, 1.57]}

    resultado = resolver_odd_referencia(pick, casas_licenciadas=set(), odds_por_fixture_mercado_selecao=odds)

    assert resultado.valor == 1.57
    assert resultado.origem == "oddspapi"


def test_resolver_odd_referencia_over_under_linha_errada_nao_bate():
    pick = _pick(mercado="over_under", selecao="Menos de 3.5 gols")
    odds = {("fix-1", "over_under", "under", 2.5): [1.57]}  # linha diferente da citada

    resultado = resolver_odd_referencia(pick, casas_licenciadas=set(), odds_por_fixture_mercado_selecao=odds)

    assert resultado is None


def test_resolver_odd_espn_usa_o_minimo_entre_casas_licenciadas():
    pick = _pick(mercado="1x2", selecao="Home win")
    payload = {
        "odds": [
            {"provider": {"name": "Bet365"}, "homeTeamOdds": {"moneyLine": -200}},  # 1.500
            {"provider": {"name": "Betano"}, "homeTeamOdds": {"moneyLine": -150}},  # 1.667
            {"provider": {"name": "DraftKings"}, "homeTeamOdds": {"moneyLine": -300}},  # nao licenciada
        ]
    }

    resultado = resolver_odd_espn(pick, payload, casas_licenciadas_normalizadas={"bet365", "betano"})

    assert resultado.valor == 1.5
    assert resultado.origem == "espn"


def test_resolver_odd_espn_mercado_fora_do_1x2_nunca_tenta():
    pick = _pick(mercado="over_under", selecao="Under 2.5")
    payload = {"odds": [{"provider": {"name": "Bet365"}, "homeTeamOdds": {"moneyLine": -200}}]}

    resultado = resolver_odd_espn(pick, payload, casas_licenciadas_normalizadas={"bet365"})

    assert resultado is None


def test_resolver_odd_espn_selecao_ambigua_nao_chuta():
    # "1X" (dupla chance) - mesma restricao do nivel 2, nunca resolve.
    pick = _pick(mercado="1x2", selecao="1X")
    payload = {"odds": [{"provider": {"name": "Bet365"}, "homeTeamOdds": {"moneyLine": -200}}]}

    resultado = resolver_odd_espn(pick, payload, casas_licenciadas_normalizadas={"bet365"})

    assert resultado is None


def test_resolver_odd_espn_sem_casa_licenciada_no_payload():
    # Caso comum na sonda ao vivo de hoje: so' DraftKings, nunca licenciada.
    pick = _pick(mercado="1x2", selecao="Home win")
    payload = {"odds": [{"provider": {"name": "DraftKings"}, "homeTeamOdds": {"moneyLine": -240}}]}

    resultado = resolver_odd_espn(pick, payload, casas_licenciadas_normalizadas={"bet365", "betano", "superbet"})

    assert resultado is None
