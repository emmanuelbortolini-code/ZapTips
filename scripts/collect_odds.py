"""Adapter do OddsPapi (Fase 1g): captura odd de referencia independente
(nivel 2 da hierarquia, ver CLAUDE.md "Fase 1b") para o mercado 1x2, nas
ligas com tournamentId confirmado em `league_map`.

Roda 1x/dia: uma chamada a /odds-by-tournaments por casa (bet365, betano,
superbet - decisao registrada no CLAUDE.md) mais 1 chamada a /participants
(catalogo de nomes, ver abaixo), cobrindo todas as partidas das ligas
configuradas de uma vez. ~120 requisicoes/mes, dentro da cota de 250.

Casamento de fixture: por nome de time, nao por horario de kickoff.
Tentativa inicial era casar so por (liga, kickoff_utc exato), já que o
OddsPapi so devolve participant1Id/participant2Id numericos (sem nome) em
/odds-by-tournaments. Dado real derrubou essa premissa: ~60% das partidas
do Brasileirao colidem em horario (rodadas usam sempre os mesmos 3-4
horarios padrao, nao so a rodada final). `/participants` resolve o nome a
partir do id (catalogo grande mas estatico, ~19500 times de todos os
campeonatos), e o nome resolvido passa pelo `app.matcher` ja existente
(mesmo threshold fuzzy, mesma politica de nunca chutar ambiguidade)
contra `team_aliases`, ja semeada da ESPN na Fase 1d. `participant1Id` e
sempre o mandante - confirmado com o exemplo real Palmeiras x Fluminense.

Uso:
    uv run python -m scripts.collect_odds
"""

import sys
import time
from datetime import date

import httpx
import psycopg
import structlog

from app.config import get_settings
from app.db import get_connection
from app.matcher import TeamAlias, match_team_name, normalize_team_name
from app.oddspapi import (
    COOLDOWN_SECONDS,
    OddsPapiFixtureOdds,
    fetch_odds_by_tournaments,
    fetch_participants,
    parse_odds_by_tournaments_response,
)
from app.pipeline import ResultadoEtapa

log = structlog.get_logger()

BOOKMAKERS = (("bet365", "Bet365"), ("betano", "Betano"), ("superbet", "Superbet"))
QUOTA_LIMITE_MENSAL = 250
QUOTA_ALERTA_PCT = 0.8


def _erro_sem_segredo(exc: Exception) -> str:
    # httpx.HTTPStatusError.__str__ inclui a URL completa da resposta, com
    # todos os query params - inclusive `apiKey`. Nunca logar str(exc) de
    # uma chamada autenticada por query param; loga so o que ajuda a
    # diagnosticar sem vazar credencial.
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


def upsert_casa(cur: psycopg.Cursor, nome: str, slug_oddspapi: str) -> str:
    cur.execute(
        """
        insert into casas (nome, slug_oddspapi, licenciada_br, ativa)
        values (%s, %s, true, true)
        on conflict (slug_oddspapi) do update set nome = excluded.nome
        returning id
        """,
        (nome, slug_oddspapi),
    )
    return cur.fetchone()[0]


def upsert_odds_referencia(
    cur: psycopg.Cursor,
    fixture_id: str,
    casa_id: str,
    mercado: str,
    selecao: str,
    linha: float | None,
    valor: float,
) -> None:
    cur.execute(
        """
        insert into odds_referencia (fixture_id, casa_id, mercado, selecao, linha, valor, origem)
        values (%s, %s, %s, %s, %s, %s, 'oddspapi')
        on conflict (fixture_id, casa_id, mercado, selecao, coalesce(linha, -1)) do update set
            valor = excluded.valor,
            capturada_em = now()
        """,
        (fixture_id, casa_id, mercado, selecao, linha, valor),
    )


def registrar_chamada_api(cur: psycopg.Cursor, provedor: str, limite: int) -> int:
    mes_referencia = date.today().strftime("%Y-%m")
    cur.execute(
        """
        insert into api_quota (provedor, mes_referencia, chamadas, limite)
        values (%s, %s, 1, %s)
        on conflict (provedor, mes_referencia) do update set
            chamadas = api_quota.chamadas + 1,
            limite = excluded.limite,
            atualizado_em = now()
        returning chamadas
        """,
        (provedor, mes_referencia, limite),
    )
    chamadas = cur.fetchone()[0]
    if limite and chamadas / limite >= QUOTA_ALERTA_PCT:
        log.warning("quota_oddspapi_proxima_do_limite", chamadas=chamadas, limite=limite)
    return chamadas


