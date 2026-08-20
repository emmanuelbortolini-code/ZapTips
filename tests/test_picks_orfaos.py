from app.picks_orfaos import (
    MAX_TENTATIVAS_MATCHING,
    TIPO_EXCLUIDO,
    TIPO_SEM_FIXTURE,
    deve_escalar_para_revisao,
    limpar_pick_orfao,
    upsert_pick_orfao,
)
from tests._fakes import FakeCursor


def test_upsert_pick_orfao_grava_com_on_conflict_pick_e_tipo():
    cur = FakeCursor(fetchone_results=[(1,)])

    tentativas = upsert_pick_orfao(cur, "p1", "sem odd")

    assert tentativas == 1
    sql, params = cur.queries[0]
    assert "on conflict (pick_id, tipo)" in sql
    assert "tentativas = picks_orfaos.tentativas + 1" in sql
    assert "returning tentativas" in sql
    assert params == ("p1", TIPO_EXCLUIDO, "sem odd")


def test_upsert_pick_orfao_default_tipo_e_excluido():
    cur = FakeCursor(fetchone_results=[(1,)])

    upsert_pick_orfao(cur, "p1", "conflito")

    assert cur.queries[0][1][1] == "excluido"


def test_upsert_pick_orfao_aceita_tipo_sem_fixture():
    cur = FakeCursor(fetchone_results=[(3,)])

    tentativas = upsert_pick_orfao(cur, "p2", "sem fixture na janela", tipo=TIPO_SEM_FIXTURE)

    assert tentativas == 3
    assert cur.queries[0][1] == ("p2", TIPO_SEM_FIXTURE, "sem fixture na janela")


def test_limpar_pick_orfao_deleta_por_pick_e_tipo():
    cur = FakeCursor()

    limpar_pick_orfao(cur, "p1", TIPO_SEM_FIXTURE)

    sql, params = cur.queries[0]
    assert "delete from picks_orfaos" in sql
    assert "tipo = %s" in sql
    assert params == ("p1", TIPO_SEM_FIXTURE)


def test_deve_escalar_para_revisao_abaixo_do_limite():
    assert deve_escalar_para_revisao(MAX_TENTATIVAS_MATCHING - 1) is False


def test_deve_escalar_para_revisao_no_limite():
    assert deve_escalar_para_revisao(MAX_TENTATIVAS_MATCHING) is True


def test_deve_escalar_para_revisao_acima_do_limite():
    assert deve_escalar_para_revisao(MAX_TENTATIVAS_MATCHING + 1) is True
