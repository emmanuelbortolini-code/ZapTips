"""Motor de montagem do `daily_slate` (Fase 4, "Stream unico de
palpites"). Puro - recebe a lista de picks candidatos (ja filtrados por
kickoff nas proximas 24h e por ja terem odd de referencia resolvida,
filtros que dependem de "agora" e ficam no script chamador) e devolve
quem entra no slate e quais decisoes de status precisam ser aplicadas
nos picks que ficaram de fora por conflito.

Conflito (documento original, "Montagem", passo 2-3): duas selecoes
diferentes no mesmo mercado da mesma fixture. Resolvido por consenso
(mais picks concordando na mesma selecao); empate manda a fixture+mercado
inteira pra revisao manual, nunca decide sozinho.

Agrupamento por selecao usa `app.odds_resolution.normalizar_selecao_1x2`
quando o mercado e' `1x2` (achado do code-reviewer: duas fontes podem
concordar no mesmo resultado com fraseado diferente - "Home win" vs
"Vitória do Fluminense" - e comparar o texto bruto tratava isso como
desacordo, diluindo o consenso real). Mercados fora de `1x2` ainda
comparam texto bruto (nao existe normalizador equivalente pra
over_under/ambas_marcam/handicap ainda - falta comparar tambem `linha`,
que a extracao da Fase 3 nem populou; fica documentado como limitacao
conhecida, nao resolvida especulativamente aqui).

Limite diario (`SLATE_MAX_PICKS`): quando sobra mais candidato do que
cabe, corta pelos de menor `confianca_tipster` (confianca de extracao da
Fase 3). Decisao desta sessao, nao especificada no documento original -
o pick cortado so por limite **nao muda de status** (segue `vinculado`,
elegivel de novo no proximo dia/run), diferente do pick perdedor de
conflito (que teve alguem escolhido no lugar dele pra mesma fixture,
entao vira `descartado`).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from app.odds_resolution import normalizar_selecao_1x2

DecisaoStatus = Literal["descartado", "revisao_manual"]

_FUSO_ENVIO = ZoneInfo("America/Sao_Paulo")


@dataclass(frozen=True)
class PickParaSlate:
    pick_id: str
    fixture_id: str
    mercado: str
    selecao: str
    time_casa: str | None
    time_fora: str | None
    odd_referencia: float
    odd_referencia_em: datetime | None
    odd_referencia_origem: str | None
    odd_minima: float
    confianca_tipster: float


def chave_selecao(pick: PickParaSlate) -> str:
    if pick.mercado == "1x2":
        normalizada = normalizar_selecao_1x2(pick.selecao, pick.time_casa, pick.time_fora)
        if normalizada is not None:
            return normalizada
    return pick.selecao


def detectar_e_resolver_conflitos(
    picks: list[PickParaSlate],
) -> tuple[list[PickParaSlate], list[tuple[str, DecisaoStatus]]]:
    por_grupo: dict[tuple[str, str], list[PickParaSlate]] = defaultdict(list)
    for pick in picks:
        por_grupo[(pick.fixture_id, pick.mercado)].append(pick)

    sobreviventes: list[PickParaSlate] = []
    decisoes: list[tuple[str, DecisaoStatus]] = []

    for grupo in por_grupo.values():
        if len({chave_selecao(p) for p in grupo}) == 1:
            sobreviventes.extend(grupo)
            continue

        por_selecao: dict[str, list[PickParaSlate]] = defaultdict(list)
        for p in grupo:
            por_selecao[chave_selecao(p)].append(p)

        maior_consenso = max(len(subgrupo) for subgrupo in por_selecao.values())
        vencedores_possiveis = [sg for sg in por_selecao.values() if len(sg) == maior_consenso]

        if len(vencedores_possiveis) > 1:
            # Empate no consenso - a partida inteira (fixture+mercado)
            # vai pra revisao manual, nunca decide sozinho entre iguais.
            decisoes.extend((p.pick_id, "revisao_manual") for p in grupo)
            continue

        vencedor_ids = {p.pick_id for p in vencedores_possiveis[0]}
        sobreviventes.extend(vencedores_possiveis[0])
        decisoes.extend((p.pick_id, "descartado") for p in grupo if p.pick_id not in vencedor_ids)

    return sobreviventes, decisoes


def montar_slate(
    picks: list[PickParaSlate], slate_max_picks: int
) -> tuple[list[PickParaSlate], list[tuple[str, DecisaoStatus]]]:
    sobreviventes, decisoes_conflito = detectar_e_resolver_conflitos(picks)
    ordenados = sorted(sobreviventes, key=lambda p: p.confianca_tipster, reverse=True)
    incluidos = ordenados[:slate_max_picks]
    return incluidos, decisoes_conflito


def instante_de_corte(
    data_slate: date, horario_envio: str, intervalo_segundos: int, n_assinantes: int, antecedencia_horas: int
) -> datetime:
    # Nivel A do corte de antecedencia (D2, Fase 5d): "nao enviar pra
    # jogo que comeca em menos de X horas" so e correto se calculado
    # contra o FIM ESTIMADO da sessao de envio, nao contra o momento em
    # que o slate e montado (de madrugada) - senao uma partida que
    # comeca pouco depois do horario de envio passaria pelo corte na
    # montagem e ainda assim ficaria dentro da janela proibida quando a
    # sessao chegasse nela de verdade. O nivel B (app.messages_generator.
    # respeita_antecedencia_minima) e a defesa que roda no momento real
    # da geracao, protegendo mesmo se a aprovacao atrasar.
    hora, minuto = (int(x) for x in horario_envio.split(":"))
    inicio_sessao = datetime.combine(data_slate, time(hora, minuto), tzinfo=_FUSO_ENVIO)
    duracao_estimada = timedelta(seconds=intervalo_segundos * max(1, n_assinantes))
    corte = inicio_sessao + duracao_estimada + timedelta(hours=antecedencia_horas)
    return corte.astimezone(timezone.utc)
