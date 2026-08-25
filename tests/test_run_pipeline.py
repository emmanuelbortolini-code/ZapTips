import scripts.collect_apwin as collect_apwin
import scripts.collect_eagle_predict as collect_eagle_predict
import scripts.collect_odds as collect_odds
import scripts.collect_sda as collect_sda
import scripts.link_picks as link_picks
import scripts.resolve_odds as resolve_odds
from app.pipeline import ResultadoEtapa
from scripts.run_pipeline import _adaptador_coleta, _adaptador_matching, _adaptador_odds, _parse_forcar_etapa, _rodar_subetapa


def test_parse_forcar_etapa_sem_flag():
    assert _parse_forcar_etapa([]) == frozenset()


def test_parse_forcar_etapa_uma_etapa():
    assert _parse_forcar_etapa(["--forcar-etapa", "odds"]) == frozenset({"odds"})


def test_parse_forcar_etapa_multiplas_etapas():
    assert _parse_forcar_etapa(["--forcar-etapa", "odds", "--forcar-etapa", "slate"]) == frozenset({"odds", "slate"})


def test_parse_forcar_etapa_ignora_flag_sem_valor_no_final():
    assert _parse_forcar_etapa(["--forcar-etapa"]) == frozenset()


def test_rodar_subetapa_devolve_resultado_normal():
    resultado = _rodar_subetapa("x", lambda: ResultadoEtapa(status="ok", itens_ok=5))
    assert resultado == ResultadoEtapa(status="ok", itens_ok=5)


def test_rodar_subetapa_captura_excecao_e_degrada():
    def explode():
        raise RuntimeError("falha de rede")

    resultado = _rodar_subetapa("x", explode)

    assert resultado.status == "degradado"
    assert resultado.detalhe["excecao"] == "RuntimeError"


def test_adaptador_coleta_consolida_eagle_sda_e_apwin(monkeypatch):
    monkeypatch.setattr(collect_eagle_predict, "executar", lambda: ResultadoEtapa(status="ok", itens_ok=9))
    monkeypatch.setattr(collect_sda, "executar", lambda: ResultadoEtapa(status="ok", itens_ok=3))
    monkeypatch.setattr(collect_apwin, "executar", lambda: ResultadoEtapa(status="ok", itens_ok=1))

    resultado = _adaptador_coleta({})

    assert resultado.status == "ok"
    assert resultado.itens_ok == 13


def test_adaptador_coleta_degrada_quando_uma_fonte_falha(monkeypatch):
    monkeypatch.setattr(collect_eagle_predict, "executar", lambda: ResultadoEtapa(status="ok", itens_ok=9))
    monkeypatch.setattr(collect_apwin, "executar", lambda: ResultadoEtapa(status="ok", itens_ok=1))

    def sda_explode():
        raise RuntimeError("falha")

    monkeypatch.setattr(collect_sda, "executar", sda_explode)

    resultado = _adaptador_coleta({})

    assert resultado.status == "degradado"
    assert resultado.detalhe["subetapas"]["sda"]["status"] == "degradado"
    assert resultado.detalhe["subetapas"]["eagle_predict"]["status"] == "ok"
    assert resultado.detalhe["subetapas"]["apwin"]["status"] == "ok"


def test_adaptador_odds_consolida_collect_e_resolve(monkeypatch):
    monkeypatch.setattr(collect_odds, "executar", lambda: ResultadoEtapa(status="ok", itens_ok=4))
    monkeypatch.setattr(resolve_odds, "executar", lambda: ResultadoEtapa(status="ok", itens_ok=1))

    resultado = _adaptador_odds({})

    assert resultado.status == "ok"
    assert resultado.itens_ok == 5


def test_adaptador_matching_conta_tentativa_quando_fixtures_trouxe_novas(monkeypatch):
    capturado = {}

    def fake_executar(contar_tentativa):
        capturado["contar_tentativa"] = contar_tentativa
        return ResultadoEtapa(status="ok")

    monkeypatch.setattr(link_picks, "executar", fake_executar)

    _adaptador_matching({"fixtures": ResultadoEtapa(status="ok", detalhe={"novas": 3})})

    assert capturado["contar_tentativa"] is True


def test_adaptador_matching_nao_conta_tentativa_quando_fixtures_nao_trouxe_novas(monkeypatch):
    capturado = {}

    def fake_executar(contar_tentativa):
        capturado["contar_tentativa"] = contar_tentativa
        return ResultadoEtapa(status="ok")

    monkeypatch.setattr(link_picks, "executar", fake_executar)

    _adaptador_matching({"fixtures": ResultadoEtapa(status="ok", detalhe={"novas": 0})})

    assert capturado["contar_tentativa"] is False


def test_adaptador_matching_nao_conta_tentativa_quando_fixtures_ausente(monkeypatch):
    capturado = {}

    def fake_executar(contar_tentativa):
        capturado["contar_tentativa"] = contar_tentativa
        return ResultadoEtapa(status="ok")

    monkeypatch.setattr(link_picks, "executar", fake_executar)

    _adaptador_matching({})

    assert capturado["contar_tentativa"] is False
