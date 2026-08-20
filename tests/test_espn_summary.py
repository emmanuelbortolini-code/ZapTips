from app.espn_fixtures import EventoIgnorado
from app.espn_summary import EspnMatchResult, EspnTeamStats, parse_summary_response


def _status_type(state: str, completed: bool, name: str = "STATUS_X") -> dict:
    return {"name": name, "state": state, "completed": completed}


def _payload(status_type: dict, was_suspended: bool = False, **overrides) -> dict:
    header = {
        "id": "401841183",
        "competitions": [
            {
                "status": {"type": status_type},
                "wasSuspended": was_suspended,
                "competitors": [
                    {
                        "homeAway": "home",
                        "score": "3",
                        "linescores": [{"displayValue": "1"}, {"displayValue": "2"}],
                    },
                    {
                        "homeAway": "away",
                        "score": "1",
                        "linescores": [{"displayValue": "0"}, {"displayValue": "1"}],
                    },
                ],
            }
        ],
    }
    boxscore = {
        "teams": [
            {
                "team": {"id": "2022"},
                "statistics": [
                    {"name": "wonCorners", "displayValue": "4"},
                    {"name": "yellowCards", "displayValue": "3"},
                    {"name": "redCards", "displayValue": "0"},
                    {"name": "totalShots", "displayValue": "11"},
                    {"name": "possessionPct", "displayValue": "50.1"},
                    {"name": "foulsCommitted", "displayValue": "14"},
                ],
            },
            {
                "team": {"id": "9169"},
                "statistics": [
                    {"name": "wonCorners", "displayValue": "2"},
                    {"name": "yellowCards", "displayValue": "1"},
                    {"name": "redCards", "displayValue": "1"},
                    {"name": "totalShots", "displayValue": "8"},
                    {"name": "possessionPct", "displayValue": "49.9"},
                ],
            },
        ]
    }
    payload = {"header": header, "boxscore": boxscore}
    payload.update(overrides)
    return payload


def test_parse_partida_encerrada_extrai_placar_final_e_intervalo():
    payload = _payload(_status_type("post", True, "STATUS_FULL_TIME"))

    resultado, stats, ignorado = parse_summary_response(payload)

    assert ignorado is None
    assert resultado == EspnMatchResult(
        espn_event_id="401841183",
        status="encerrada",
        placar_casa=3,
        placar_fora=1,
        placar_ht_casa=1,
        placar_ht_fora=0,
    )


def test_parse_partida_encerrada_extrai_estatisticas_por_time():
    payload = _payload(_status_type("post", True, "STATUS_FULL_TIME"))

    _, stats, ignorado = parse_summary_response(payload)

    assert ignorado is None
    assert stats == [
        EspnTeamStats(
            espn_event_id="401841183",
            espn_team_id="2022",
            escanteios=4,
            cartoes_amarelos=3,
            cartoes_vermelhos=0,
            finalizacoes=11,
            posse=50.1,
        ),
        EspnTeamStats(
            espn_event_id="401841183",
            espn_team_id="9169",
            escanteios=2,
            cartoes_amarelos=1,
            cartoes_vermelhos=1,
            finalizacoes=8,
            posse=49.9,
        ),
    ]


def test_parse_partida_ao_vivo_nao_extrai_placar_nem_estatisticas():
    # O job de resultados so fecha o resultado quando a partida realmente
    # termina; escrever placar/stats parciais de um jogo em andamento
    # criaria dado "final" que ainda vai mudar.
    payload = _payload(_status_type("in", False, "STATUS_IN_PROGRESS"))

    resultado, stats, ignorado = parse_summary_response(payload)

    assert ignorado is None
    assert resultado.status == "ao_vivo"
    assert resultado.placar_casa is None
    assert resultado.placar_fora is None
    assert stats == []


def test_parse_status_nao_reconhecido_retorna_ignorado():
    payload = _payload(_status_type("post", False, "STATUS_POSTPONED"))

    resultado, stats, ignorado = parse_summary_response(payload)

    assert resultado is None
    assert stats == []
    assert ignorado == EventoIgnorado(
        espn_event_id="401841183", motivo="status_nao_reconhecido", status_raw="STATUS_POSTPONED"
    )


def test_parse_payload_sem_header_id_retorna_ignorado():
    payload = _payload(_status_type("pre", False))
    del payload["header"]["id"]

    resultado, stats, ignorado = parse_summary_response(payload)

    assert resultado is None
    assert stats == []
    assert ignorado.motivo == "payload_incompleto"


def test_parse_lida_com_boxscore_null_explicito_sem_crashar():
    # boxscore ausente/null nao invalida o resultado principal (placar
    # ja veio do header) - so as estatisticas por time ficam vazias.
    payload = _payload(_status_type("post", True, "STATUS_FULL_TIME"))
    payload["boxscore"] = None

    resultado, stats, ignorado = parse_summary_response(payload)

    assert ignorado is None
    assert resultado.placar_casa == 3
    assert stats == []


