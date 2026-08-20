import json

from app.extraction import (
    ExtractedPalpite,
    RawPickInput,
    montar_lotes,
    montar_mensagem_usuario,
    parse_resposta,
)


def _post(id_: str, texto: str = "texto qualquer") -> RawPickInput:
    return RawPickInput(raw_pick_id=id_, texto_bruto=texto)


def _resposta(resultados: list[dict]) -> str:
    return json.dumps({"resultados": resultados})


def _palpite_valido(**overrides) -> dict:
    base = {
        "time_casa": "Galo",
        "time_fora": None,
        "competicao": None,
        "data_referencia": None,
        "mercado": "1x2",
        "selecao": "Galo vence",
        "odd": 1.85,
        "casa_apostas": "Bet365",
        "unidades": 2,
        "confianca_extracao": 0.9,
    }
    base.update(overrides)
    return base


def test_montar_lotes_divide_em_grupos_do_tamanho_certo():
    posts = [_post(str(i)) for i in range(5)]

    lotes = montar_lotes(posts, max_posts_por_lote=2)

    assert [len(lote) for lote in lotes] == [2, 2, 1]


def test_montar_lotes_lote_unico_quando_cabe_tudo():
    posts = [_post(str(i)) for i in range(3)]

    lotes = montar_lotes(posts, max_posts_por_lote=10)

    assert len(lotes) == 1
    assert len(lotes[0]) == 3


def test_montar_mensagem_usuario_inclui_post_id_e_texto():
    mensagem = montar_mensagem_usuario([_post("abc-123", "Galo vence hoje")])

    assert "abc-123" in mensagem
    assert "Galo vence hoje" in mensagem


def test_parse_resposta_extrai_palpite_de_um_post():
    resposta = _resposta([{"post_id": "p1", "palpites": [_palpite_valido()]}])

    palpites, respondidos = parse_resposta(resposta)

    assert respondidos == {"p1"}
    assert palpites == [
        ExtractedPalpite(
            raw_pick_id="p1", time_casa="Galo", time_fora=None, competicao=None,
            data_referencia=None, mercado="1x2", selecao="Galo vence", odd=1.85,
            casa_apostas="Bet365", unidades=2, confianca_extracao=0.9,
        )
    ]


def test_parse_resposta_post_sem_palpite_ainda_conta_como_respondido():
    resposta = _resposta([{"post_id": "p1", "palpites": []}])

    palpites, respondidos = parse_resposta(resposta)

    assert palpites == []
    assert respondidos == {"p1"}


def test_parse_resposta_multiplos_palpites_no_mesmo_post():
    resposta = _resposta(
        [{"post_id": "p1", "palpites": [_palpite_valido(selecao="A"), _palpite_valido(selecao="B")]}]
    )

    palpites, _ = parse_resposta(resposta)

    assert [p.selecao for p in palpites] == ["A", "B"]


def test_parse_resposta_ignora_resultado_sem_post_id():
    resposta = _resposta([{"post_id": "", "palpites": [_palpite_valido()]}])

    palpites, respondidos = parse_resposta(resposta)

    assert palpites == []
    assert respondidos == set()


def test_parse_resposta_isola_palpite_malformado_dos_demais():
    # Um item sem "selecao" (obrigatorio) nao pode derrubar os outros
    # palpites do mesmo post nem de outros posts do lote.
    malformado = _palpite_valido()
    del malformado["selecao"]
    resposta = _resposta(
        [
            {"post_id": "p1", "palpites": [malformado, _palpite_valido(selecao="ok")]},
            {"post_id": "p2", "palpites": [_palpite_valido(selecao="tambem ok")]},
        ]
    )

    palpites, respondidos = parse_resposta(resposta)

    assert [p.selecao for p in palpites] == ["ok", "tambem ok"]
    assert respondidos == {"p1", "p2"}


def test_parse_resposta_normaliza_mercado_desconhecido_para_outro():
    resposta = _resposta([{"post_id": "p1", "palpites": [_palpite_valido(mercado="mercado_inventado")]}])

    palpites, _ = parse_resposta(resposta)

    assert palpites[0].mercado == "outro"


def test_parse_resposta_confianca_fora_do_intervalo_e_limitada_a_0_1():
    resposta = _resposta(
        [
            {"post_id": "p1", "palpites": [_palpite_valido(selecao="alta", confianca_extracao=1.5)]},
            {"post_id": "p2", "palpites": [_palpite_valido(selecao="baixa", confianca_extracao=-0.2)]},
        ]
    )

    palpites, _ = parse_resposta(resposta)

    confiancas = {p.selecao: p.confianca_extracao for p in palpites}
    assert confiancas == {"alta": 1.0, "baixa": 0.0}


def test_parse_resposta_confianca_ausente_vira_zero():
    palpite = _palpite_valido()
    del palpite["confianca_extracao"]
    resposta = _resposta([{"post_id": "p1", "palpites": [palpite]}])

    palpites, _ = parse_resposta(resposta)

    assert palpites[0].confianca_extracao == 0.0
