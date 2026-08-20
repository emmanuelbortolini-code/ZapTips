"""Matcher de times: liga o nome que o tipster escreve ao time canonico.

A ESPN chama de "Atletico Mineiro", o tipster escreve "Galo". Este modulo
resolve a parte de normalizacao/match de nome; a desambiguacao por janela
de kickoff (quando dois times diferentes cadastram o mesmo alias
normalizado, ex.: America-MG e America-RN) depende do coletor de fixtures
da Fase 1, ainda nao escrito - por enquanto qualquer ambiguidade cai em
revisao_manual, nunca chuta.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal, Sequence

from rapidfuzz import fuzz

THRESHOLD_FUZZY = 85.0

# Abaixo desse tamanho, fuzzy matching nao e confiavel: strings curtas
# (abreviacoes de 3-4 letras, ex.: "GAL" do Galatasaray) tem alta chance de
# coincidencia acidental de caracteres com um nome curto qualquer, mesmo
# sem nenhuma relacao semantica (achado real: "Galo", apelido do
# Atletico-MG que a ESPN nao cadastra, bateu fuzzy contra "GAL" com score
# 85.71). Abaixo do minimo, so aceita match exato.
MIN_LEN_FUZZY = 5

_SUFIXO_ESTADO_RE = re.compile(r"[-/]\s*[a-z]{2}\s*$")
_TOKEN_CLUBE_RE = re.compile(r"\b(?:fc|ec|sc|cf|ac)\b")
_NAO_ALFANUMERICO_RE = re.compile(r"[^a-z0-9\s]")
_ESPACOS_RE = re.compile(r"\s+")

MatchStatus = Literal["exato", "fuzzy", "revisao_manual"]


@dataclass(frozen=True)
class TeamAlias:
    team_id: str
    alias_normalizado: str


@dataclass(frozen=True)
class MatchResult:
    team_id: str | None
    alias_correspondente: str | None
    score: float
    status: MatchStatus


def normalize_team_name(nome: str) -> str:
    # Token de clube removido antes do sufixo de estado: em nomes como
    # "Botafogo-RJ FC", o "FC" fica depois do "-RJ" e, se o sufixo de
    # estado rodasse primeiro (ancorado no fim da string), o "FC" o
    # impediria de casar. Removendo o token primeiro, o codigo de estado
    # sempre acaba no fim de verdade quando a segunda regex roda.
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    minusculo = sem_acento.lower()
    sem_token_clube = _TOKEN_CLUBE_RE.sub("", minusculo)
    sem_sufixo_estado = _SUFIXO_ESTADO_RE.sub("", sem_token_clube)
    sem_pontuacao = _NAO_ALFANUMERICO_RE.sub(" ", sem_sufixo_estado)
    return _ESPACOS_RE.sub(" ", sem_pontuacao).strip()


def _pontuar(nome_normalizado: str, alias: TeamAlias) -> tuple[TeamAlias, bool, float]:
    exato = alias.alias_normalizado == nome_normalizado
    if exato:
        return alias, True, 100.0

    tamanho_confiavel = (
        len(nome_normalizado) >= MIN_LEN_FUZZY and len(alias.alias_normalizado) >= MIN_LEN_FUZZY
    )
    if not tamanho_confiavel:
        return alias, False, 0.0

    return alias, False, fuzz.token_set_ratio(nome_normalizado, alias.alias_normalizado)


def match_team_name(nome: str, aliases: Sequence[TeamAlias]) -> MatchResult:
    nome_normalizado = normalize_team_name(nome)

    if not aliases:
        return MatchResult(team_id=None, alias_correspondente=None, score=0.0, status="revisao_manual")

    pontuados = [_pontuar(nome_normalizado, alias) for alias in aliases]
    melhor_score = max(score for _, _, score in pontuados)
    melhores = [(alias, exato) for alias, exato, score in pontuados if score == melhor_score]
    times_distintos = {alias.team_id for alias, _ in melhores}

    if melhor_score < THRESHOLD_FUZZY or len(times_distintos) > 1:
        return MatchResult(team_id=None, alias_correspondente=None, score=melhor_score, status="revisao_manual")

    # Empate entre aliases do mesmo time (nao ambiguo, ja passou o check
    # acima): prefere o alias exato, nao o primeiro na ordem em que o
    # chamador passou a lista - a ordem de uma query no banco nao e garantida.
    melhores.sort(key=lambda par: not par[1])
    vencedor, vencedor_exato = melhores[0]
    status: MatchStatus = "exato" if vencedor_exato else "fuzzy"
    return MatchResult(
        team_id=vencedor.team_id,
        alias_correspondente=vencedor.alias_normalizado,
        score=melhor_score,
        status=status,
    )
