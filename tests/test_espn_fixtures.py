from datetime import datetime, timezone

from app.espn_fixtures import EspnFixtureRaw, EventoIgnorado, map_status, parse_scoreboard_response


def _status_type(state: str, completed: bool, name: str = "STATUS_X") -> dict:
    return {"name": name, "state": state, "completed": completed}


def test_map_status_scheduled_retorna_agendada():
    assert map_status(_status_type("pre", False, "STATUS_SCHEDULED"), was_suspended=False) == "agendada"


def test_map_status_em_andamento_retorna_ao_vivo():
    assert map_status(_status_type("in", False, "STATUS_IN_PROGRESS"), was_suspended=False) == "ao_vivo"


def test_map_status_finalizado_e_completo_retorna_encerrada():
    assert map_status(_status_type("post", True, "STATUS_FULL_TIME"), was_suspended=False) == "encerrada"


def test_map_status_post_sem_completed_retorna_none():
    # Adiada/cancelada tambem caem em state="post" sem completed=true, e a
    # ESPN nao documenta como distinguir isso de forma confiavel (ver
    # CLAUDE.md, Fase 1a, pergunta 8) - nunca mapear por suposicao.
    assert map_status(_status_type("post", False, "STATUS_POSTPONED"), was_suspended=False) is None


def test_map_status_suspenso_retorna_none_mesmo_com_state_conhecido():
    # wasSuspended=true nunca foi confirmado com caso real (CLAUDE.md); nao
    # da para saber se vira "adiada" ou "cancelada", entao nao mapeia.
    assert map_status(_status_type("pre", False), was_suspended=True) is None


def test_map_status_estado_desconhecido_retorna_none():
    assert map_status(_status_type("algo_novo", False), was_suspended=False) is None


def _payload_com_evento(**overrides) -> dict:
    evento = {
        "id": "401841192",
        "date": "2026-08-15T19:30Z",
        "season": {"slug": "2026-brasileiro-serie-a"},
        "competitions": [
            {
                "status": {"type": _status_type("pre", False, "STATUS_SCHEDULED")},
                "wasSuspended": False,
                "venue": {"fullName": "Estadio do Maracana"},
                "competitors": [
                    {"homeAway": "home", "team": {"id": "3445"}},
                    {"homeAway": "away", "team": {"id": "2029"}},
                ],
            }
        ],
    }
    evento.update(overrides)
    return {"events": [evento]}


def test_parse_extrai_fixture_com_dados_completos():
    fixtures, ignorados = parse_scoreboard_response(_payload_com_evento(), liga="bra.1")

    assert ignorados == []
    assert fixtures == [
        EspnFixtureRaw(
            espn_event_id="401841192",
            liga="bra.1",
            temporada="2026-brasileiro-serie-a",
            home_espn_team_id="3445",
            away_espn_team_id="2029",
            kickoff_utc=datetime(2026, 8, 15, 19, 30, tzinfo=timezone.utc),
            status="agendada",
            estadio="Estadio do Maracana",
        )
    ]


def test_parse_ignora_evento_sem_id():
    payload = _payload_com_evento(id=None)

    fixtures, ignorados = parse_scoreboard_response(payload, liga="bra.1")

    assert fixtures == []
    assert ignorados == [EventoIgnorado(espn_event_id=None, motivo="payload_incompleto", status_raw=None)]


def test_parse_ignora_evento_sem_competitions():
    payload = _payload_com_evento(competitions=[])

    fixtures, ignorados = parse_scoreboard_response(payload, liga="bra.1")

    assert fixtures == []
    assert ignorados[0].motivo == "payload_incompleto"


def test_parse_ignora_evento_com_status_nao_reconhecido_e_reporta_motivo():
    payload = _payload_com_evento()
    payload["events"][0]["competitions"][0]["status"]["type"] = _status_type(
        "post", False, "STATUS_POSTPONED"
    )

    fixtures, ignorados = parse_scoreboard_response(payload, liga="bra.1")

    assert fixtures == []
    assert ignorados == [
        EventoIgnorado(espn_event_id="401841192", motivo="status_nao_reconhecido", status_raw="STATUS_POSTPONED")
    ]


def test_parse_lida_com_evento_sem_venue():
    payload = _payload_com_evento()
    del payload["events"][0]["competitions"][0]["venue"]

    fixtures, _ = parse_scoreboard_response(payload, liga="bra.1")

    assert fixtures[0].estadio is None


def test_parse_lida_com_time_faltando_no_competitors():
    payload = _payload_com_evento()
    payload["events"][0]["competitions"][0]["competitors"] = [
        {"homeAway": "home", "team": {"id": "3445"}},
    ]

    fixtures, _ = parse_scoreboard_response(payload, liga="bra.1")

    assert fixtures[0].home_espn_team_id == "3445"
    assert fixtures[0].away_espn_team_id is None


def test_parse_lida_com_venue_null_explicito_sem_crashar():
    # Diferente de chave ausente: aqui a chave existe no JSON com valor
    # null, entao competicao.get("venue", {}) devolve None, nao {}.
    payload = _payload_com_evento()
    payload["events"][0]["competitions"][0]["venue"] = None

    fixtures, ignorados = parse_scoreboard_response(payload, liga="bra.1")

    assert fixtures == []
    assert ignorados[0].motivo == "erro_parsing"


def test_parse_lida_com_season_null_explicito_sem_crashar():
    payload = _payload_com_evento()
    payload["events"][0]["season"] = None

    fixtures, ignorados = parse_scoreboard_response(payload, liga="bra.1")

    assert fixtures == []
    assert ignorados[0].motivo == "erro_parsing"


def test_parse_lida_com_status_null_explicito_sem_crashar():
    payload = _payload_com_evento()
    payload["events"][0]["competitions"][0]["status"] = None

    fixtures, ignorados = parse_scoreboard_response(payload, liga="bra.1")

    assert fixtures == []
    assert ignorados[0].motivo == "erro_parsing"


def test_parse_multiplos_eventos_mistura_ok_e_ignorados():
    payload = _payload_com_evento()
    evento_ignorado = {
        "id": "999",
        "date": "2026-08-16T19:30Z",
        "season": {"slug": "2026-brasileiro-serie-a"},
        "competitions": [
            {
                "status": {"type": _status_type("post", False, "STATUS_CANCELED")},
                "wasSuspended": False,
                "venue": {"fullName": "Outro Estadio"},
                "competitors": [
                    {"homeAway": "home", "team": {"id": "1"}},
                    {"homeAway": "away", "team": {"id": "2"}},
                ],
            }
        ],
    }
    payload["events"].append(evento_ignorado)

    fixtures, ignorados = parse_scoreboard_response(payload, liga="bra.1")

    assert [f.espn_event_id for f in fixtures] == ["401841192"]
    assert [i.espn_event_id for i in ignorados] == ["999"]
