import json
from decimal import Decimal

from app.settlement.engine import FixtureEncerrada, FixtureStatTime, PickParaLiquidar, Resolution
from app.settlement.persistencia import (
    PendenteRevisao,
    buscar_picks_pendentes,
    buscar_stats_por_fixture,
    gravar_resultado,
    gravar_revisao_manual,
    listar_pendentes_revisao,
)
from tests._fakes import FakeCursor


def test_buscar_picks_pendentes_mapeia_colunas():
    cur = FakeCursor(
        fetchall_results=[
            [("p1", "1x2", "Home win", None, "Cruzeiro", "Mirassol", "fix-1", "encerrada", 2, 1)]
        ]
    )

    pares = buscar_picks_pendentes(cur)

    assert pares == [
        (
            PickParaLiquidar(
                pick_id="p1", mercado="1x2", selecao="Home win", linha=None,
                time_casa="Cruzeiro", time_fora="Mirassol",
            ),
            FixtureEncerrada(fixture_id="fix-1", status="encerrada", placar_casa=2, placar_fora=1),
        )
    ]
    sql = cur.queries[0][0]
    assert "'vinculado'" in sql and "'encerrada'" in sql and "pick_results" in sql and "pr.id is null" in sql
    # Fase 6d: picks cortados por conflito ou rejeitados pelo piso
    # tambem precisam liquidar, pro relatorio de performance por fonte
    # comparar publicado x nao-publicado na mesma base.
    assert "'descartado'" in sql


def test_buscar_picks_pendentes_converte_linha_para_decimal():
    cur = FakeCursor(
        fetchall_results=[
            [("p1", "over_under", "Mais de 2.5 gols", Decimal("2.5"), "A", "B", "fix-1", "encerrada", 3, 0)]
        ]
    )

    (pick, _fixture), = buscar_picks_pendentes(cur)

    assert pick.linha == Decimal("2.5")


def test_buscar_stats_por_fixture_agrupa_por_fixture():
    cur = FakeCursor(fetchall_results=[[("fix-1", 5, 2, 0), ("fix-1", 4, 1, 1), ("fix-2", 3, 0, 0)]])

    stats = buscar_stats_por_fixture(cur, ["fix-1", "fix-2"])

    assert stats == {
        "fix-1": [
            FixtureStatTime(escanteios=5, cartoes_amarelos=2, cartoes_vermelhos=0),
            FixtureStatTime(escanteios=4, cartoes_amarelos=1, cartoes_vermelhos=1),
        ],
        "fix-2": [FixtureStatTime(escanteios=3, cartoes_amarelos=0, cartoes_vermelhos=0)],
    }


def test_buscar_stats_por_fixture_lista_vazia_nao_consulta():
    cur = FakeCursor()

    assert buscar_stats_por_fixture(cur, []) == {}
    assert cur.queries == []


def test_gravar_resultado_grava_insert_com_evidencia_json():
    cur = FakeCursor()

    gravar_resultado(
        cur, "p1", "fix-1", Resolution("green", {"placar_casa": 2, "placar_fora": 1}), resolver="1x2"
    )

    sql, params = cur.queries[0]
    assert "insert into pick_results" in sql
    assert "on conflict (pick_id) do update" in sql
    pick_id, fixture_id, resultado, resolver, evidencia_json, revisado = params
    assert (pick_id, fixture_id, resultado, resolver, revisado) == ("p1", "fix-1", "green", "1x2", False)
    assert json.loads(evidencia_json) == {"placar_casa": 2, "placar_fora": 1}


def test_gravar_resultado_aceita_nao_liquidavel():
    # Diferente da tabela descartada nesta sessao (pick_liquidacoes):
    # pick_results.resultado aceita 'nao_liquidavel' desde a Fase 0 - o
    # pipeline automatico sempre grava uma linha, mesmo quando ambiguo.
    cur = FakeCursor()

    gravar_resultado(
        cur, "p1", "fix-1", Resolution("nao_liquidavel", {"motivo": "selecao_nao_reconhecida"}), resolver="1x2"
    )

    _, params = cur.queries[0]
    assert params[2] == "nao_liquidavel"
    assert params[5] is False


def test_gravar_revisao_manual_marca_revisado_por_humano():
    cur = FakeCursor()

    gravar_revisao_manual(cur, "p1", "fix-1", "meio_red", "placar divergente do que o sistema usou")

    sql, params = cur.queries[0]
    pick_id, fixture_id, resultado, resolver, evidencia_json, revisado = params
    assert (pick_id, fixture_id, resultado, resolver, revisado) == ("p1", "fix-1", "meio_red", "revisao_manual", True)
    assert json.loads(evidencia_json) == {"motivo": "revisao_manual", "detalhe": "placar divergente do que o sistema usou"}


def test_listar_pendentes_revisao_mapeia_colunas():
    cur = FakeCursor(fetchall_results=[[("p1", "fix-1", "1x2", "texto esquisito", "selecao_nao_reconhecida")]])

    pendentes = listar_pendentes_revisao(cur)

    assert pendentes == [
        PendenteRevisao(pick_id="p1", fixture_id="fix-1", mercado="1x2", selecao="texto esquisito", motivo="selecao_nao_reconhecida")
    ]
    sql = cur.queries[0][0]
    assert "resultado = 'nao_liquidavel'" in sql and "revisado_por_humano = false" in sql