def test_parse_lida_com_status_null_explicito_sem_crashar():
    # status ausente/null vira estado desconhecido (nao "pre"/"in"/"post"),
    # cai no mesmo balde de status_nao_reconhecido - nao crasha.
    payload = _payload(_status_type("post", True, "STATUS_FULL_TIME"))
    payload["header"]["competitions"][0]["status"] = None

    resultado, stats, ignorado = parse_summary_response(payload)

    assert resultado is None
    assert stats == []
    assert ignorado.motivo == "status_nao_reconhecido"


def test_parse_lida_com_linescores_ausente():
    payload = _payload(_status_type("post", True, "STATUS_FULL_TIME"))
    for competidor in payload["header"]["competitions"][0]["competitors"]:
        competidor["linescores"] = []

    resultado, _, ignorado = parse_summary_response(payload)

    assert ignorado is None
    assert resultado.placar_ht_casa is None
    assert resultado.placar_ht_fora is None


def test_parse_erro_de_verdade_no_meio_do_parsing_vira_ignorado():
    # API sem contrato de estabilidade: um item de "competitors" que nao e
    # um dict (formato inesperado) tem que virar EventoIgnorado, nunca
    # derrubar o job inteiro de resultados.
    payload = _payload(_status_type("post", True, "STATUS_FULL_TIME"))
    payload["header"]["competitions"][0]["competitors"] = ["formato inesperado"]

    resultado, stats, ignorado = parse_summary_response(payload)

    assert resultado is None
    assert stats == []
    assert ignorado.motivo == "erro_parsing"


def test_parse_ignora_time_sem_id_no_boxscore():
    payload = _payload(_status_type("post", True, "STATUS_FULL_TIME"))
    payload["boxscore"]["teams"][0]["team"] = {}

    _, stats, _ = parse_summary_response(payload)

    assert len(stats) == 1
    assert stats[0].espn_team_id == "9169"


def test_parse_lida_com_displayValue_nao_numerico_sem_crashar():
    payload = _payload(_status_type("post", True, "STATUS_FULL_TIME"))
    for stat in payload["boxscore"]["teams"][0]["statistics"]:
        if stat["name"] in ("wonCorners", "possessionPct"):
            stat["displayValue"] = "N/A"

    _, stats, ignorado = parse_summary_response(payload)

    assert ignorado is None
    assert stats[0].escanteios is None
    assert stats[0].posse is None


def test_parse_lida_com_metrica_ausente_no_boxscore():
    payload = _payload(_status_type("post", True, "STATUS_FULL_TIME"))
    payload["boxscore"]["teams"][0]["statistics"] = [
        s
        for s in payload["boxscore"]["teams"][0]["statistics"]
        if s["name"] not in ("redCards", "possessionPct")
    ]

    _, stats, ignorado = parse_summary_response(payload)

    assert ignorado is None
    assert stats[0].cartoes_vermelhos is None
    assert stats[0].posse is None


def test_parse_com_statistics_null_explicito_mantem_placar_ja_valido():
    # Achado real: "statistics": null num time especifico nao pode jogar
    # fora o placar final que ja foi parseado com sucesso do header - vira
    # stats vazias, nao EventoIgnorado.
    payload = _payload(_status_type("post", True, "STATUS_FULL_TIME"))
    payload["boxscore"]["teams"][0]["statistics"] = None

    resultado, stats, ignorado = parse_summary_response(payload)

    assert ignorado is None
    assert resultado.placar_casa == 3
    assert resultado.placar_fora == 1
    assert stats[0].escanteios is None
    assert stats[1].escanteios == 2


def test_parse_com_competitors_null_explicito_nao_crasha():
    payload = _payload(_status_type("post", True, "STATUS_FULL_TIME"))
    payload["header"]["competitions"][0]["competitors"] = None

    resultado, stats, ignorado = parse_summary_response(payload)

    assert ignorado is None
    assert resultado.placar_casa is None
    assert resultado.placar_fora is None


def test_parse_erro_inesperado_no_boxscore_nao_descarta_placar():
    # Item de "teams" que nao e dict: caso extremo alem do que o "or []"
    # ja blinda, cobrindo o try/except de _parse_stats como rede de
    # seguranca. O placar (ja parseado do header) continua valido.
    payload = _payload(_status_type("post", True, "STATUS_FULL_TIME"))
    payload["boxscore"]["teams"] = ["formato inesperado"]

    resultado, stats, ignorado = parse_summary_response(payload)

    assert ignorado is None
    assert resultado.placar_casa == 3
    assert stats == []


def test_parse_ignora_estatisticas_irrelevantes():
    payload = _payload(_status_type("post", True, "STATUS_FULL_TIME"))

    _, stats, _ = parse_summary_response(payload)

    # "foulsCommitted" so aparece no time 1 e nao esta no conjunto
    # relevante (escanteios/cartoes/finalizacoes/posse) - nao deve gerar
    # campo nenhum no EspnTeamStats.
    assert not hasattr(stats[0], "foulsCommitted")
