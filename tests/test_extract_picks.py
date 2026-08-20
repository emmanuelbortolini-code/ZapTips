import json

import anthropic
import httpx

from app.extraction import ExtractedPalpite, RawPickInput
from scripts.extract_picks import (
    buscar_raw_picks_pendentes,
    carregar_casas,
    marcar_extraidos,
    processar_lotes,
    upsert_pick,
)
from tests._fakes import FakeCursor


class _Usage:
    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def _palpite(raw_pick_id="p1", confianca=0.9, **overrides) -> ExtractedPalpite:
    base = dict(
        raw_pick_id=raw_pick_id, time_casa="Galo", time_fora=None, competicao=None,
        data_referencia=None, mercado="1x2", selecao="Galo vence", odd=1.85,
        casa_apostas="Bet365", unidades=2.0, confianca_extracao=confianca,
    )
    base.update(overrides)
    return ExtractedPalpite(**base)


def test_buscar_raw_picks_pendentes_mapeia_colunas():
    cur = FakeCursor(fetchall_results=[[("id-1", "texto 1", "Fulano"), ("id-2", "texto 2", None)]])

    pendentes = buscar_raw_picks_pendentes(cur)

    assert pendentes == [
        RawPickInput(raw_pick_id="id-1", texto_bruto="texto 1", autor="Fulano"),
        RawPickInput(raw_pick_id="id-2", texto_bruto="texto 2", autor=None),
    ]
    assert "extraido_em is null" in cur.queries[0][0]


def test_buscar_raw_picks_pendentes_normaliza_id_para_str():
    # psycopg devolve uuid.UUID por padrao pra coluna uuid - sem
    # normalizar aqui, a comparacao de conjuntos contra post_id (sempre
    # str, vem do JSON da resposta do modelo) nunca bateria.
    class _FakeUUID:
        def __str__(self):
            return "11111111-1111-1111-1111-111111111111"

    cur = FakeCursor(fetchall_results=[[(_FakeUUID(), "texto", None)]])

    pendentes = buscar_raw_picks_pendentes(cur)

    assert pendentes[0].raw_pick_id == "11111111-1111-1111-1111-111111111111"
    assert isinstance(pendentes[0].raw_pick_id, str)


def test_carregar_casas_inclui_nome_e_aliases():
    cur = FakeCursor(
        fetchall_results=[
            [("casa-1", "Bet365", ["bet 365", "bet365 br"]), ("casa-2", "Betano", [])]
        ]
    )

    casas = carregar_casas(cur)

    assert casas == {
        "bet365": "casa-1", "bet 365": "casa-1", "bet365 br": "casa-1",
        "betano": "casa-2",
    }


def test_upsert_pick_confianca_alta_fica_extraido():
    cur = FakeCursor()

    upsert_pick(cur, _palpite(confianca=0.9), casa_id="casa-1", tipster="Fulano")

    _, params = cur.queries[0]
    assert params[6] == "extraido"


def test_upsert_pick_confianca_baixa_vai_para_revisao_manual():
    cur = FakeCursor()

    upsert_pick(cur, _palpite(confianca=0.5), casa_id=None, tipster=None)

    _, params = cur.queries[0]
    assert params[6] == "revisao_manual"


def test_upsert_pick_grava_campos_extraidos_e_tipster():
    cur = FakeCursor()

    upsert_pick(
        cur,
        _palpite(time_casa="Galo", time_fora="Cruzeiro", competicao="Brasileirao", unidades=3.0),
        casa_id="casa-1",
        tipster="Fulano",
    )

    _, params = cur.queries[0]
    assert params[-1] == "Fulano"  # tipster
    assert params[7:11] == ("Galo", "Cruzeiro", "Brasileirao", None)  # time_casa/fora/competicao/data
    assert params[11] == 3.0  # unidades


def test_marcar_extraidos_ignora_lista_vazia():
    cur = FakeCursor()

    marcar_extraidos(cur, [])

    assert cur.queries == []


