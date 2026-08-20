from app.espn_teams import EspnTeam, parse_teams_response


def _payload(times: list[dict]) -> dict:
    return {
        "sports": [
            {
                "leagues": [
                    {
                        "teams": [{"team": t} for t in times],
                    }
                ]
            }
        ]
    }


def test_parse_extrai_id_nome_canonico_e_aliases():
    payload = _payload(
        [
            {
                "id": "819",
                "displayName": "Flamengo",
                "shortDisplayName": "Flamengo",
                "abbreviation": "FLA",
                "name": "Flamengo",
                "location": "Flamengo",
            }
        ]
    )

    times = parse_teams_response(payload)

    assert times == [
        EspnTeam(espn_team_id="819", nome_canonico="Flamengo", aliases=frozenset({"Flamengo", "FLA"}))
    ]


def test_parse_deduplica_aliases_repetidos():
    # displayName, shortDisplayName, name e location vem todos iguais para
    # a maioria dos times da amostra real (bra.1); so abbreviation varia.
    payload = _payload(
        [
            {
                "id": "9967",
                "displayName": "Bahia",
                "shortDisplayName": "Bahia",
                "abbreviation": "BAH",
                "name": "Bahia",
                "location": "Bahia",
            }
        ]
    )

    times = parse_teams_response(payload)

    assert times[0].aliases == frozenset({"Bahia", "BAH"})


def test_parse_capta_apelido_quando_displayName_e_shortDisplayName_divergem():
    # Vasco da Gama x Vasco: unico caso da amostra real onde
    # shortDisplayName traz uma forma mais curta que o nome oficial.
    payload = _payload(
        [
            {
                "id": "3454",
                "displayName": "Vasco da Gama",
                "shortDisplayName": "Vasco",
                "abbreviation": "VAS",
                "name": "Vasco da Gama",
                "location": "Vasco da Gama",
            }
        ]
    )

    times = parse_teams_response(payload)

    assert times[0].aliases == frozenset({"Vasco da Gama", "Vasco", "VAS"})


def test_parse_ignora_time_sem_id():
    payload = _payload([{"displayName": "Sem Id"}])

    assert parse_teams_response(payload) == []


def test_parse_ignora_time_sem_displayName():
    payload = _payload([{"id": "1"}])

    assert parse_teams_response(payload) == []


def test_parse_ignora_campos_vazios_ou_ausentes_como_alias():
    payload = _payload(
        [
            {
                "id": "1",
                "displayName": "Time X",
                "shortDisplayName": "",
                "abbreviation": None,
            }
        ]
    )

    times = parse_teams_response(payload)

    assert times[0].aliases == frozenset({"Time X"})


def test_parse_lida_com_multiplas_ligas_no_mesmo_payload():
    payload = {
        "sports": [
            {
                "leagues": [
                    {"teams": [{"team": {"id": "1", "displayName": "Time A"}}]},
                    {"teams": [{"team": {"id": "2", "displayName": "Time B"}}]},
                ]
            }
        ]
    }

    times = parse_teams_response(payload)

    assert {t.espn_team_id for t in times} == {"1", "2"}


def test_parse_payload_vazio_retorna_lista_vazia():
    assert parse_teams_response({}) == []
