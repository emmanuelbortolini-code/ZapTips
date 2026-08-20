"""Parser de `picks.selecao` (texto livre do tipster) para intencao
tipada (Fase 6a) - existe porque `picks.linha` nunca foi populado pela
extracao da Fase 3 (`app/extraction.py::_PALPITE_SCHEMA` nao tem esse
campo) e reprocessar via API nao e viavel hoje (sem credito, e os
raw_picks ja estao marcados `extraido_em`). A informacao so existe como
texto livre em `picks.selecao` - este modulo deriva dela.

Regra de ouro, herdada do resto do projeto (app.matcher desde a Fase 1c,
app.odds_resolution desde a Fase 4): ambiguidade nunca e chutada. Texto
que nao bate com nenhum padrao conhecido devolve None, que o motor de
liquidacao (engine.py) trata como `nao_liquidavel`, nunca como red.

Separador decimal misto (achado real da spec, secao SDA): odds e linhas
usam tanto ponto quanto virgula na mesma fonte ("Cruzeiro -1,5" vs
"Palmeiras -1.5"). Normaliza pra ponto antes de qualquer Decimal(str(...)).
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.odds_resolution import Selecao1x2, fora_de_escopo, normalizar_selecao_1x2

ParDuplaChance = Literal["1X", "X2", "12"]


@dataclass(frozen=True)
class Intencao1x2:
    lado: Selecao1x2


@dataclass(frozen=True)
class IntencaoDuplaChance:
    par: ParDuplaChance


@dataclass(frozen=True)
class IntencaoDNB:
    lado: Literal["casa", "fora"]


@dataclass(frozen=True)
class IntencaoAmbasMarcam:
    sim: bool


@dataclass(frozen=True)
class IntencaoTotal:
    direcao: Literal["over", "under"]
    linha: Decimal


@dataclass(frozen=True)
class IntencaoHandicap:
    lado: Literal["casa", "fora"]
    linha: Decimal


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


def _decimal_pt_br(texto: str) -> Decimal:
    return Decimal(texto.replace(",", "."))


_MARCADORES_DNB = ("ganhar ou empatar", "dnb", "draw no bet", "empate anula")

# Qualquer mencao a isso significa que a selecao NAO e sobre o resultado
# do jogo inteiro (90min+acrescimos) - e escopo diferente (1o/2o tempo)
# ou depende de mais que esta partida (agregado de mata-mata, penaltis).
# Achado real: "Al Hilal vence o 1o tempo" e "Senegal se classifica"
# apareceram nos dados reais dentre 84 selecoes distintas de 1x2 - as
# unicas duas que nao sao resultado direto do jogo. Resolver qualquer
# uma delas contra o placar final da partida inteira estaria liquidando
# um mercado diferente do que foi apostado. Movida pra app.odds_resolution
# em 2026-08-20 (`fora_de_escopo`) - o mesmo modulo ja e importado daqui
# (normalizar_selecao_1x2) e agora tambem precisa da guarda pros
# normalizadores de ambas_marcam/over_under (achado do code-reviewer).
_fora_de_escopo = fora_de_escopo


def parse_1x2_ou_variantes(
    selecao: str, time_casa: str | None, time_fora: str | None
) -> Intencao1x2 | IntencaoDuplaChance | IntencaoDNB | None:
    s = _normalizar(selecao)
    if _fora_de_escopo(s):
        return None

    codigo = s.replace(" ", "").upper()
    if codigo in ("1X", "X1"):
        return IntencaoDuplaChance(par="1X")
    if codigo in ("X2", "2X"):
        return IntencaoDuplaChance(par="X2")
    if codigo in ("12", "21"):
        return IntencaoDuplaChance(par="12")

    # DNB (Draw No Bet) - achado real: a fonte nao usa a sigla, escreve
    # "X para ganhar ou empatar contra Y" (ex.: "Itabaiana para ganhar
    # ou empatar contra Confianca"). "dnb"/"draw no bet"/"empate anula"
    # ficam como reconhecimento defensivo pra fraseado que ainda nao
    # apareceu nos dados reais.
    marcadores_dnb = [m for m in _MARCADORES_DNB if m in s]
    if marcadores_dnb:
        # A frase "X para ganhar ou empatar contra Y" cita os DOIS times -
        # checar o nome contra a string inteira sempre bateria pros dois.
        # O time que decide o lado e' o sujeito, sempre antes do marcador
        # (o adversario, quando existe, vem depois de "contra").
        sujeito = s[: min(s.index(m) for m in marcadores_dnb)]
        casa_bate = bool(time_casa) and _contem_time(sujeito, time_casa)
        fora_bate = bool(time_fora) and _contem_time(sujeito, time_fora)
        if casa_bate and not fora_bate:
            return IntencaoDNB(lado="casa")
        if fora_bate and not casa_bate:
            return IntencaoDNB(lado="fora")
        return None

    lado = normalizar_selecao_1x2(selecao, time_casa, time_fora)
    if lado is not None:
        return Intencao1x2(lado=lado)
    return None


def _contem_time(selecao_normalizada: str, nome_time: str) -> bool:
    from app.matcher import normalize_team_name

    alvo = normalize_team_name(nome_time)
    return bool(alvo) and alvo in normalize_team_name(selecao_normalizada)


def parse_ambas_marcam(selecao: str) -> IntencaoAmbasMarcam | None:
    s = _normalizar(selecao)
    ultimo_token = s.split("-")[-1].strip()
    if ultimo_token in ("sim", "yes"):
        return IntencaoAmbasMarcam(sim=True)
    if ultimo_token in ("nao", "no"):
        return IntencaoAmbasMarcam(sim=False)
    # "BTTS" bare, sem sim/nao explicito - ambiguo, nunca chuta (ex.:
    # nao presumir que "BTTS" sozinho significa "sim").
    return None


_TOTAL_RE = re.compile(
    r"(mais de|acima de|over|menos de|abaixo de|under)\s*([\d.,]+)", re.IGNORECASE
)
_DIRECAO_OVER = {"mais de", "acima de", "over"}
_DIRECAO_UNDER = {"menos de", "abaixo de", "under"}


def parse_total(selecao: str) -> IntencaoTotal | None:
    # Generico pra over/under de gols/escanteios/cartoes - a escolha de
    # QUAL total comparar (gols, escanteios, cartoes) e do resolver, que
    # ja sabe seu proprio mercado (picks.mercado dispatcha pro resolver
    # certo); este parser so extrai direcao + linha do texto.
    s = _normalizar(selecao)
    if _fora_de_escopo(s):
        # Achado do code-reviewer (Fase 6a): sem essa guarda, "Mais de
        # 0.5 gols no 1o tempo" seria liquidado contra o placar do jogo
        # inteiro - silenciosamente errado, mesma classe de risco que
        # parse_1x2_ou_variantes ja evita.
        return None
    m = _TOTAL_RE.search(s)
    if m is None:
        return None
    direcao_texto, numero_texto = m.group(1), m.group(2)
    try:
        linha = _decimal_pt_br(numero_texto)
    except Exception:
        return None
    direcao = "over" if direcao_texto in _DIRECAO_OVER else "under"
    return IntencaoTotal(direcao=direcao, linha=linha)


_NUMERO_FINAL_RE = re.compile(r"([+-]?\d+(?:[.,]\d+)?)\s*(?:\([^)]*\))?\s*$")
_TOKEN_ABREVIACAO_RE = re.compile(r"\b(?:hc|ha)\b\s*$")


def parse_handicap(selecao: str, time_casa: str | None, time_fora: str | None) -> IntencaoHandicap | None:
    s = _normalizar(selecao)
    if _fora_de_escopo(s):
        return None
    m = _NUMERO_FINAL_RE.search(s)
    if m is None:
        return None
    try:
        linha = _decimal_pt_br(m.group(1))
    except Exception:
        return None

    sujeito = s[: m.start()].strip()
    sujeito = _TOKEN_ABREVIACAO_RE.sub("", sujeito).strip()

    if "home win" in sujeito or sujeito == "casa":
        return IntencaoHandicap(lado="casa", linha=linha)
    if "away win" in sujeito or sujeito == "fora":
        return IntencaoHandicap(lado="fora", linha=linha)

    casa_bate = bool(time_casa) and _contem_time(sujeito, time_casa)
    fora_bate = bool(time_fora) and _contem_time(sujeito, time_fora)
    if casa_bate and not fora_bate:
        return IntencaoHandicap(lado="casa", linha=linha)
    if fora_bate and not casa_bate:
        return IntencaoHandicap(lado="fora", linha=linha)
    return None


# "Cartoes, condicao por time" (spec, Fase 6a) e' mercado distinto de
# total de cartoes: a condicao vale para os DOIS times simultaneamente
# (ex.: "Ambas as equipes recebem 2 cartoes ou mais"), nao para a soma.
# Nao existe exemplo real desse texto nos dados ja coletados pelo
# projeto (a unica fonte com mercado por-time confirmado e' o APWin, que
# ainda nao foi construido - ver CLAUDE.md, "Proximos passos" #8) -
# entao so o marcador e' reconhecido aqui, pra nunca deixar esse tipo de
# selecao ser liquidada por engano como se fosse o total (engine.py usa
# isso pra desviar pra `nao_liquidavel` antes de tentar `parse_total`).
# Escrever o parser completo (extrair a linha da condicao) fica para
# quando houver texto real pra validar contra, mesma cautela ja aplicada
# ao resto do projeto.
_MARCADORES_CONDICAO_POR_TIME = ("ambas equipes", "ambas as equipes", "cada equipe", "cada time", "os dois times")


def eh_condicao_por_time(selecao: str) -> bool:
    s = _normalizar(selecao)
    return any(m in s for m in _MARCADORES_CONDICAO_POR_TIME)
