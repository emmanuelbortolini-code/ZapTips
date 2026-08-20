"""Motor de liquidacao (Fase 6a) - despacha cada pick liquidavel pro
resolver do seu mercado e devolve o resultado categorico + evidencia.

Escopo desta entrega: 1x2 (incluindo dupla chance e DNB, que a extracao
sempre grava como mercado "1x2" - so o texto de `selecao` distingue),
ambas_marcam, over_under (gols), handicap (europeu e asiatico),
escanteios e cartoes (total da partida, via `fixture_stats`). "Cartoes,
condicao por time" (spec, Fase 6a) fica de fora - ver
`app.settlement.selecao.eh_condicao_por_time` para o motivo (sem texto
real pra validar o parser contra).

Regra de ouro herdada do resto do projeto: ambiguidade e dado malformado
nunca viram `red` por suposicao - viram `nao_liquidavel`, com evidencia
do motivo, para revisao manual (`python -m app.settlement review`,
ainda nao implementado).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Sequence

from app.settlement.linhas import Resultado, combinar, dividir_linha, fracao_valida, metade_por_diferenca
from app.settlement.selecao import (
    IntencaoAmbasMarcam,
    IntencaoDNB,
    IntencaoDuplaChance,
    IntencaoHandicap,
    IntencaoTotal,
    Intencao1x2,
    eh_condicao_por_time,
    parse_1x2_ou_variantes,
    parse_ambas_marcam,
    parse_handicap,
    parse_total,
)

# Status de fixture que nunca produzem resultado de jogo real - void
# incondicional, qualquer que seja o mercado (spec, Fase 6a: "Void: ...
# partida cancelada ou adiada").
_STATUS_VOID_INCONDICIONAL = ("adiada", "cancelada")


@dataclass(frozen=True)
class PickParaLiquidar:
    pick_id: str
    mercado: str
    selecao: str
    linha: Decimal | None
    time_casa: str
    time_fora: str


@dataclass(frozen=True)
class FixtureEncerrada:
    fixture_id: str
    status: str
    placar_casa: int | None
    placar_fora: int | None


@dataclass(frozen=True)
class FixtureStatTime:
    # Uma linha por time (casa e fora) - `fixture_stats` e' assim que a
    # ESPN grava (ver migrations/0001_init.sql). Sem `eh_casa`/`time_id`
    # porque nenhum resolver desta entrega distingue por time (so soma
    # os dois) - entra quando "cartoes, condicao por time" for escrito.
    escanteios: int | None
    cartoes_amarelos: int | None
    cartoes_vermelhos: int | None


@dataclass(frozen=True)
class Resolution:
    resultado: Resultado
    evidencia: dict = field(default_factory=dict)


def _sem_placar(fixture: FixtureEncerrada) -> bool:
    return fixture.placar_casa is None or fixture.placar_fora is None


def _resolver_1x2(pick: PickParaLiquidar, fixture: FixtureEncerrada, stats: Sequence[FixtureStatTime]) -> Resolution:
    if _sem_placar(fixture):
        return Resolution("nao_liquidavel", {"motivo": "fixture_sem_placar"})

    intencao = parse_1x2_ou_variantes(pick.selecao, pick.time_casa, pick.time_fora)
    if intencao is None:
        return Resolution("nao_liquidavel", {"motivo": "selecao_nao_reconhecida", "selecao": pick.selecao})

    if fixture.placar_casa > fixture.placar_fora:
        vencedor = "casa"
    elif fixture.placar_casa < fixture.placar_fora:
        vencedor = "fora"
    else:
        vencedor = "empate"

    evidencia_base = {
        "placar_casa": fixture.placar_casa,
        "placar_fora": fixture.placar_fora,
        "vencedor": vencedor,
    }

    if isinstance(intencao, Intencao1x2):
        resultado: Resultado = "green" if intencao.lado == vencedor else "red"
        return Resolution(resultado, {**evidencia_base, "selecao_interpretada": "1x2", "lado": intencao.lado})

    if isinstance(intencao, IntencaoDuplaChance):
        cobre = {"1X": ("casa", "empate"), "X2": ("fora", "empate"), "12": ("casa", "fora")}[intencao.par]
        resultado = "green" if vencedor in cobre else "red"
        return Resolution(resultado, {**evidencia_base, "selecao_interpretada": "dupla_chance", "par": intencao.par})

    if isinstance(intencao, IntencaoDNB):
        if vencedor == "empate":
            resultado = "void"
        else:
            resultado = "green" if intencao.lado == vencedor else "red"
        return Resolution(resultado, {**evidencia_base, "selecao_interpretada": "dnb", "lado": intencao.lado})

    return Resolution("nao_liquidavel", {"motivo": "intencao_1x2_nao_tratada"})


def _resolver_ambas_marcam(
    pick: PickParaLiquidar, fixture: FixtureEncerrada, stats: Sequence[FixtureStatTime]
) -> Resolution:
    if _sem_placar(fixture):
        return Resolution("nao_liquidavel", {"motivo": "fixture_sem_placar"})

    intencao: IntencaoAmbasMarcam | None = parse_ambas_marcam(pick.selecao)
    if intencao is None:
        return Resolution("nao_liquidavel", {"motivo": "selecao_nao_reconhecida", "selecao": pick.selecao})

    ambas_marcaram = fixture.placar_casa > 0 and fixture.placar_fora > 0
    resultado: Resultado = "green" if ambas_marcaram == intencao.sim else "red"
    return Resolution(
        resultado,
        {
            "placar_casa": fixture.placar_casa,
            "placar_fora": fixture.placar_fora,
            "ambas_marcaram": ambas_marcaram,
            "selecao_interpretada": intencao.sim,
        },
    )


def _linha_efetiva(pick: PickParaLiquidar, linha_do_texto: Decimal) -> Decimal:
    # picks.linha e a fonte de verdade quando presente (ex.: entrada
    # manual via console); a extracao da Fase 3 nunca populou essa
    # coluna (ver app/settlement/selecao.py), entao o texto de `selecao`
    # e o caminho comum hoje.
    return pick.linha if pick.linha is not None else linha_do_texto


def _liquidar_linha_quebravel(linha: Decimal, diferenca_por_metade: Callable[[Decimal], Decimal]) -> Resultado | None:
    if not fracao_valida(linha):
        return None
    metades = [metade_por_diferenca(diferenca_por_metade(metade)) for metade in dividir_linha(linha)]
    return combinar(metades)


def _resolver_over_under(
    pick: PickParaLiquidar, fixture: FixtureEncerrada, stats: Sequence[FixtureStatTime]
) -> Resolution:
    if _sem_placar(fixture):
        return Resolution("nao_liquidavel", {"motivo": "fixture_sem_placar"})

    intencao: IntencaoTotal | None = parse_total(pick.selecao)
    if intencao is None:
        return Resolution("nao_liquidavel", {"motivo": "selecao_nao_reconhecida", "selecao": pick.selecao})

    linha = _linha_efetiva(pick, intencao.linha)
    total = Decimal(fixture.placar_casa + fixture.placar_fora)

    if intencao.direcao == "over":
        diferenca_por_metade = lambda metade: total - metade
    else:
        diferenca_por_metade = lambda metade: metade - total

    resultado = _liquidar_linha_quebravel(linha, diferenca_por_metade)
    evidencia = {
        "placar_casa": fixture.placar_casa,
        "placar_fora": fixture.placar_fora,
        "total": str(total),
        "linha": str(linha),
        "direcao": intencao.direcao,
    }
    if resultado is None:
        return Resolution("nao_liquidavel", {**evidencia, "motivo": "linha_malformada"})
    return Resolution(resultado, evidencia)


def _resolver_handicap(
    pick: PickParaLiquidar, fixture: FixtureEncerrada, stats: Sequence[FixtureStatTime]
) -> Resolution:
    if _sem_placar(fixture):
        return Resolution("nao_liquidavel", {"motivo": "fixture_sem_placar"})

    intencao: IntencaoHandicap | None = parse_handicap(pick.selecao, pick.time_casa, pick.time_fora)
    if intencao is None:
        return Resolution("nao_liquidavel", {"motivo": "selecao_nao_reconhecida", "selecao": pick.selecao})

    linha = _linha_efetiva(pick, intencao.linha)
    margem = (
        Decimal(fixture.placar_casa - fixture.placar_fora)
        if intencao.lado == "casa"
        else Decimal(fixture.placar_fora - fixture.placar_casa)
    )

    resultado = _liquidar_linha_quebravel(linha, lambda metade: margem + metade)
    evidencia = {
        "placar_casa": fixture.placar_casa,
        "placar_fora": fixture.placar_fora,
        "lado": intencao.lado,
        "margem": str(margem),
        "linha": str(linha),
    }
    if resultado is None:
        return Resolution("nao_liquidavel", {**evidencia, "motivo": "linha_malformada"})
    return Resolution(resultado, evidencia)


def _soma_stat(stats: Sequence[FixtureStatTime], campo: Callable[[FixtureStatTime], int | None]) -> int | None:
    # Cobertura parcial (um dos dois times sem o stat) nunca vira total
    # parcial silencioso - "depende de cobertura" (spec, Fase 6a) quer
    # dizer que a falta e' esperada e precisa render nao_liquidavel, nao
    # um numero incompleto disfarcado de total real. `!= 2`, nao `< 2`
    # (achado do code-reviewer): mais de duas linhas (ex.: fan-out de
    # join, bug de query que devolveu o mesmo time duas vezes) tambem
    # nunca deve ser somado como se fosse um total valido - `stats` nao
    # carrega identidade de time pra detectar duplicata, entao o
    # tamanho exato e' a unica defesa disponivel aqui.
    if len(stats) != 2:
        return None
    valores = [campo(s) for s in stats]
    if any(v is None for v in valores):
        return None
    return sum(valores)


def _cartoes_do_time(stat: FixtureStatTime) -> int | None:
    # Decisao registrada (sem confirmacao contra doc de casa de aposta
    # real): "cartoes" de liquidacao = amarelo + vermelho somados, mesma
    # convencao que o mercado "Bookings" do OddsPapi parece seguir
    # (Fase 1b). Revisitar se uma conferencia amostral contra
    # OddsPapi/settlements (pendencia da Fase 6a) mostrar divergencia.
    if stat.cartoes_amarelos is None or stat.cartoes_vermelhos is None:
        return None
    return stat.cartoes_amarelos + stat.cartoes_vermelhos


def _resolver_total_via_stats(
    pick: PickParaLiquidar,
    stats: Sequence[FixtureStatTime],
    campo: Callable[[FixtureStatTime], int | None],
    nome_stat: str,
) -> Resolution:
    intencao: IntencaoTotal | None = parse_total(pick.selecao)
    if intencao is None:
        return Resolution("nao_liquidavel", {"motivo": "selecao_nao_reconhecida", "selecao": pick.selecao})

    total = _soma_stat(stats, campo)
    if total is None:
        return Resolution("nao_liquidavel", {"motivo": "stats_incompletos", "stat": nome_stat})

    linha = _linha_efetiva(pick, intencao.linha)
    total_decimal = Decimal(total)

    if intencao.direcao == "over":
        diferenca_por_metade = lambda metade: total_decimal - metade
    else:
        diferenca_por_metade = lambda metade: metade - total_decimal

    resultado = _liquidar_linha_quebravel(linha, diferenca_por_metade)
    evidencia = {
        "stat": nome_stat,
        "total": str(total_decimal),
        "linha": str(linha),
        "direcao": intencao.direcao,
    }
    if resultado is None:
        return Resolution("nao_liquidavel", {**evidencia, "motivo": "linha_malformada"})
    return Resolution(resultado, evidencia)


def _resolver_escanteios(
    pick: PickParaLiquidar, fixture: FixtureEncerrada, stats: Sequence[FixtureStatTime]
) -> Resolution:
    return _resolver_total_via_stats(pick, stats, campo=lambda s: s.escanteios, nome_stat="escanteios")


def _resolver_cartoes(
    pick: PickParaLiquidar, fixture: FixtureEncerrada, stats: Sequence[FixtureStatTime]
) -> Resolution:
    if eh_condicao_por_time(pick.selecao):
        # Mercado distinto de total (ver docstring de
        # app.settlement.selecao.eh_condicao_por_time) - nunca liquidar
        # como se fosse o total da partida.
        return Resolution("nao_liquidavel", {"motivo": "condicao_por_time_nao_suportada", "selecao": pick.selecao})
    return _resolver_total_via_stats(pick, stats, campo=_cartoes_do_time, nome_stat="cartoes")


REGISTRO: dict[str, Callable[[PickParaLiquidar, FixtureEncerrada, Sequence[FixtureStatTime]], Resolution]] = {
    "1x2": _resolver_1x2,
    "ambas_marcam": _resolver_ambas_marcam,
    "over_under": _resolver_over_under,
    "escanteios": _resolver_escanteios,
    "cartoes": _resolver_cartoes,
    "handicap": _resolver_handicap,
}


def liquidar(pick: PickParaLiquidar, fixture: FixtureEncerrada, stats: Sequence[FixtureStatTime] = ()) -> Resolution:
    if fixture.status in _STATUS_VOID_INCONDICIONAL:
        return Resolution("void", {"motivo": "fixture_status", "status": fixture.status})

    # Achado do code-reviewer (Fase 6a): so `collect_results.py` grava
    # placar quando o status resolve pra "encerrada" (Fase 1f), entao
    # hoje isso nunca deveria disparar na pratica - mas essa e uma
    # garantia de OUTRO modulo, nao deste. Checar aqui evita confiar
    # implicitamente num invariante alheio, mesmo padrao de defesa em
    # profundidade ja usado em app.pipeline.avancar_etapas.
    if fixture.status != "encerrada":
        return Resolution("nao_liquidavel", {"motivo": "fixture_nao_encerrada", "status": fixture.status})

    resolver = REGISTRO.get(pick.mercado)
    if resolver is None:
        return Resolution("nao_liquidavel", {"motivo": "mercado_sem_resolver", "mercado": pick.mercado})
    return resolver(pick, fixture, stats)
