"""Resolve odd de referencia e odd minima para picks ja vinculados a uma
fixture (Fase 4, "Odd de referencia e odd minima").

Hierarquia implementada (ver CLAUDE.md, Fase 1b, "Hierarquia de origens"):

1. **Fonte** - o proprio tipster citou uma casa licenciada e uma odd
   junto do palpite (`picks.casa_id`/`picks.odd_citada`, ja resolvidos na
   extracao - Fase 3). Mais direto, usa como esta.
2. **OddsPapi** (`odds_referencia`, Fase 1g/4) - cobre `1x2`,
   `ambas_marcam` e `over_under` (gols, tempo cheio), tres casas
   (bet365/betano/superbet). Usa o **minimo** entre as tres: o produto
   promete um piso, nao uma cotacao ("abaixo dela, o assinante nao
   aposta, porque o retorno nao paga o risco" - documento original),
   entao a referencia mais conservadora entre as casas rastreadas e a
   que sustenta essa promessa sem exagerar. `ambas_marcam`/`over_under`
   adicionados em 2026-08-20 (pedido do PM: "nao tem como trazer as odds
   da fonte caso nao tenha da OddsPapi?") - o dado ja vinha na mesma
   resposta de `/odds-by-tournaments` que o projeto so usava parcialmente
   (ver `app.oddspapi.parse_odds_extras_by_tournaments_response`).
3. **ESPN** (`app.espn_odds`, bloco nativo `odds`/`pickcenter` do
   `/summary`) - so mercado `1x2`, mesma restricao de selecao do nivel 2
   (`normalizar_selecao_1x2`). Formato real e' odds americanas
   (moneyline), convertidas pra decimal em `app.espn_odds`. Usa o
   **minimo** entre as casas licenciadas que aparecerem (mesmo raciocinio
   de piso conservador do nivel 2) - na pratica, sonda ao vivo desta
   sessao (2026-08-20, 7 ligas) so encontrou a DraftKings, nao licenciada,
   entao esse nivel raramente resolve algo hoje; existe pro caso raro em
   que uma casa licenciada aparecer.
4. Manual (curadoria no console) - **fora de escopo aqui**, resolvido
   direto por `app.console.acoes.criar_palpite_manual` (Fase 5d).

Nivel 2, mercado `1x2`, so resolve seleçoes de resultado simples
(casa/empate/fora) - "1X"/"X2"/"12" (dupla chance) nao mapeiam pra uma
unica linha de `odds_referencia` (que so guarda resultado unico) e ficam
deliberadamente sem tentativa de resolucao nesse nivel, em vez de
arriscar um mapeamento errado. `handicap`/`escanteios`/`cartoes` ainda
nao tem cobertura no OddsPapi - so o nivel 1 pode resolve-los.
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from app.espn_odds import extrair_odds_licenciadas
from app.matcher import normalize_team_name

OrigemOdd = Literal["fonte", "oddspapi", "espn"]
Selecao1x2 = Literal["casa", "empate", "fora"]

_EMPATE_LITERAIS = {"empate", "draw", "x"}
_CASA_LITERAIS = {"home win", "vitoria da casa", "1"}
_FORA_LITERAIS = {"away win", "vitoria de fora", "2"}

# Movido pra ca (2026-08-20) a partir de app/settlement/selecao.py, que
# ja importa deste modulo (normalizar_selecao_1x2) - definir aqui em vez
# de la evita import circular (odds_resolution -> settlement.selecao ->
# odds_resolution) e deixa a guarda reaproveitavel pelos dois lados.
# Achado do code-reviewer (Fase 6a, selecao.py): sem isso, "Mais de 0.5
# gols no 1o tempo" seria tratado como se fosse do jogo inteiro -
# silenciosamente errado. A mesma guarda faltava aqui quando os
# normalizadores de ambas_marcam/over_under foram adicionados (achado do
# code-reviewer, 2026-08-20) - risco pior aqui do que em settlement,
# porque alimenta odd_referencia/odd_minima mostrada pro assinante real.
ESCOPO_FORA_DO_JOGO_INTEIRO = ("tempo", "classific", "avanc", "agregad", "penalt", "prorrog")


def fora_de_escopo(selecao_normalizada: str) -> bool:
    return any(termo in selecao_normalizada for termo in ESCOPO_FORA_DO_JOGO_INTEIRO)


@dataclass(frozen=True)
class PickParaResolverOdds:
    pick_id: str
    fixture_id: str
    mercado: str
    selecao: str
    time_casa: str | None
    time_fora: str | None
    casa_id: str | None
    odd_citada: float | None


@dataclass(frozen=True)
class OddReferenciaEncontrada:
    valor: float
    origem: OrigemOdd


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


def _contem_time(selecao_normalizada: str, nome_time: str) -> bool:
    alvo = normalize_team_name(nome_time)
    return bool(alvo) and alvo in normalize_team_name(selecao_normalizada)


def normalizar_selecao_1x2(selecao: str, time_casa: str | None, time_fora: str | None) -> Selecao1x2 | None:
    s = _normalizar(selecao)

    if s in _EMPATE_LITERAIS:
        return "empate"
    if s in _CASA_LITERAIS:
        return "casa"
    if s in _FORA_LITERAIS:
        return "fora"

    if "venc" in s or "vitoria" in s:
        # Checa os dois antes de decidir - achado real do code-reviewer:
        # quando um time bate sozinho, e' seguro; quando os DOIS batem
        # (nome de um e' substring do outro, ex. "Gremio" dentro de
        # "Gremio Novorizontino", ou os dois normalizam igual, ex.
        # "Atletico-MG"/"Atletico-GO" -> "atletico"), preferir casa
        # cegamente ja causou o cenario exato que MIN_LEN_FUZZY existe
        # pra evitar em app/matcher.py - aqui precisa da mesma cautela.
        casa_bate = bool(time_casa) and _contem_time(s, time_casa)
        fora_bate = bool(time_fora) and _contem_time(s, time_fora)
        if casa_bate and not fora_bate:
            return "casa"
        if fora_bate and not casa_bate:
            return "fora"

    return None


_NAO_RE = re.compile(r"\bnao\b")
_SIM_RE = re.compile(r"\b(sim|yes|btts)\b")
# "BTTS No"/"BTTS: No" (Eagle Predict, em ingles) - achado do
# code-reviewer: bare "no" fica de fora do reconhecimento geral (ver
# docstring abaixo), mas isso deixava "BTTS No" cair no _SIM_RE (que
# bate em "btts" sozinho) e responder "sim" - o oposto do que o texto
# diz. Restrito a quando "no" aparece perto de "btts" especificamente,
# nao reabre o falso positivo da preposicao portuguesa "no 1o tempo".
_BTTS_NAO_RE = re.compile(r"\bbtts\b.*\bno\b|\bno\b.*\bbtts\b")


def normalizar_selecao_ambas_marcam(selecao: str) -> Literal["sim", "nao"] | None:
    """"Ambas as equipes marcam: sim/nao", "BTTS", "Yes"/"No"/"BTTS No"
    (Eagle Predict, em ingles). Checa "nao" ANTES de "sim" de proposito -
    nunca o contrario, porque testar "sim" primeiro arriscaria bater com
    uma substring de outra palavra antes do "nao" explicito ser visto.
    Bare "no" em ingles fica de fora do reconhecimento geral (so conta
    perto de "btts", ver _BTTS_NAO_RE): "Benfica marca no 1o e 2o tempo"
    (achado real, Fase 3) tem "no" como preposicao em portugues, nao
    como resposta - incluir isso chutaria errado num mercado que nem e'
    ambas_marcam de verdade (aquele exemplo e' "outro").

    `fora_de_escopo` primeiro (achado do code-reviewer, 2026-08-20,
    mesma classe de bug ja corrigida em app.settlement.selecao): sem
    isso, "Ambas marcam no 1o tempo" resolveria contra o mercado de jogo
    inteiro - odd errada mostrada pro assinante real."""
    s = _normalizar(selecao)
    if fora_de_escopo(s):
        return None
    if _NAO_RE.search(s) or _BTTS_NAO_RE.search(s):
        return "nao"
    if _SIM_RE.search(s):
        return "sim"
    return None


_OVER_UNDER_RE = re.compile(r"\b(mais|menos|over|under)\b\s*(?:de\s*)?(\d+(?:[.,]\d+)?)")


def normalizar_selecao_over_under(selecao: str) -> tuple[Literal["over", "under"], float] | None:
    """"Menos de 2.5 gols", "Mais 3.5 gols" (sem "de"), "Over 1.5",
    "Under 3.5" - devolve (direcao, linha) ou None se o texto nao tiver
    um numero de linha reconhecivel (nunca chuta uma linha). `fora_de_
    escopo` primeiro pelo mesmo motivo de normalizar_selecao_ambas_
    marcam acima - "Mais de 0.5 gols no 1o tempo" nunca pode resolver
    contra o mercado de jogo inteiro."""
    s = _normalizar(selecao)
    if fora_de_escopo(s):
        return None
    m = _OVER_UNDER_RE.search(s)
    if not m:
        return None
    direcao_raw, linha_raw = m.groups()
    direcao: Literal["over", "under"] = "over" if direcao_raw in ("mais", "over") else "under"
    try:
        linha = float(linha_raw.replace(",", "."))
    except ValueError:
        return None
    return direcao, linha


def resolver_odd_referencia(
    pick: PickParaResolverOdds,
    casas_licenciadas: set[str],
    odds_por_fixture_mercado_selecao: dict[tuple[str, str, str, float | None], list[float]],
) -> OddReferenciaEncontrada | None:
    if pick.casa_id is not None and pick.casa_id in casas_licenciadas and pick.odd_citada is not None:
        return OddReferenciaEncontrada(valor=pick.odd_citada, origem="fonte")

    if pick.mercado == "1x2":
        selecao_normalizada = normalizar_selecao_1x2(pick.selecao, pick.time_casa, pick.time_fora)
        if selecao_normalizada is not None:
            valores = odds_por_fixture_mercado_selecao.get((pick.fixture_id, "1x2", selecao_normalizada, None), [])
            if valores:
                return OddReferenciaEncontrada(valor=min(valores), origem="oddspapi")

    elif pick.mercado == "ambas_marcam":
        selecao_normalizada = normalizar_selecao_ambas_marcam(pick.selecao)
        if selecao_normalizada is not None:
            valores = odds_por_fixture_mercado_selecao.get(
                (pick.fixture_id, "ambas_marcam", selecao_normalizada, None), []
            )
            if valores:
                return OddReferenciaEncontrada(valor=min(valores), origem="oddspapi")

    elif pick.mercado == "over_under":
        resultado_over_under = normalizar_selecao_over_under(pick.selecao)
        if resultado_over_under is not None:
            direcao, linha = resultado_over_under
            valores = odds_por_fixture_mercado_selecao.get((pick.fixture_id, "over_under", direcao, linha), [])
            if valores:
                return OddReferenciaEncontrada(valor=min(valores), origem="oddspapi")

    return None


def resolver_odd_espn(
    pick: PickParaResolverOdds,
    payload_summary: dict,
    casas_licenciadas_normalizadas: set[str],
) -> OddReferenciaEncontrada | None:
    """Nivel 3 - ver docstring do modulo e app.espn_odds. So tenta
    resolver quando o mercado e' `1x2` e a selecao normaliza pra
    casa/fora/empate (mesma restricao do nivel 2) - chamar isto sem essa
    checagem previa desperdicaria uma chamada de rede (feita pelo
    chamador, `scripts/resolve_odds.py`) pra um pick que nunca poderia
    usar o resultado mesmo com o payload em maos."""
    if pick.mercado != "1x2":
        return None

    selecao_normalizada = normalizar_selecao_1x2(pick.selecao, pick.time_casa, pick.time_fora)
    if selecao_normalizada is None:
        return None

    encontradas = extrair_odds_licenciadas(payload_summary, selecao_normalizada, casas_licenciadas_normalizadas)
    if not encontradas:
        return None

    return OddReferenciaEncontrada(valor=min(e.valor for e in encontradas), origem="espn")


def calcular_odd_minima(odd_referencia: float, margem_pct: float, odd_minima_absoluta: float) -> float:
    # Decimal, nao float/math.floor: e' uma promessa de produto ("piso
    # arredondado pra cima quebra a promessa", documento original), nao
    # so um detalhe interno - imprecisao binaria de float podia empurrar
    # um valor tipo x.xx5 pro lado errado do arredondamento. Decimal(str(x))
    # preserva o valor decimal como digitado/recebido, sem herdar o ruido
    # binario do float de origem.
    referencia = Decimal(str(odd_referencia))
    margem = Decimal(str(margem_pct))
    piso = Decimal(str(odd_minima_absoluta))
    bruta = max(referencia * (Decimal("1") - margem), piso)
    return float(bruta.quantize(Decimal("0.01"), rounding=ROUND_DOWN))
