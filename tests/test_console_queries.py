from datetime import date

from app.console.queries import (
    EstadoEtapaDetalhado,
    EstadoRun,
    HistoricoColeta,
    carregar_estado_run,
    encerradas_sem_liquidacao,
    historico_coleta,
    mensagens_expiradas,
    orfaos_aguardando_partida,
    quota_mes,
    revisao_manual_pendente,
)
from tests._fakes import FakeCursor


def test_carregar_estado_run_nenhum_run_hoje():
    cur = FakeCursor(fetchone_results=[None])

    estado = carregar_estado_run(cur, date(2026, 8, 11))

    assert estado == EstadoRun(existe=False, status=None, etapa_atual=None, etapas=())
    assert len(cur.queries) == 1  # nao consulta pipeline_stages sem run


def test_carregar_estado_run_completa_etapas_ausentes_como_pendente():
    cur = FakeCursor(
        fetchone_results=[("run-1", "degradado", "slate")],
        fetchall_results=[
            [
                ("fixtures", 1, "ok", 2, 0, None),
                ("coleta", 2, "ok", 7, 0, {"subetapas": {}}),
            ]
        ],
    )

    estado = carregar_estado_run(cur, date(2026, 8, 11))

    assert estado.existe is True
    assert estado.status == "degradado"
    assert estado.etapa_atual == "slate"
    assert len(estado.etapas) == 6  # todas as 6, mesmo as 4 nao presentes no banco ainda

    por_nome = {e.nome: e for e in estado.etapas}
    assert por_nome["fixtures"] == EstadoEtapaDetalhado(
        nome="fixtures", ordem=1, status="ok", itens_ok=2, itens_erro=0, detalhe={}
    )
    assert por_nome["coleta"].detalhe == {"subetapas": {}}
    assert por_nome["extracao"] == EstadoEtapaDetalhado(
        nome="extracao", ordem=3, status="pendente", itens_ok=0, itens_erro=0, detalhe={}
    )


def test_carregar_estado_run_etapas_na_ordem_de_etapas():
    cur = FakeCursor(fetchone_results=[("run-1", "rodando", "coleta")], fetchall_results=[[]])

    estado = carregar_estado_run(cur, date(2026, 8, 11))

    assert [e.nome for e in estado.etapas] == ["fixtures", "coleta", "extracao", "matching", "odds", "slate"]


def test_historico_coleta_mapeia_subetapas():
    cur = FakeCursor(
        fetchall_results=[
            [
                (date(2026, 8, 11), {"subetapas": {"eagle_predict": {"status": "ok"}}}),
                (date(2026, 8, 10), None),
            ]
        ]
    )

    historico = historico_coleta(cur, dias=7)

    assert historico == [
        HistoricoColeta(data=date(2026, 8, 11), subetapas={"eagle_predict": {"status": "ok"}}),
        HistoricoColeta(data=date(2026, 8, 10), subetapas={}),
    ]
    sql, params = cur.queries[0]
    assert "etapa = 'coleta'" in sql
    assert "order by r.data_referencia desc" in sql
    assert params == (7,)


def test_quota_mes_retorna_chamadas_e_limite():
    cur = FakeCursor(fetchone_results=[(15, 250)])

    chamadas, limite = quota_mes(cur, "2026-08")

    assert (chamadas, limite) == (15, 250)
    assert cur.queries[0][1] == ("2026-08",)


def test_quota_mes_sem_linha_retorna_zero_e_none():
    cur = FakeCursor(fetchone_results=[None])
    assert quota_mes(cur, "2026-08") == (0, None)


def test_orfaos_aguardando_partida_filtra_tipo_sem_fixture():
    cur = FakeCursor(fetchone_results=[(192,)])

    assert orfaos_aguardando_partida(cur) == 192
    assert cur.queries[0][1] == ("sem_fixture",)


def test_encerradas_sem_liquidacao_junta_picks_e_pick_results():
    cur = FakeCursor(fetchone_results=[(3,)])

    resultado = encerradas_sem_liquidacao(cur, horas=12)

    assert resultado == 3
    sql, params = cur.queries[0]
    assert "join picks" in sql
    assert "pick_results" in sql
    assert "pr.id is null" in sql
    assert params == (12,)


def test_mensagens_expiradas_conta_status_expirada():
    cur = FakeCursor(fetchone_results=[(0,)])

    assert mensagens_expiradas(cur) == 0
    assert "'expirada'" in cur.queries[0][0]


def test_revisao_manual_pendente_filtra_nao_liquidavel_nao_revisado():
    cur = FakeCursor(fetchone_results=[(4,)])

    assert revisao_manual_pendente(cur) == 4
    sql = cur.queries[0][0]
    assert "'nao_liquidavel'" in sql and "revisado_por_humano = false" in sql
