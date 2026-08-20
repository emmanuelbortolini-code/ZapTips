from app.console.queries import EstadoEtapaDetalhado, EstadoRun
from app.console.rules import avaliar_acesso_curadoria


def _etapa(nome, status, ordem=1, itens_ok=0, itens_erro=0, detalhe=None):
    return EstadoEtapaDetalhado(nome=nome, ordem=ordem, status=status, itens_ok=itens_ok, itens_erro=itens_erro, detalhe=detalhe or {})


def _estado(status, etapa_atual, etapas):
    return EstadoRun(existe=True, status=status, etapa_atual=etapa_atual, etapas=tuple(etapas))


def test_nenhum_run_hoje_bloqueia():
    estado = EstadoRun(existe=False, status=None, etapa_atual=None, etapas=())

    acesso = avaliar_acesso_curadoria(estado)

    assert acesso.liberado is False
    assert "nao rodou hoje" in acesso.motivo_bloqueio


def test_slate_ausente_bloqueia():
    estado = _estado("rodando", "coleta", [_etapa("fixtures", "ok"), _etapa("coleta", "rodando")])

    acesso = avaliar_acesso_curadoria(estado)

    assert acesso.liberado is False
    assert "slate" in acesso.motivo_bloqueio
    assert "coleta" in acesso.motivo_bloqueio


def test_slate_pendente_bloqueia():
    estado = _estado("rodando", "odds", [_etapa("fixtures", "ok"), _etapa("slate", "pendente")])

    acesso = avaliar_acesso_curadoria(estado)

    assert acesso.liberado is False


def test_slate_rodando_bloqueia():
    estado = _estado("rodando", "slate", [_etapa("fixtures", "ok"), _etapa("slate", "rodando")])

    acesso = avaliar_acesso_curadoria(estado)

    assert acesso.liberado is False
    assert "andamento" in acesso.motivo_bloqueio


def test_fixtures_falhou_bloqueia_mesmo_sem_chegar_no_slate():
    estado = _estado("falhou", "fixtures", [_etapa("fixtures", "falhou")])

    acesso = avaliar_acesso_curadoria(estado)

    assert acesso.liberado is False
    assert "fixtures" in acesso.motivo_bloqueio


def test_slate_ok_libera_sem_avisos():
    estado = _estado(
        "pronto", "slate",
        [_etapa("fixtures", "ok"), _etapa("coleta", "ok"), _etapa("extracao", "ok"),
         _etapa("matching", "ok"), _etapa("odds", "ok"), _etapa("slate", "ok")],
    )

    acesso = avaliar_acesso_curadoria(estado)

    assert acesso.liberado is True
    assert acesso.motivo_bloqueio is None
    assert acesso.avisos == ()


def test_slate_degradado_libera_com_aviso_por_etapa_nao_ok():
    estado = _estado(
        "degradado", "slate",
        [
            _etapa("fixtures", "ok"),
            _etapa("coleta", "ok"),
            _etapa("extracao", "degradado", itens_erro=7, detalhe={"motivo": "anthropic_api_key_ausente", "pendentes": 7}),
            _etapa("matching", "ok"),
            _etapa("odds", "ok"),
            _etapa("slate", "ok"),
        ],
    )

    acesso = avaliar_acesso_curadoria(estado)

    assert acesso.liberado is True
    assert len(acesso.avisos) == 1
    aviso = acesso.avisos[0]
    assert aviso.etapa == "extracao"
    assert "anthropic_api_key_ausente" in aviso.mensagem
    assert "7" in aviso.mensagem


def test_aviso_de_coleta_lista_subetapas_com_problema():
    estado = _estado(
        "degradado", "slate",
        [
            _etapa("fixtures", "ok"),
            _etapa("coleta", "degradado", detalhe={"subetapas": {"eagle_predict": {"status": "ok"}, "sda": {"status": "degradado"}}}),
            _etapa("slate", "ok"),
        ],
    )

    acesso = avaliar_acesso_curadoria(estado)

    aviso = next(a for a in acesso.avisos if a.etapa == "coleta")
    assert "sda" in aviso.mensagem
    assert "eagle_predict" not in aviso.mensagem


def test_aviso_generico_por_itens_erro_sem_motivo_ou_subetapas():
    estado = _estado(
        "degradado", "slate",
        [_etapa("fixtures", "ok"), _etapa("matching", "degradado", itens_erro=2), _etapa("slate", "ok")],
    )

    acesso = avaliar_acesso_curadoria(estado)

    aviso = next(a for a in acesso.avisos if a.etapa == "matching")
    assert "2 item" in aviso.mensagem


def test_aviso_generico_sem_detalhe_nenhum_mostra_so_o_status():
    estado = _estado(
        "degradado", "slate",
        [_etapa("fixtures", "ok"), _etapa("odds", "degradado"), _etapa("slate", "ok")],
    )

    acesso = avaliar_acesso_curadoria(estado)

    aviso = next(a for a in acesso.avisos if a.etapa == "odds")
    assert aviso.mensagem == "degradado"


def test_slate_correcao_em_andamento_gera_aviso_mesmo_com_status_ok():
    estado = _estado(
        "pronto", "slate",
        [_etapa("fixtures", "ok"), _etapa("slate", "ok", detalhe={"pulado": "correcao_manual_em_andamento", "data": "2026-08-11"})],
    )

    acesso = avaliar_acesso_curadoria(estado)

    assert acesso.liberado is True
    aviso = next(a for a in acesso.avisos if a.etapa == "slate")
    assert "correcao" in aviso.mensagem.lower()
