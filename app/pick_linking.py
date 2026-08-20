"""Vincula picks extraidos a fixtures reais.

Pre-requisito da Fase 4 que o documento original nao cobre explicitamente
(ele assume "picks vinculados a fixtures" como dado de entrada da
curadoria) - achado real desta sessao: as datas do backfill da Fase 3
(maio a agosto de 2026, textos historicos de tipsters) quase nao se
sobrepoem com a janela de 7 dias que `collect_fixtures.py` mantem. Esse
modulo e o elo que falta entre as duas.

Resolve `time_casa`/`time_fora` do pick contra `teams` via `app.matcher`
(mesmos aliases semeados na Fase 1d), depois escolhe a fixture certa
entre candidatas com os dois times batendo, dentro de uma janela de
kickoff em torno de `data_referencia` (o pick so tem data solta, sem
hora, e os mesmos dois times podem se enfrentar em datas diferentes -
a janela evita casar o jogo errado do mesmo confronto).

Nunca chuta, mesmo criterio de `app.matcher` desde a Fase 1c:
- Time nao resolvido (sem alias, score baixo, ou ambiguo dentro do
  proprio matcher) -> pick fica como esta (`extraido`), tenta de novo
  num run futuro quando mais times/fixtures existirem. Nao e erro -
  a maioria dos picks do backfill referencia ligas fora do escopo de
  11 competicoes semeado na Fase 1d (times suecos, holandeses etc. do
  Eagle Predict).
- Times resolvidos mas nenhuma fixture candidata na janela -> mesma
  coisa, fica `extraido` (fixture ainda nao foi coletada).
- Times resolvidos e mais de uma fixture candidata na janela (ex.:
  confronto de ida e volta) -> ambiguidade real, `revisao_manual`.
- Times resolvidos e exatamente uma fixture candidata -> `vinculado`.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, Sequence

from app.matcher import TeamAlias, match_team_name

# Mesma tolerancia ja usada na desambiguacao de odds do OddsPapi
# (Fase 1g) - o pick nao tem hora, so data, e BRT/UTC diverge por ate 3h
# nas duas pontas do dia.
JANELA_KICKOFF_HORAS = 36

_DATA_BR_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")

VinculoStatus = Literal["vinculado", "extraido", "revisao_manual"]
MotivoNaoVinculado = Literal["sem_times_no_pick", "time_nao_resolvido", "sem_fixture_na_janela"]


@dataclass(frozen=True)
class PickParaVincular:
    pick_id: str
    time_casa: str | None
    time_fora: str | None
    data_referencia: str | None


@dataclass(frozen=True)
class FixtureCandidata:
    fixture_id: str
    home_team_id: str
    away_team_id: str
    kickoff_utc: datetime


@dataclass(frozen=True)
class ResultadoVinculo:
    pick_id: str
    fixture_id: str | None
    score_matching: float | None
    status: VinculoStatus
    # So preenchido quando status == "extraido" - distingue as tres causas
    # que hoje colapsam no mesmo status (Fase 5a, contador de tentativas
    # de scripts/link_picks.py so avanca pra "sem_fixture_na_janela": e
    # o unico cenario que a especificacao descreve como "orfao" de
    # verdade, os outros dois sao picks de liga fora do escopo semeado,
    # que nunca vao resolver so com o tempo passando).
    motivo: MotivoNaoVinculado | None = None


def parse_data_referencia(texto: str | None) -> date | None:
    """So entende dd/mm/aaaa (unico formato visto no dado real da Fase 3
    - Eagle Predict e SDA sempre citam data explicita no post). Datas
    relativas ("hoje", "amanha") ou formato inesperado voltam None -
    o chamador trata isso como "sem janela pra filtrar", nao como erro."""
    if not texto:
        return None
    m = _DATA_BR_RE.match(texto.strip())
    if not m:
        return None
    dia, mes, ano = (int(x) for x in m.groups())
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def _dentro_da_janela(kickoff: datetime, data_ref: date) -> bool:
    centro = datetime.combine(data_ref, time(12, 0), tzinfo=timezone.utc)
    return abs(kickoff - centro) <= timedelta(hours=JANELA_KICKOFF_HORAS)


def vincular_pick(
    pick: PickParaVincular,
    aliases: Sequence[TeamAlias],
    fixtures_por_par: dict[tuple[str, str], list[FixtureCandidata]],
) -> ResultadoVinculo:
    if not pick.time_casa or not pick.time_fora:
        return ResultadoVinculo(pick.pick_id, None, None, "extraido", "sem_times_no_pick")

    casa_match = match_team_name(pick.time_casa, aliases)
    fora_match = match_team_name(pick.time_fora, aliases)

    if casa_match.team_id is None or fora_match.team_id is None:
        return ResultadoVinculo(pick.pick_id, None, None, "extraido", "time_nao_resolvido")

    candidatas = fixtures_por_par.get((casa_match.team_id, fora_match.team_id), [])

    data_ref = parse_data_referencia(pick.data_referencia)
    if data_ref is not None:
        candidatas = [c for c in candidatas if _dentro_da_janela(c.kickoff_utc, data_ref)]

    if not candidatas:
        return ResultadoVinculo(pick.pick_id, None, None, "extraido", "sem_fixture_na_janela")

    if len(candidatas) > 1:
        return ResultadoVinculo(pick.pick_id, None, None, "revisao_manual")

    score = min(casa_match.score, fora_match.score)
    return ResultadoVinculo(pick.pick_id, candidatas[0].fixture_id, score, "vinculado")
