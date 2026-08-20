from datetime import date, datetime, timezone

import httpx
import pytest

from app.pipeline import (
    ETAPAS,
    ResultadoEtapa,
    avancar_etapas,
    consolidar_status_run,
    consolidar_subetapas,
    data_operacional,
    degradar,
    deve_pular,
    limites_utc_do_dia,
    pode_iniciar,
    montar_status_por_etapa,
    segunda_da_semana_anterior,
)


def _etapa(nome: str):
    return next(e for e in ETAPAS if e.nome == nome)


def test_etapas_na_ordem_da_spec():
    assert [e.nome for e in ETAPAS] == ["fixtures", "coleta", "extracao", "matching", "odds", "slate"]


def test_so_fixtures_aborta_o_run_se_falhar():
    assert _etapa("fixtures").aborta_run_se_falhar is True
    for nome in ("coleta", "extracao", "matching", "odds", "slate"):
        assert _etapa(nome).aborta_run_se_falhar is False


def test_pode_iniciar_fixtures_sem_predecessor():
    assert pode_iniciar(_etapa("fixtures"), {}) is True


@pytest.mark.parametrize("status_anterior", ["ok", "degradado"])
def test_pode_iniciar_true_quando_anterior_ok_ou_degradado(status_anterior):
    assert pode_iniciar(_etapa("coleta"), {"fixtures": status_anterior}) is True


@pytest.mark.parametrize("status_anterior", ["falhou", "pendente", "rodando"])
def test_pode_iniciar_false_quando_anterior_nao_fechou_bem(status_anterior):
    assert pode_iniciar(_etapa("coleta"), {"fixtures": status_anterior}) is False


def test_pode_iniciar_false_quando_anterior_ausente():
    assert pode_iniciar(_etapa("coleta"), {}) is False


def test_deve_pular_quando_ja_ok_e_nao_forcada():
    assert deve_pular(_etapa("fixtures"), {"fixtures": "ok"}, frozenset()) is True


def test_deve_pular_false_quando_forcada():
    assert deve_pular(_etapa("fixtures"), {"fixtures": "ok"}, frozenset({"fixtures"})) is False


def test_deve_pular_false_quando_degradado():
    assert deve_pular(_etapa("fixtures"), {"fixtures": "degradado"}, frozenset()) is False


def test_deve_pular_false_quando_nunca_rodou():
    assert deve_pular(_etapa("fixtures"), {}, frozenset()) is False


def test_consolidar_status_run_todas_ok_vira_pronto():
    status = {e.nome: "ok" for e in ETAPAS}
    assert consolidar_status_run(status) == "pronto"


def test_consolidar_status_run_uma_degradada_vira_degradado():
    status = {e.nome: "ok" for e in ETAPAS}
    status["odds"] = "degradado"
    assert consolidar_status_run(status) == "degradado"


def test_consolidar_status_run_uma_falhou_vira_falhou():
    status = {e.nome: "pendente" for e in ETAPAS}
    status["fixtures"] = "falhou"
    assert consolidar_status_run(status) == "falhou"


def test_consolidar_status_run_falhou_tem_prioridade_sobre_degradado():
    status = {e.nome: "degradado" for e in ETAPAS}
    status["fixtures"] = "falhou"
    assert consolidar_status_run(status) == "falhou"


def test_consolidar_subetapas_soma_contadores_e_degrada():
    sub = {
        "eagle_predict": ResultadoEtapa(status="ok", itens_ok=9, itens_erro=0),
        "sda": ResultadoEtapa(status="falhou", itens_ok=0, itens_erro=1, detalhe={"excecao": "HTTPError"}),
    }

    resultado = consolidar_subetapas(sub)

    assert resultado.status == "degradado"
    assert resultado.itens_ok == 9
    assert resultado.itens_erro == 1
    assert resultado.detalhe["subetapas"]["sda"]["status"] == "falhou"
    assert resultado.detalhe["subetapas"]["eagle_predict"]["status"] == "ok"


def test_consolidar_subetapas_todas_ok_vira_ok():
    sub = {
        "bet365": ResultadoEtapa(status="ok", itens_ok=1),
        "betano": ResultadoEtapa(status="ok", itens_ok=1),
    }

    resultado = consolidar_subetapas(sub)

    assert resultado.status == "ok"
    assert resultado.itens_ok == 2


def test_status_por_etapa_marca_pendente_quando_nunca_fechou():
    resultados = {"fixtures": ResultadoEtapa(status="ok", itens_ok=42)}

    status = montar_status_por_etapa(resultados)

    assert status["fixtures"] == "ok"
    assert status["coleta"] == "pendente"
    assert status["slate"] == "pendente"


def test_status_por_etapa_cobre_todas_as_etapas():
    assert set(montar_status_por_etapa({}).keys()) == {e.nome for e in ETAPAS}


