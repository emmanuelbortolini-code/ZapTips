from app.espn_odds import OddEspnEncontrada, extrair_odds_licenciadas, normalizar_nome_casa

# Payload reduzido, moldado no formato real observado numa sonda ao vivo
# desta sessao (2026-08-20, event=401841205, bra.1) - odds americanas
# (moneyLine), nunca decimais, confirmado contra a API de verdade.
_PAYLOAD_DRAFTKINGS = {
    "odds": [
        {
            "provider": {"name": "DraftKings"},
            "homeTeamOdds": {"moneyLine": -240},
            "awayTeamOdds": {"moneyLine": 600},
            "drawOdds": {"moneyLine": 360.0},
        }
    ]
}

_PAYLOAD_BET365 = {
    "odds": [
        {
            "provider": {"name": "Bet 365"},
            "homeTeamOdds": {"moneyLine": -150},
            "awayTeamOdds": {"moneyLine": 350},
            "drawOdds": {"moneyLine": 280},
        }
    ]
}


def test_normalizar_nome_casa_remove_espaco_e_case():
    assert normalizar_nome_casa("Bet 365") == "bet365"
    assert normalizar_nome_casa("BET365") == "bet365"
    assert normalizar_nome_casa("  Betano ") == "betano"


def test_extrair_odds_licenciadas_ignora_casa_nao_licenciada():
    # DraftKings nao esta no conjunto de casas licenciadas - achado real
    # da sonda ao vivo: e' o unico provider visto em 7 ligas testadas
    # hoje, mas nunca e' elegivel pro nivel 3 (nao licenciada no Brasil).
    encontradas = extrair_odds_licenciadas(_PAYLOAD_DRAFTKINGS, "casa", casas_licenciadas_normalizadas={"bet365", "betano", "superbet"})

    assert encontradas == []


def test_extrair_odds_licenciadas_converte_moneyline_positivo_e_negativo():
    # -150 -> 1 + 100/150 = 1.6666... -> arredondado a 3 casas (mesma
    # precisao de picks.odd_referencia, numeric(6,3)); +350 -> 1 + 3.5 = 4.5
    encontradas_casa = extrair_odds_licenciadas(_PAYLOAD_BET365, "casa", casas_licenciadas_normalizadas={"bet365"})
    encontradas_fora = extrair_odds_licenciadas(_PAYLOAD_BET365, "fora", casas_licenciadas_normalizadas={"bet365"})
    encontradas_empate = extrair_odds_licenciadas(_PAYLOAD_BET365, "empate", casas_licenciadas_normalizadas={"bet365"})

    assert encontradas_casa == [OddEspnEncontrada(valor=1.667, casa_nome="Bet 365")]
    assert encontradas_fora == [OddEspnEncontrada(valor=4.5, casa_nome="Bet 365")]
    assert encontradas_empate == [OddEspnEncontrada(valor=3.8, casa_nome="Bet 365")]


def test_extrair_odds_licenciadas_match_ignora_espaco_no_nome_do_provider():
    # "Bet 365" (nome real do provider no payload) precisa bater com a
    # casa cadastrada como "Bet365" (sem espaco, migrations/0009) - por
    # isso o match e' por nome normalizado, nao literal.
    encontradas = extrair_odds_licenciadas(_PAYLOAD_BET365, "casa", casas_licenciadas_normalizadas={"bet365"})

    assert len(encontradas) == 1
    assert encontradas[0].casa_nome == "Bet 365"


def test_extrair_odds_licenciadas_multiplas_casas_licenciadas():
    payload = {
        "odds": [
            {"provider": {"name": "Bet365"}, "homeTeamOdds": {"moneyLine": -200}},
            {"provider": {"name": "Betano"}, "homeTeamOdds": {"moneyLine": -110}},
            {"provider": {"name": "DraftKings"}, "homeTeamOdds": {"moneyLine": -300}},
        ]
    }

    encontradas = extrair_odds_licenciadas(payload, "casa", casas_licenciadas_normalizadas={"bet365", "betano"})

    assert {e.casa_nome for e in encontradas} == {"Bet365", "Betano"}


def test_extrair_odds_licenciadas_sem_bloco_odds_nao_quebra():
    assert extrair_odds_licenciadas({}, "casa", casas_licenciadas_normalizadas={"bet365"}) == []
    assert extrair_odds_licenciadas({"odds": None}, "casa", casas_licenciadas_normalizadas={"bet365"}) == []


def test_extrair_odds_licenciadas_entrada_malformada_e_pulada_sem_quebrar():
    # Mesma politica ja usada em espn_fixtures/espn_summary/oddspapi:
    # payload sem contrato de estabilidade, um campo nulo/ausente numa
    # entrada nao pode derrubar o parsing das demais.
    payload = {
        "odds": [
            {"provider": None, "homeTeamOdds": {"moneyLine": -150}},
            {"provider": {"name": "Bet365"}, "homeTeamOdds": None},
            {"provider": {"name": "Betano"}, "homeTeamOdds": {"moneyLine": "nao-numerico"}},
            {"provider": {"name": "Superbet"}, "homeTeamOdds": {"moneyLine": -120}},
        ]
    }

    encontradas = extrair_odds_licenciadas(
        payload, "casa", casas_licenciadas_normalizadas={"bet365", "betano", "superbet"}
    )

    assert [e.casa_nome for e in encontradas] == ["Superbet"]


def test_extrair_odds_licenciadas_item_nulo_na_lista_e_pulado_sem_quebrar():
    # Achado do code-reviewer: um item `null` explicito na lista `odds`
    # (nao so um campo interno nulo) - mesma classe de bug ja corrigida
    # em app/espn_fixtures.py e app/espn_summary.py (Fase 1e/1f), payload
    # sem contrato de estabilidade.
    payload = {
        "odds": [
            None,
            {"provider": {"name": "Bet365"}, "homeTeamOdds": {"moneyLine": -200}},
        ]
    }

    encontradas = extrair_odds_licenciadas(payload, "casa", casas_licenciadas_normalizadas={"bet365"})

    assert [e.casa_nome for e in encontradas] == ["Bet365"]


def test_extrair_odds_licenciadas_moneyline_zero_e_invalido():
    payload = {"odds": [{"provider": {"name": "Bet365"}, "homeTeamOdds": {"moneyLine": 0}}]}

    assert extrair_odds_licenciadas(payload, "casa", casas_licenciadas_normalizadas={"bet365"}) == []
