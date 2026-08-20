import uuid
from datetime import date, datetime, timezone

from app.console.queries import SessaoEnvio, buscar_sessao_aberta, resumo_do_dia, universo_da_sessao
from app.pipeline import limites_utc_do_dia
from tests._fakes import FakeCursor

_DATA = date(2026, 8, 11)
_INICIADA_EM = datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)


def test_buscar_sessao_aberta_devolve_none_quando_nao_ha_linha():
    cur = FakeCursor(fetchone_results=[None])

    assert buscar_sessao_aberta(cur, _DATA) is None


def test_buscar_sessao_aberta_converte_uuid_para_str():
    # Mesma classe de bug real da Fase 5d (buscar_slate_atual): psycopg
    # devolve coluna uuid como uuid.UUID, nao str - uuid.UUID.__eq__(str)
    # nunca e True, o que quebraria _exigir_sessao_aberta_de_hoje contra
    # o path param (sempre string) no Postgres real, invisivel com
    # FakeCursor se o teste nao usar um uuid.UUID de verdade aqui.
    sessao_id = uuid.uuid4()
    slate_id = uuid.uuid4()
    cur = FakeCursor(fetchone_results=[(sessao_id, _DATA, slate_id, "ativa", _INICIADA_EM, None, None, None)])

    sessao = buscar_sessao_aberta(cur, _DATA)

    assert sessao == SessaoEnvio(
        id=str(sessao_id), data=_DATA, slate_id=str(slate_id), status="ativa",
        iniciada_em=_INICIADA_EM, pausada_em=None, retomada_em=None, encerrada_em=None,
    )
    assert isinstance(sessao.id, str)
    assert isinstance(sessao.slate_id, str)


def test_buscar_sessao_aberta_filtra_por_data_e_encerrada_em_null():
    cur = FakeCursor(fetchone_results=[None])

    buscar_sessao_aberta(cur, _DATA)

    sql = cur.queries[0][0]
    assert "data = %s" in sql
    assert "encerrada_em is null" in sql


def test_universo_da_sessao_query_tem_os_dois_termos_do_or_e_assinante_ativo():
    cur = FakeCursor(fetchall_results=[[]])

    universo_da_sessao(cur, _DATA)

    sql = cur.queries[0][0]
    assert "status = 'pronta'" in sql
    assert "m.slate_id in (select id from daily_slates where data = %s)" in sql
    assert "opt_out_em is null" in sql
    assert "status = 'ativo'" in sql


def test_universo_da_sessao_inclui_termo_de_mensagem_fechamento_sem_slate():
    # Achado real (checklist manual de navegador): mensagem tipo
    # 'fechamento' (Fase 6e) sempre tem slate_id NULL - sem esse
    # terceiro termo do OR, um assinante cujo unico fechamento do dia ja
    # tivesse sido resolvido (nao mais 'pronta') cairia do universo,
    # reembaralhando ordem_da_sessao pros demais - o mesmo bug que os
    # outros dois termos do OR ja existem pra evitar.
    cur = FakeCursor(fetchall_results=[[]])

    universo_da_sessao(cur, _DATA)

    sql, params = cur.queries[0]
    assert "m.slate_id is null and m.gerada_em >= %s and m.gerada_em < %s" in sql
    assert params == (_DATA,) + limites_utc_do_dia(_DATA)


def test_universo_da_sessao_converte_ids_para_str():
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    cur = FakeCursor(fetchall_results=[[(u1,), (u2,)]])

    resultado = universo_da_sessao(cur, _DATA)

    assert resultado == [str(u1), str(u2)]


def test_resumo_do_dia_mapeia_contadores_e_lista_de_pulos():
    cur = FakeCursor(
        fetchone_results=[(3, 1, 2)],
        fetchall_results=[[("Fulano", "+5511999990000", "nao atende")]],
    )

    enviadas, expiradas, prontas_restantes, puladas = resumo_do_dia(cur, _DATA)

    assert (enviadas, expiradas, prontas_restantes) == (3, 1, 2)
    assert puladas == [("Fulano", "+5511999990000", "nao atende")]


def test_resumo_do_dia_escopado_por_data_do_slate_nao_por_sessao():
    cur = FakeCursor(fetchone_results=[(0, 0, 0)], fetchall_results=[[]])

    resumo_do_dia(cur, _DATA)

    sql_contadores = cur.queries[0][0]
    assert "ds.data = %s" in sql_contadores
    sql_pulos = cur.queries[1][0]
    assert "ds.data = %s" in sql_pulos
    assert "status = 'pulada'" in sql_pulos


def test_resumo_do_dia_conta_mensagem_de_fechamento_sem_slate():
    # Achado real (checklist manual de navegador, primeira sessao com
    # dado real): uma mensagem tipo 'fechamento' (slate_id NULL por
    # design, Fase 6e) marcada 'enviada' pelo atalho Enter aparecia como
    # "Enviadas: 0" no resumo de fim de sessao - o INNER JOIN antigo em
    # daily_slates excluia toda mensagem de fechamento do resumo, apesar
    # do status em `messages` estar correto. left join + segundo termo
    # do OR (via gerada_em em limites_utc_do_dia) e o que corrige isso.
    cur = FakeCursor(fetchone_results=[(1, 0, 0)], fetchall_results=[[]])

    resumo_do_dia(cur, _DATA)

    sql_contadores, params_contadores = cur.queries[0]
    assert "left join daily_slates" in sql_contadores
    assert "m.slate_id is null and m.gerada_em >= %s and m.gerada_em < %s" in sql_contadores
    assert params_contadores == (_DATA,) + limites_utc_do_dia(_DATA)

    sql_pulos, params_pulos = cur.queries[1]
    assert "left join daily_slates" in sql_pulos
    assert "m.slate_id is null and m.gerada_em >= %s and m.gerada_em < %s" in sql_pulos
    assert params_pulos == (_DATA,) + limites_utc_do_dia(_DATA)