def test_data_operacional_usa_fuso_brasilia_nao_utc():
    # 23h de Brasilia em 10/08 ja e 02h UTC do dia 11/08 - se usasse UTC
    # puro, o pipeline abriria o run do dia errado a noite (D6, CLAUDE.md
    # Fase 5a).
    agora_utc = datetime(2026, 8, 11, 2, 30, tzinfo=timezone.utc)

    assert data_operacional(agora_utc) == date(2026, 8, 10)


def test_data_operacional_manha_utc_mesmo_dia_em_brasilia():
    agora_utc = datetime(2026, 8, 11, 14, 0, tzinfo=timezone.utc)

    assert data_operacional(agora_utc) == date(2026, 8, 11)


class _AdaptadorRastreado:
    """Envolve um adaptador fake e registra a ordem/quantidade de chamadas
    em `chamadas`, pra testar o laco de avancar_etapas sem depender de
    lambdas encadeadas."""

    def __init__(self, chamadas: list[str], resultado: ResultadoEtapa | None = None, excecao: BaseException | None = None):
        self._chamadas = chamadas
        self._resultado = resultado or ResultadoEtapa(status="ok")
        self._excecao = excecao

    def __call__(self, nome: str):
        def adaptador(resultados):
            self._chamadas.append(nome)
            if self._excecao is not None:
                raise self._excecao
            return self._resultado

        return adaptador


def _adaptadores_todos_ok(chamadas: list[str]) -> dict:
    fabrica = _AdaptadorRastreado(chamadas)
    return {e.nome: fabrica(e.nome) for e in ETAPAS}


def test_avancar_etapas_caminho_feliz_todas_ok():
    chamadas: list[str] = []
    adaptadores = _adaptadores_todos_ok(chamadas)

    resultados, status_final, etapa_atual = avancar_etapas({}, adaptadores)

    assert status_final == "pronto"
    assert etapa_atual == "slate"
    assert chamadas == ["fixtures", "coleta", "extracao", "matching", "odds", "slate"]
    assert all(resultados[e.nome].status == "ok" for e in ETAPAS)


def test_avancar_etapas_falha_em_coleta_degrada_mas_continua():
    chamadas: list[str] = []
    adaptadores = _adaptadores_todos_ok(chamadas)
    adaptadores["coleta"] = _AdaptadorRastreado(chamadas, excecao=RuntimeError("falha de rede"))("coleta")

    resultados, status_final, etapa_atual = avancar_etapas({}, adaptadores)

    assert status_final == "degradado"
    assert resultados["coleta"].status == "degradado"
    assert resultados["coleta"].detalhe["excecao"] == "RuntimeError"
    assert chamadas == ["fixtures", "coleta", "extracao", "matching", "odds", "slate"]


def test_avancar_etapas_falha_em_fixtures_aborta_o_run():
    chamadas: list[str] = []
    adaptadores = _adaptadores_todos_ok(chamadas)
    adaptadores["fixtures"] = _AdaptadorRastreado(chamadas, excecao=RuntimeError("ESPN fora do ar"))("fixtures")

    resultados, status_final, etapa_atual = avancar_etapas({}, adaptadores)

    assert status_final == "falhou"
    assert etapa_atual == "fixtures"
    assert chamadas == ["fixtures"]
    assert "coleta" not in resultados


def test_avancar_etapas_odds_falhou_nao_aborta_slate_continua():
    # F5: se um adaptador de uma etapa que nao aborta devolver
    # status="falhou" (nao deveria, mas o tipo nao impede), o run nao
    # aborta - so fixtures pode fechar o run como falhou.
    chamadas: list[str] = []
    adaptadores = _adaptadores_todos_ok(chamadas)
    adaptadores["odds"] = _AdaptadorRastreado(chamadas, resultado=ResultadoEtapa(status="falhou", itens_erro=1))("odds")

    resultados, status_final, etapa_atual = avancar_etapas({}, adaptadores)

    assert "slate" in chamadas
    assert resultados["odds"].status == "degradado"  # sanitizado, nunca falhou fora da etapa 1
    assert status_final == "degradado"


def test_avancar_etapas_resume_pula_etapas_ja_ok():
    resultados_iniciais = {
        "fixtures": ResultadoEtapa(status="ok", itens_ok=10),
        "coleta": ResultadoEtapa(status="ok", itens_ok=5),
    }
    chamadas: list[str] = []
    adaptadores = _adaptadores_todos_ok(chamadas)

    resultados, status_final, etapa_atual = avancar_etapas(resultados_iniciais, adaptadores)

    assert "fixtures" not in chamadas
    assert "coleta" not in chamadas
    assert chamadas == ["extracao", "matching", "odds", "slate"]
    assert status_final == "pronto"


