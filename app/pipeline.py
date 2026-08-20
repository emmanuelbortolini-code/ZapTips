"""Estado puro do orquestrador de pipeline (Fase 5a) - catalogo de etapas,
maquina de estado de transicao entre elas e agregacao de resultado. Sem
I/O: le e devolve so os dicionarios de status que scripts/run_pipeline.py
monta a partir do banco, mesmo principio de app/matcher.py e app/slate.py
(logica testavel sem Postgres, script fino cuida da leitura/escrita).

Seis etapas na ordem da especificacao (Fase 5, "Sincronizacao: execucao
diaria com etapas"). So `fixtures` aborta o run inteiro se falhar - as
demais sempre degradam (nunca fecham como `falhou`), entao a regra "etapa
so inicia quando a anterior fechar ok ou degradado" nunca trava o
pipeline no meio, exceto pelo abort explicito da etapa 1."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Literal, Mapping
from zoneinfo import ZoneInfo

StatusEtapa = Literal["pendente", "rodando", "ok", "degradado", "falhou"]
StatusRun = Literal["rodando", "pronto", "degradado", "falhou"]

# O produto e todo fuso Brasilia (envio 9h, corte de kickoff 11h30) - um
# run disparado as 22h BRT ja seria dia seguinte em UTC puro, abrindo e
# curando o slate errado (D6, CLAUDE.md Fase 5a). Brasil nao observa
# horario de verao desde 2019, mas usa ZoneInfo (nao offset fixo) porque
# essa e a fonte de verdade do SO/tzdata, sem precisar reagir manualmente
# se a regra mudar de novo.
FUSO_OPERACIONAL = ZoneInfo("America/Sao_Paulo")


def data_operacional(agora_utc: datetime | None = None) -> date:
    agora = agora_utc if agora_utc is not None else datetime.now(timezone.utc)
    return agora.astimezone(FUSO_OPERACIONAL).date()


def limites_utc_do_dia(data_ref: date) -> tuple[datetime, datetime]:
    # Extraido de app/relatorio_diario.py (Fase 7), onde nasceu como
    # `_limites_utc_do_dia` privada - reaproveitado agora por
    # app/console/queries.py pelo mesmo motivo que a funcao existe:
    # `coluna::date = %s` avalia no fuso da SESSAO do Postgres (UTC por
    # padrao), nao no fuso operacional. Um evento as 21h30 BRT e 00h30
    # UTC do dia seguinte - contado no dia errado se comparado por
    # ::date puro. Calculando os limites UTC do dia BRASILEIRO aqui, a
    # comparacao por intervalo (>= inicio, < fim) fica correta
    # independente do fuso da sessao.
    inicio_local = datetime.combine(data_ref, time.min, tzinfo=FUSO_OPERACIONAL)
    fim_local = inicio_local + timedelta(days=1)
    return inicio_local.astimezone(timezone.utc), fim_local.astimezone(timezone.utc)


def segunda_da_semana_anterior(hoje: date) -> date:
    """Data (segunda-feira) que abre a semana ISO anterior a `hoje` -
    usada pelo resumo semanal (Fase 6e), que roda as segundas e cobre a
    semana que acabou de fechar (segunda-domingo).

    `hoje` nao precisa ser uma segunda-feira: sempre volta pra segunda da
    semana corrente primeiro (`hoje - hoje.weekday() dias`), depois mais
    7 pra semana anterior - o job continua correto mesmo rodando atrasado
    (ex.: terca, se o agendador ficou fora do ar na segunda). Os limites
    UTC da janela de 7 dias que comeca nessa data vem de
    `limites_utc_do_dia`, chamado duas vezes pelo chamador (inicio e
    inicio+6 dias) - sem duplicar aqui a logica de fuso/DST que ja existe
    la."""
    segunda_desta_semana = hoje - timedelta(days=hoje.weekday())
    return segunda_desta_semana - timedelta(days=7)


@dataclass(frozen=True)
class EtapaSpec:
    ordem: int
    nome: str
    aborta_run_se_falhar: bool


ETAPAS: tuple[EtapaSpec, ...] = (
    EtapaSpec(1, "fixtures", True),
    EtapaSpec(2, "coleta", False),
    EtapaSpec(3, "extracao", False),
    EtapaSpec(4, "matching", False),
    EtapaSpec(5, "odds", False),
    EtapaSpec(6, "slate", False),
)


@dataclass(frozen=True)
class ResultadoEtapa:
    status: Literal["ok", "degradado", "falhou"]
    itens_ok: int = 0
    itens_erro: int = 0
    detalhe: Mapping[str, object] = field(default_factory=dict)


def montar_status_por_etapa(resultados: Mapping[str, ResultadoEtapa]) -> dict[str, StatusEtapa]:
    return {etapa.nome: resultados[etapa.nome].status if etapa.nome in resultados else "pendente" for etapa in ETAPAS}


def pode_iniciar(etapa: EtapaSpec, status_por_etapa: Mapping[str, StatusEtapa]) -> bool:
    if etapa.ordem == 1:
        return True
    anterior = next(e for e in ETAPAS if e.ordem == etapa.ordem - 1)
    status_anterior = status_por_etapa.get(anterior.nome)
    return status_anterior in ("ok", "degradado")


def deve_pular(etapa: EtapaSpec, status_por_etapa: Mapping[str, StatusEtapa], forcadas: frozenset[str]) -> bool:
    if etapa.nome in forcadas:
        return False
    return status_por_etapa.get(etapa.nome) == "ok"


def consolidar_subetapas(sub: Mapping[str, ResultadoEtapa]) -> ResultadoEtapa:
    status = "ok" if all(r.status == "ok" for r in sub.values()) else "degradado"
    return ResultadoEtapa(
        status=status,
        itens_ok=sum(r.itens_ok for r in sub.values()),
        itens_erro=sum(r.itens_erro for r in sub.values()),
        detalhe={
            "subetapas": {
                nome: {"status": r.status, "itens_ok": r.itens_ok, "itens_erro": r.itens_erro, "detalhe": dict(r.detalhe)}
                for nome, r in sub.items()
            }
        },
    )


def degradar(exc: BaseException) -> ResultadoEtapa:
    # Nunca embute str(exc) bruto no detalhe - precedente critico da Fase
    # 1g (_erro_sem_segredo): erro de chamada autenticada do httpx
    # stringifica a URL completa, incluindo apiKey/token na query string.
    return ResultadoEtapa(status="degradado", itens_erro=1, detalhe={"excecao": type(exc).__name__})


def consolidar_status_run(status_por_etapa: Mapping[str, StatusEtapa]) -> StatusRun:
    valores = set(status_por_etapa.values())
    if "falhou" in valores:
        return "falhou"
    if valores == {"ok"}:
        return "pronto"
    return "degradado"


Adaptador = Callable[[Mapping[str, ResultadoEtapa]], ResultadoEtapa]


def avancar_etapas(
    resultados_iniciais: Mapping[str, ResultadoEtapa],
    adaptadores: Mapping[str, Adaptador],
    forcadas: frozenset[str] = frozenset(),
    ao_iniciar_etapa: Callable[[EtapaSpec], None] = lambda etapa: None,
    ao_fechar_etapa: Callable[[EtapaSpec, ResultadoEtapa], None] = lambda etapa, resultado: None,
) -> tuple[dict[str, ResultadoEtapa], StatusRun, str | None]:
    """Laco de orquestracao puro - decide qual etapa roda, pula, ou aborta
    o run, sem tocar em banco. scripts/run_pipeline.py injeta os
    callbacks ao_iniciar_etapa/ao_fechar_etapa pra persistir cada
    transicao de etapa (curta, sem conexao aberta durante o trabalho de
    rede do adaptador - achado da Fase 1f reaplicado aqui) e os
    adaptadores reais (que chamam scripts.*.executar()). Testes usam
    adaptadores e callbacks fake, sem Postgres.

    Devolve o resultado final por etapa (pra fechar_run consolidar o
    status do run) e qual foi a ultima etapa tocada (etapa_atual)."""
    resultados = dict(resultados_iniciais)
    etapa_atual: str | None = None

    for etapa in ETAPAS:
        status_atual = montar_status_por_etapa(resultados)
        if deve_pular(etapa, status_atual, forcadas):
            continue
        if not pode_iniciar(etapa, status_atual):
            # Defesa em profundidade, nao alcancavel com o ETAPAS atual:
            # o proprio laco garante que, ao chegar aqui, a etapa
            # anterior ja fechou ok/degradado (ou o run ja abortou antes).
            # So passa a valer se uma configuracao futura de ETAPAS
            # permitir mais de uma etapa abortante, ou se resultados
            # vier de um estado externo corrompido.
            break

        ao_iniciar_etapa(etapa)
        etapa_atual = etapa.nome
        try:
            resultado = adaptadores[etapa.nome](resultados)
        except Exception as exc:  # noqa: BLE001 - fronteira deliberada, ver degradar()
            resultado = (
                ResultadoEtapa(status="falhou", itens_erro=1, detalhe={"excecao": type(exc).__name__})
                if etapa.aborta_run_se_falhar
                else degradar(exc)
            )

        if resultado.status == "falhou" and not etapa.aborta_run_se_falhar:
            # So a etapa 1 pode fechar o run como falhou (F5, CLAUDE.md
            # Fase 5a) - se um adaptador de outra etapa devolver "falhou"
            # sem levantar excecao (nao deveria, mas o tipo nao impede),
            # sanitiza pra degradado em vez de propagar um abort indevido.
            resultado = ResultadoEtapa(status="degradado", itens_ok=resultado.itens_ok, itens_erro=resultado.itens_erro, detalhe=resultado.detalhe)

        ao_fechar_etapa(etapa, resultado)
        resultados = {**resultados, etapa.nome: resultado}

        if resultado.status == "falhou" and etapa.aborta_run_se_falhar:
            break

    status_final = consolidar_status_run(montar_status_por_etapa(resultados))
    return resultados, status_final, etapa_atual