def carregar_fixtures_por_times(
    cur: psycopg.Cursor, ligas: list[str]
) -> dict[tuple[str, str, str], str | None]:
    cur.execute(
        "select liga, home_team_id, away_team_id, id from fixtures "
        "where liga = any(%s) and home_team_id is not null and away_team_id is not null",
        (ligas,),
    )

    candidatos: dict[tuple[str, str, str], list[str]] = {}
    for liga, home_team_id, away_team_id, fixture_id in cur.fetchall():
        chave = (liga, str(home_team_id), str(away_team_id))
        candidatos.setdefault(chave, []).append(str(fixture_id))

    resolvidos: dict[tuple[str, str, str], str | None] = {}
    for chave, ids in candidatos.items():
        if len(ids) > 1:
            log.warning("times_ambiguo", liga=chave[0], fixture_ids=ids)
            resolvidos[chave] = None
        else:
            resolvidos[chave] = ids[0]
    return resolvidos


def carregar_team_aliases(cur: psycopg.Cursor) -> list[TeamAlias]:
    cur.execute("select team_id, alias_normalizado from team_aliases")
    return [TeamAlias(team_id=str(team_id), alias_normalizado=alias) for team_id, alias in cur.fetchall()]


def filtrar_aliases_relevantes(
    aliases: list[TeamAlias], fixtures_por_times: dict[tuple[str, str, str], str | None]
) -> list[TeamAlias]:
    # team_aliases foi semeada da ESPN cobrindo 11 competicoes (Fase 1d),
    # incluindo sub-20, reservas e copas regionais - times diferentes que
    # as vezes normalizam pro mesmo alias que o time principal (ex.: um
    # "Atletico Mineiro" de categoria de base). Isso gera ambiguidade
    # falsa na hora de casar odd do OddsPapi, que so precisa considerar
    # os times que realmente tem fixture na janela atual (bra.1/bra.2).
    times_relevantes = {team_id for _, home, away in fixtures_por_times for team_id in (home, away)}
    return [alias for alias in aliases if alias.team_id in times_relevantes]


def validar_participantes(resultado: object) -> dict[str, str] | None:
    return resultado if isinstance(resultado, dict) else None


def resolver_participante(participant_id: str, participantes: dict[str, str], aliases: list[TeamAlias]) -> str | None:
    nome = participantes.get(participant_id)
    if not nome:
        log.warning("participante_sem_nome", participant_id=participant_id)
        return None

    resultado = match_team_name(nome, aliases)
    if resultado.status == "revisao_manual":
        log.warning(
            "participante_sem_match_confiavel",
            participant_id=participant_id,
            nome=nome,
            nome_normalizado=normalize_team_name(nome),
            score=resultado.score,
        )
        return None
    return resultado.team_id


def processar_odds(
    cur: psycopg.Cursor,
    odds: list[OddsPapiFixtureOdds],
    liga_by_tournament_id: dict[str, str],
    fixtures_por_times: dict[tuple[str, str, str], str | None],
    participantes: dict[str, str],
    aliases: list[TeamAlias],
    casa_id: str,
) -> tuple[int, int]:
    gravadas = 0
    nao_casadas = 0
    for odd in odds:
        liga = liga_by_tournament_id.get(str(odd.tournament_id))
        home_team_id = resolver_participante(odd.participant1_id, participantes, aliases) if liga else None
        away_team_id = resolver_participante(odd.participant2_id, participantes, aliases) if liga else None

        fixture_id = None
        if liga and home_team_id and away_team_id:
            fixture_id = fixtures_por_times.get((liga, home_team_id, away_team_id))
            if fixture_id is None and fixtures_por_times.get((liga, away_team_id, home_team_id)) is not None:
                # participant1Id="mandante" e uma suposicao validada com 1
                # exemplo real, nao um campo explicito da API. Se o
                # inverso bate, o pressuposto quebrou pra este torneio ou
                # casa - sinaliza alto e alto em vez de gravar a odd
                # trocada (casa/fora invertidos seria pior que nao gravar).
                log.warning(
                    "participant1_pode_nao_ser_mandante",
                    liga=liga,
                    oddspapi_fixture_id=odd.oddspapi_fixture_id,
                    bookmaker=odd.bookmaker,
                )

        if fixture_id is None:
            nao_casadas += len(odd.precos)
            continue

        for selecao, valor in odd.precos.items():
            upsert_odds_referencia(cur, fixture_id, casa_id, "1x2", selecao, None, valor)
            gravadas += 1

    return gravadas, nao_casadas