def test_avancar_etapas_resume_reexecuta_etapa_persistida_como_falhou():
    # Etapa que nao e fixtures nunca deveria persistir "falhou" no fluxo
    # normal (avancar_etapas sanitiza pra degradado) - mas se persistir
    # por qualquer motivo (dado antigo, bug corrigido depois), o resume
    # tenta de novo automaticamente, ja que so status "ok" e pulado.
    resultados_iniciais = {
        "fixtures": ResultadoEtapa(status="ok"),
        "coleta": ResultadoEtapa(status="falhou"),
    }
    chamadas: list[str] = []
    adaptadores = _adaptadores_todos_ok(chamadas)

    resultados, status_final, etapa_atual = avancar_etapas(resultados_iniciais, adaptadores)

    assert chamadas == ["coleta", "extracao", "matching", "odds", "slate"]
    assert resultados["coleta"].status == "ok"
    assert status_final == "pronto"


def test_avancar_etapas_forcar_etapa_reexecuta_mesmo_ja_ok():
    resultados_iniciais = {e.nome: ResultadoEtapa(status="ok") for e in ETAPAS}
    chamadas: list[str] = []
    adaptadores = _adaptadores_todos_ok(chamadas)

    avancar_etapas(resultados_iniciais, adaptadores, forcadas=frozenset({"odds"}))

    assert chamadas == ["odds"]


def test_avancar_etapas_chama_callbacks_de_inicio_e_fim():
    chamadas: list[str] = []
    adaptadores = _adaptadores_todos_ok(chamadas)
    iniciadas = []
    fechadas = []

    avancar_etapas(
        {},
        adaptadores,
        ao_iniciar_etapa=lambda etapa: iniciadas.append(etapa.nome),
        ao_fechar_etapa=lambda etapa, resultado: fechadas.append((etapa.nome, resultado.status)),
    )

    assert iniciadas == ["fixtures", "coleta", "extracao", "matching", "odds", "slate"]
    assert fechadas == [(nome, "ok") for nome in iniciadas]


def test_degradar_nunca_vaza_segredo_da_excecao():
    request = httpx.Request("GET", "https://api.oddspapi.io/odds?apiKey=segredo-super-secreto")
    response = httpx.Response(403, request=request, text="restricted")
    exc = httpx.HTTPStatusError("erro", request=request, response=response)

    resultado = degradar(exc)

    assert resultado.status == "degradado"
    assert resultado.itens_erro == 1
    detalhe_texto = repr(resultado.detalhe)
    assert "segredo-super-secreto" not in detalhe_texto
    assert resultado.detalhe["excecao"] == "HTTPStatusError"


# --- limites_utc_do_dia: fuso de Brasilia, nao UTC cru (achado HIGH do
# code-reviewer na Fase 7, movido pra ca da Fase de checklist de sessao -
# a funcao mora aqui desde entao, extraida de app/relatorio_diario.py
# pra ser reaproveitada por app/console/queries.py) ---


def test_limites_utc_do_dia_cobre_a_noite_toda_em_brasilia():
    # 12/08 00h00 BRT = 12/08 03h00 UTC; 13/08 00h00 BRT = 13/08 03h00 UTC.
    inicio_utc, fim_utc = limites_utc_do_dia(date(2026, 8, 12))
    assert inicio_utc == datetime(2026, 8, 12, 3, 0, tzinfo=timezone.utc)
    assert fim_utc == datetime(2026, 8, 13, 3, 0, tzinfo=timezone.utc)


def test_limites_utc_do_dia_um_envio_as_21h30_brt_fica_dentro_do_dia_certo():
    # 21h30 BRT do dia 12 e' 00h30 UTC do dia 13, e um ::date puro
    # contaria esse envio no dia ERRADO (13, nao 12).
    envio_21h30_brt_dia_12 = datetime(2026, 8, 13, 0, 30, tzinfo=timezone.utc)
    inicio_utc, fim_utc = limites_utc_do_dia(date(2026, 8, 12))
    assert inicio_utc <= envio_21h30_brt_dia_12 < fim_utc


# --- segunda_da_semana_anterior (Fase 6e, resumo semanal) -------------------
# 2026-08-10 e 2026-08-17 sao segundas-feiras reais (confirmado via
# date.strftime); 2026-08-19 e uma quarta na MESMA semana que a segunda 17.


def test_segunda_da_semana_anterior_rodando_numa_segunda():
    assert segunda_da_semana_anterior(date(2026, 8, 17)) == date(2026, 8, 10)


def test_segunda_da_semana_anterior_rodando_atrasado_no_meio_da_semana():
    # Agendador fora do ar na segunda, job so roda na quarta seguinte -
    # ainda tem que cobrir a MESMA semana anterior (10 a 16), nao pular
    # pra semana que ainda esta em curso.
    assert segunda_da_semana_anterior(date(2026, 8, 19)) == date(2026, 8, 10)


def test_segunda_da_semana_anterior_rodando_no_domingo():
    assert segunda_da_semana_anterior(date(2026, 8, 16)) == date(2026, 8, 3)
