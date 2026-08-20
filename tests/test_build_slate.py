from datetime import date, datetime, timezone

from app.slate import PickParaSlate
from scripts.build_slate import (
    aplicar_decisoes_conflito,
    buscar_picks_candidatos,
    buscar_rascunho_existente,
    criar_ou_reaproveitar_slate,
    existe_correcao_em_andamento,
    existe_curadoria_em_andamento,
    inserir_slate_picks,
)
from tests._fakes import FakeCursor


def _pick(pick_id="p1") -> PickParaSlate:
    return PickParaSlate(
        pick_id=pick_id, fixture_id="fix-1", mercado="1x2", selecao="casa",
        time_casa="Time A", time_fora="Time B",
        odd_referencia=1.85, odd_referencia_em=None, odd_referencia_origem="fonte",
        odd_minima=1.5, confianca_tipster=0.9,
    )


_CORTE = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def test_buscar_picks_candidatos_mapeia_colunas():
    kickoff_apos_corte = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)
    cur = FakeCursor(
        fetchall_results=[
            [("p1", "fix-1", "1x2", "casa", "Time A", "Time B", 1.85, None, "fonte", 1.5, 0.9, kickoff_apos_corte)]
        ]
    )

    picks, excluidos = buscar_picks_candidatos(cur, _CORTE)

    assert picks == [_pick()]
    assert excluidos == []
    sql = cur.queries[0][0]
    assert "status = 'vinculado'" in sql
    assert "odd_referencia is not null" in sql
    assert "interval '24 hours'" in sql
    assert "quarentena is not true" in sql


def test_buscar_picks_candidatos_exclui_kickoff_antes_do_corte():
    kickoff_antes_do_corte = datetime(2026, 8, 11, 11, 0, tzinfo=timezone.utc)
    cur = FakeCursor(
        fetchall_results=[
            [("p1", "fix-1", "1x2", "casa", "Time A", "Time B", 1.85, None, "fonte", 1.5, 0.9, kickoff_antes_do_corte)]
        ]
    )

    picks, excluidos = buscar_picks_candidatos(cur, _CORTE)

    assert picks == []
    assert excluidos == ["p1"]


def test_buscar_picks_candidatos_confianca_ausente_vira_zero():
    kickoff_apos_corte = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)
    cur = FakeCursor(
        fetchall_results=[
            [("p1", "fix-1", "1x2", "casa", "Time A", "Time B", 1.85, None, "fonte", 1.5, None, kickoff_apos_corte)]
        ]
    )

    picks, _ = buscar_picks_candidatos(cur, _CORTE)

    assert picks[0].confianca_tipster == 0.0


def test_buscar_rascunho_existente_retorna_id_quando_ha_rascunho():
    cur = FakeCursor(fetchone_results=[("slate-1",)])

    assert buscar_rascunho_existente(cur, date(2026, 8, 11)) == "slate-1"
    sql = cur.queries[0][0]
    assert "substitui_slate_id is null" in sql
    assert "curadoria_iniciada_em is null" in sql


def test_existe_correcao_em_andamento_true_quando_ha_rascunho_de_correcao():
    cur = FakeCursor(fetchone_results=[(1,)])

    assert existe_correcao_em_andamento(cur, date(2026, 8, 11)) is True
    assert "substitui_slate_id is not null" in cur.queries[0][0]


def test_existe_correcao_em_andamento_false_quando_nao_ha():
    cur = FakeCursor(fetchone_results=[None])

    assert existe_correcao_em_andamento(cur, date(2026, 8, 11)) is False


def test_existe_curadoria_em_andamento_true_quando_ha_marca():
    cur = FakeCursor(fetchone_results=[(1,)])

    assert existe_curadoria_em_andamento(cur, date(2026, 8, 11)) is True
    sql = cur.queries[0][0]
    assert "curadoria_iniciada_em is not null" in sql
    assert "substitui_slate_id is null" in sql


def test_existe_curadoria_em_andamento_false_quando_nao_ha():
    cur = FakeCursor(fetchone_results=[None])
    assert existe_curadoria_em_andamento(cur, date(2026, 8, 11)) is False


def test_buscar_rascunho_existente_none_quando_nao_ha():
    cur = FakeCursor(fetchone_results=[None])

    assert buscar_rascunho_existente(cur, date(2026, 8, 11)) is None


def test_criar_ou_reaproveitar_slate_reaproveita_e_limpa_slate_picks():
    cur = FakeCursor(fetchone_results=[("slate-1",)])

    slate_id = criar_ou_reaproveitar_slate(cur, date(2026, 8, 11))

    assert slate_id == "slate-1"
    assert len(cur.queries) == 2  # select do rascunho + delete dos slate_picks antigos
    assert "delete from slate_picks" in cur.queries[1][0]


def test_criar_ou_reaproveitar_slate_cria_novo_quando_nao_ha_rascunho():
    cur = FakeCursor(fetchone_results=[None, ("slate-novo",)])

    slate_id = criar_ou_reaproveitar_slate(cur, date(2026, 8, 11))

    assert slate_id == "slate-novo"
    assert "insert into daily_slates" in cur.queries[1][0]


def test_inserir_slate_picks_grava_ordem_sequencial():
    cur = FakeCursor()

    inserir_slate_picks(cur, "slate-1", [_pick("p1"), _pick("p2")])

    assert len(cur.queries) == 2
    _, params1 = cur.queries[0]
    _, params2 = cur.queries[1]
    assert params1[:3] == ("slate-1", "p1", 1)
    assert params2[:3] == ("slate-1", "p2", 2)


def test_aplicar_decisoes_conflito_atualiza_status_e_registra_motivo():
    cur = FakeCursor(fetchone_results=[(1,), (1,)])

    aplicar_decisoes_conflito(cur, [("p1", "descartado"), ("p2", "revisao_manual")])

    assert len(cur.queries) == 4  # 2 updates + 2 upserts em picks_orfaos
    assert "update picks set status" in cur.queries[0][0]
    assert cur.queries[0][1] == ("descartado", "p1")
    assert "insert into picks_orfaos" in cur.queries[1][0]
    assert "update picks set status" in cur.queries[2][0]
    assert cur.queries[2][1] == ("revisao_manual", "p2")