def executar() -> ResultadoEtapa:
    settings = get_settings()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select espn_league_code, oddspapi_tournament_id from league_map "
                "where ativa and oddspapi_tournament_id is not null"
            )
            mapeamento = cur.fetchall()
            if not mapeamento:
                return ResultadoEtapa(status="degradado", itens_erro=1, detalhe={"motivo": "league_map_sem_torneios"})

            ligas = [liga for liga, _ in mapeamento]
            liga_by_tournament_id = {tid: liga for liga, tid in mapeamento}
            tournament_ids = [tid for _, tid in mapeamento]

            fixtures_por_times = carregar_fixtures_por_times(cur, ligas)
            aliases = filtrar_aliases_relevantes(carregar_team_aliases(cur), fixtures_por_times)
            casa_id_by_slug = {slug: upsert_casa(cur, nome, slug) for slug, nome in BOOKMAKERS}
        conn.commit()

    # Toda tentativa que chega a sair pela rede conta pra cota, mesmo
    # quando a resposta e' erro (4xx/5xx ainda consomem cota do lado do
    # provedor). Por isso o registro em api_quota cobre bookmakers_tentados
    # inteiro, nao so os que tiveram sucesso - e tambem cobre /participants.
    odds_por_casa: dict[str, list[OddsPapiFixtureOdds]] = {}
    bookmakers_tentados: list[str] = []
    bookmakers_falhos: list[str] = []
    participantes: dict[str, str] = {}
    participants_ok = False
    with httpx.Client() as client:
        try:
            resultado_participants = fetch_participants(client, settings.oddspapi_base_url, settings.oddspapi_api_key)
        except (httpx.HTTPError, ValueError) as exc:
            # ValueError cobre json.JSONDecodeError: corpo 200 mas nao-JSON
            # nao e HTTPError nenhum. API sem contrato de estabilidade -
            # ja teve parametro obrigatorio nao documentado, 403 em slug
            # que parecia valido, etc.
            log.warning("falha_ao_buscar_participants", erro=_erro_sem_segredo(exc))
        else:
            participantes_validados = validar_participantes(resultado_participants)
            if participantes_validados is not None:
                participantes = participantes_validados
                participants_ok = True
            else:
                log.warning("participants_formato_inesperado", tipo=type(resultado_participants).__name__)
        time.sleep(COOLDOWN_SECONDS)

        for slug, _ in BOOKMAKERS:
            bookmakers_tentados.append(slug)
            try:
                payload = fetch_odds_by_tournaments(
                    client, settings.oddspapi_base_url, settings.oddspapi_api_key, slug, tournament_ids
                )
            except httpx.HTTPError as exc:
                log.warning("falha_ao_buscar_odds", bookmaker=slug, erro=_erro_sem_segredo(exc))
                bookmakers_falhos.append(slug)
                time.sleep(COOLDOWN_SECONDS)
                continue

            odds, ignoradas = parse_odds_by_tournaments_response(payload, slug)
            if ignoradas:
                log.warning("fixtures_ignoradas_no_parsing", bookmaker=slug, quantidade=ignoradas)
            odds_por_casa[slug] = odds
            time.sleep(COOLDOWN_SECONDS)

    gravadas_total = 0
    nao_casadas_total = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            registrar_chamada_api(cur, "oddspapi", QUOTA_LIMITE_MENSAL)  # /participants
            for slug in bookmakers_tentados:
                odds = odds_por_casa.get(slug, [])
                if participants_ok:
                    gravadas, nao_casadas = processar_odds(
                        cur, odds, liga_by_tournament_id, fixtures_por_times, participantes, aliases,
                        casa_id_by_slug[slug],
                    )
                    gravadas_total += gravadas
                    nao_casadas_total += nao_casadas
                registrar_chamada_api(cur, "oddspapi", QUOTA_LIMITE_MENSAL)
        conn.commit()

    detalhe = {
        "ligas_configuradas": len(mapeamento),
        "confrontos_conhecidos": len(fixtures_por_times),
        "participants_ok": participants_ok,
        "bookmakers_tentados": bookmakers_tentados,
        "bookmakers_falhos": bookmakers_falhos,
        "gravadas": gravadas_total,
        "nao_casadas": nao_casadas_total,
    }
    status = "ok" if participants_ok and not bookmakers_falhos else "degradado"
    itens_erro = len(bookmakers_falhos) + (0 if participants_ok else 1)
    return ResultadoEtapa(status=status, itens_ok=gravadas_total, itens_erro=itens_erro, detalhe=detalhe)


def main() -> int:
    settings = get_settings()
    if not settings.database_url or not settings.oddspapi_api_key:
        print("DATABASE_URL ou ODDSPAPI_API_KEY vazia, abortando.")
        return 1

    resultado = executar()
    if resultado.detalhe.get("motivo") == "league_map_sem_torneios":
        print("league_map sem torneios configurados, abortando.")
        return 1

    print(
        f"{resultado.detalhe['ligas_configuradas']} liga(s) configurada(s), "
        f"{resultado.detalhe['confrontos_conhecidos']} confronto(s) conhecido(s)."
    )
    print(f"Odds gravadas: {resultado.detalhe['gravadas']} | nao casadas com fixture: {resultado.detalhe['nao_casadas']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