def test_marcar_extraidos_executa_update_com_ids():
    cur = FakeCursor()

    marcar_extraidos(cur, ["id-1", "id-2"])

    sql, params = cur.queries[0]
    assert "update raw_picks set extraido_em" in sql
    # any(%s::uuid[]) - cast explicito, senao um array de str pode nao
    # bater contra a coluna uuid dependendo de como o driver tipa o param.
    assert "any(%s::uuid[])" in sql
    assert params == (["id-1", "id-2"],)


def test_processar_lotes_falha_em_um_lote_nao_interrompe_os_outros(monkeypatch):
    lote1 = [RawPickInput("p1", "t1")]
    lote2 = [RawPickInput("p2", "t2")]

    def fake_extrair_lote(client, lote):
        if lote is lote1:
            raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
        return [_palpite(raw_pick_id="p2")], {"p2"}, _Usage(10, 5)

    monkeypatch.setattr("scripts.extract_picks.extrair_lote", fake_extrair_lote)

    palpites, processados, tokens_in, tokens_out = processar_lotes(client=None, lotes=[lote1, lote2])

    assert [p.raw_pick_id for p in palpites] == ["p2"]
    assert processados == {"p2"}
    assert (tokens_in, tokens_out) == (10, 5)


def test_processar_lotes_json_truncado_nao_interrompe_lotes_seguintes(monkeypatch):
    # stop_reason=max_tokens no meio de um lote grande pode truncar o
    # JSON da resposta - json.loads levanta JSONDecodeError, que nao e
    # anthropic.APIError, entao precisa de tratamento proprio.
    lote1 = [RawPickInput("p1", "t1")]
    lote2 = [RawPickInput("p2", "t2")]

    def fake_extrair_lote(client, lote):
        if lote is lote1:
            raise json.JSONDecodeError("truncado", doc="{", pos=1)
        return [_palpite(raw_pick_id="p2")], {"p2"}, _Usage(10, 5)

    monkeypatch.setattr("scripts.extract_picks.extrair_lote", fake_extrair_lote)

    palpites, processados, _, _ = processar_lotes(client=None, lotes=[lote1, lote2])

    assert [p.raw_pick_id for p in palpites] == ["p2"]
    assert processados == {"p2"}


def test_processar_lotes_resposta_sem_bloco_de_texto_nao_interrompe_lotes_seguintes(monkeypatch):
    # Ex.: stop_reason="refusal" - response.content sem bloco "text",
    # StopIteration em extrair_lote. Mesma isolacao por lote.
    lote1 = [RawPickInput("p1", "t1")]
    lote2 = [RawPickInput("p2", "t2")]

    def fake_extrair_lote(client, lote):
        if lote is lote1:
            raise StopIteration
        return [_palpite(raw_pick_id="p2")], {"p2"}, _Usage(10, 5)

    monkeypatch.setattr("scripts.extract_picks.extrair_lote", fake_extrair_lote)

    palpites, processados, _, _ = processar_lotes(client=None, lotes=[lote1, lote2])

    assert [p.raw_pick_id for p in palpites] == ["p2"]
    assert processados == {"p2"}


def test_processar_lotes_nao_marca_post_ausente_na_resposta_como_processado(monkeypatch):
    lote = [RawPickInput("p1", "t1"), RawPickInput("p2", "t2")]

    def fake_extrair_lote(client, lote_recebido):
        # Modelo so respondeu por p1, omitiu p2 - p2 nao deve ser marcado
        # como processado (fica pendente pro proximo run).
        return [_palpite(raw_pick_id="p1")], {"p1"}, _Usage(10, 5)

    monkeypatch.setattr("scripts.extract_picks.extrair_lote", fake_extrair_lote)

    palpites, processados, _, _ = processar_lotes(client=None, lotes=[lote])

    assert processados == {"p1"}
