"""Vincula picks extraidos a fixtures reais (Fase 4, pre-requisito nao
coberto explicitamente pelo documento original - ver app/pick_linking.py
para a explicacao completa do porque e do design).

So processa picks com status='extraido' (picks ja 'vinculado' ou em
'revisao_manual' nao sao reprocessados). Idempotente: rodar de novo so
tenta de novo o que ainda ficou 'extraido' - nada e desfeito.

Filtra `team_aliases` aos times que de fato tem fixture agendada agora,
mesmo principio ja usado em `collect_odds.py` (Fase 1g) pra eliminar
ambiguidade falsa entre categorias/competicoes fora do escopo do pick.

Uso:
    uv run python -m scripts.link_picks
"""

import sys

import psycopg
import structlog

from app.db import get_connection
from app.matcher import TeamAlias
from app.pick_linking import FixtureCandidata, PickParaVincular, vincular_pick
from app.picks_orfaos import TIPO_SEM_FIXTURE, deve_escalar_para_revisao, limpar_pick_orfao, upsert_pick_orfao
from app.pipeline import ResultadoEtapa

log = structlog.get_logger()

_MOTIVO_SEM_FIXTURE = "pick sem fixture na janela de kickoff ainda"


def buscar_picks_extraidos(cur: psycopg.Cursor) -> list[PickParaVincular]:
    cur.execute("select id, time_casa, time_fora, data_referencia from picks where status = 'extraido'")
    return [
        PickParaVincular(pick_id=str(row[0]), time_casa=row[1], time_fora=row[2], data_referencia=row[3])
        for row in cur.fetchall()
    ]


def carregar_fixtures_por_par(cur: psycopg.Cursor) -> dict[tuple[str, str], list[FixtureCandidata]]:
    cur.execute("select id, home_team_id, away_team_id, kickoff_utc from fixtures")
    fixtures_por_par: dict[tuple[str, str], list[FixtureCandidata]] = {}
    for fixture_id, home_id, away_id, kickoff in cur.fetchall():
        if home_id is None or away_id is None:
            continue
        chave = (str(home_id), str(away_id))
        fixtures_por_par.setdefault(chave, []).append(
            FixtureCandidata(fixture_id=str(fixture_id), home_team_id=str(home_id), away_team_id=str(away_id), kickoff_utc=kickoff)
        )
    return fixtures_por_par


def carregar_aliases_relevantes(cur: psycopg.Cursor, times_relevantes: set[str]) -> list[TeamAlias]:
    cur.execute("select team_id, alias_normalizado from team_aliases")
    return [
        TeamAlias(team_id=str(team_id), alias_normalizado=alias)
        for team_id, alias in cur.fetchall()
        if str(team_id) in times_relevantes
    ]


def aplicar_vinculo(cur: psycopg.Cursor, resultado, contar_tentativa: bool) -> None:
    if resultado.status == "vinculado":
        cur.execute(
            "update picks set fixture_id = %s, score_matching = %s, status = 'vinculado' where id = %s::uuid",
            (resultado.fixture_id, resultado.score_matching, resultado.pick_id),
        )
        limpar_pick_orfao(cur, resultado.pick_id, TIPO_SEM_FIXTURE)
        return

    if resultado.status == "revisao_manual":
        cur.execute("update picks set status = 'revisao_manual' where id = %s::uuid", (resultado.pick_id,))
        return

    # status == "extraido": time nao resolvido ou sem times no pick nunca
    # contam tentativa (D1 - liga fora do escopo semeado nao resolve so
    # com o tempo). So sem_fixture_na_janela e o cenario real de "orfao
    # aguardando partida" (especificacao Fase 5, linha 1021).
    if resultado.motivo != "sem_fixture_na_janela" or not contar_tentativa:
        return

    tentativas = upsert_pick_orfao(cur, resultado.pick_id, _MOTIVO_SEM_FIXTURE, tipo=TIPO_SEM_FIXTURE)
    if deve_escalar_para_revisao(tentativas):
        cur.execute("update picks set status = 'revisao_manual' where id = %s::uuid", (resultado.pick_id,))


def executar(contar_tentativa: bool = True) -> ResultadoEtapa:
    # contar_tentativa=True por padrao pra uso standalone (`uv run python
    # -m scripts.link_picks`) - uma execucao manual e deliberada, entao
    # conta como tentativa. O orquestrador (Fase 5a) chama com o valor
    # real (fixtures trouxe partida nova nesta execucao ou nao - D2).
    with get_connection() as conn:
        with conn.cursor() as cur:
            pendentes = buscar_picks_extraidos(cur)
            fixtures_por_par = carregar_fixtures_por_par(cur)
            times_relevantes = {team_id for par in fixtures_por_par for team_id in par}
            aliases = carregar_aliases_relevantes(cur, times_relevantes)

    resultados = [vincular_pick(pick, aliases, fixtures_por_par) for pick in pendentes]
    por_status = {"vinculado": 0, "revisao_manual": 0, "extraido": 0}
    for resultado in resultados:
        por_status[resultado.status] += 1

    with get_connection() as conn:
        with conn.cursor() as cur:
            for resultado in resultados:
                aplicar_vinculo(cur, resultado, contar_tentativa)
        conn.commit()

    detalhe = {
        "pendentes": len(pendentes),
        "pares_com_fixture": len(fixtures_por_par),
        "vinculado": por_status["vinculado"],
        "revisao_manual": por_status["revisao_manual"],
        "segue_extraido": por_status["extraido"],
    }
    return ResultadoEtapa(status="ok", itens_ok=por_status["vinculado"], itens_erro=por_status["revisao_manual"], detalhe=detalhe)


def main(contar_tentativa: bool = True) -> int:
    resultado = executar(contar_tentativa)
    print(f"{resultado.detalhe['pendentes']} pick(s) com status 'extraido', {resultado.detalhe['pares_com_fixture']} par(es) de times com fixture agendada.")
    print(
        f"vinculado: {resultado.detalhe['vinculado']} | revisao_manual: {resultado.detalhe['revisao_manual']} "
        f"| segue extraido: {resultado.detalhe['segue_extraido']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
