"""Resolve odd de referencia/odd minima pra picks vinculados a uma
fixture (Fase 4, ver app/odds_resolution.py para a hierarquia).

Processa picks com status in ('vinculado', 'sem_odd') - reprocessa
'sem_odd' tambem porque `odds_referencia` (OddsPapi) e recarregada todo
dia por `collect_odds.py` e pode resolver amanha o que nao resolveu hoje.
'descartado' e 'revisao_manual' nao sao retocados aqui.

Nivel 3 (ESPN, `app.espn_odds`/`app.odds_resolution.resolver_odd_espn`)
so entra em jogo pra picks que os niveis 1/2 (dado ja em maos, sem rede)
nao resolveram - por isso o script tem tres fases, nao duas: leitura
(sem rede), rede (so pras fixtures que realmente precisam, 1 req/s,
mesmo padrao de scripts/collect_results.py) e escrita (sem rede, sem
transacao aberta durante o loop rate-limited).

Uso:
    uv run python -m scripts.resolve_odds
"""

import sys
import time

import httpx
import psycopg
import structlog

from app.config import get_settings
from app.db import get_connection
from app.espn_client import RATE_LIMIT_SECONDS
from app.espn_odds import normalizar_nome_casa
from app.espn_summary import fetch_summary
from app.odds_resolution import (
    OddReferenciaEncontrada,
    PickParaResolverOdds,
    calcular_odd_minima,
    normalizar_selecao_1x2,
    resolver_odd_espn,
    resolver_odd_referencia,
)
from app.picks_orfaos import upsert_pick_orfao
from app.pipeline import ResultadoEtapa

log = structlog.get_logger()


def buscar_picks_vinculados(cur: psycopg.Cursor) -> list[PickParaResolverOdds]:
    # odd_referencia_origem <> 'manual' - achado real (rodando este
    # script de novo, dias depois de um palpite manual do console ja
    # aprovado/enviado/liquidado): sem essa exclusao, todo pick com
    # status='vinculado' e reprocessado aqui, inclusive um que teve sua
    # odd digitada manualmente na curadoria (criar_palpite_manual sempre
    # grava status='vinculado' + odd_referencia_origem='manual') - o
    # nivel 4 da hierarquia (manual) e explicitamente "fora de escopo"
    # deste script (ver app/odds_resolution.py), mas nada impedia o
    # nivel 1/2 automatico de sobrescrever silenciosamente o valor que o
    # operador decidiu. O dado ja enviado/liquidado usa a copia
    # congelada em slate_picks, entao isso nao corrompe historico
    # financeiro - mas corrompe o registro vivo em `picks`, que e o que
    # a Curadoria mostraria numa correcao futura desse slate.
    cur.execute(
        """
        select id, fixture_id, mercado, selecao, time_casa, time_fora, casa_id, odd_citada
        from picks
        where status in ('vinculado', 'sem_odd')
          and (odd_referencia_origem is null or odd_referencia_origem <> 'manual')
        """
    )
    return [
        PickParaResolverOdds(
            pick_id=str(row[0]), fixture_id=str(row[1]), mercado=row[2], selecao=row[3],
            time_casa=row[4], time_fora=row[5], casa_id=str(row[6]) if row[6] else None,
            odd_citada=float(row[7]) if row[7] is not None else None,
        )
        for row in cur.fetchall()
    ]


def carregar_casas_licenciadas(cur: psycopg.Cursor) -> set[str]:
    cur.execute("select id from casas where licenciada_br = true")
    return {str(row[0]) for row in cur.fetchall()}


def carregar_odds_referencia(cur: psycopg.Cursor) -> dict[tuple[str, str, str], list[float]]:
    cur.execute("select fixture_id, mercado, selecao, valor from odds_referencia")
    odds: dict[tuple[str, str, str], list[float]] = {}
    for fixture_id, mercado, selecao, valor in cur.fetchall():
        odds.setdefault((str(fixture_id), mercado, selecao), []).append(float(valor))
    return odds


def carregar_nomes_casas_licenciadas(cur: psycopg.Cursor) -> set[str]:
    cur.execute("select nome from casas where licenciada_br = true")
    return {normalizar_nome_casa(row[0]) for row in cur.fetchall()}


def carregar_fixtures_espn(cur: psycopg.Cursor, fixture_ids: set[str]) -> dict[str, tuple[str, str]]:
    if not fixture_ids:
        return {}
    cur.execute(
        "select id, espn_event_id, liga from fixtures where id = any(%s::uuid[])",
        (list(fixture_ids),),
    )
    return {str(row[0]): (row[1], row[2]) for row in cur.fetchall()}


def picks_candidatos_a_espn(
    pendentes: list[PickParaResolverOdds],
    casas_licenciadas: set[str],
    odds_por_fixture: dict[tuple[str, str, str], list[float]],
) -> list[PickParaResolverOdds]:
    # So vale gastar uma chamada de rede pro nivel 3 quando os niveis 1/2
    # (dado ja em maos) nao resolveram E a selecao normaliza - a mesma
    # checagem que resolver_odd_espn faz internamente, replicada aqui
    # pra nao buscar o /summary de uma fixture cujo pick nunca poderia
    # usar o resultado (ex.: mercado fora de 1x2, dupla chance).
    candidatos = []
    for pick in pendentes:
        if resolver_odd_referencia(pick, casas_licenciadas, odds_por_fixture) is not None:
            continue
        if pick.mercado != "1x2":
            continue
        if normalizar_selecao_1x2(pick.selecao, pick.time_casa, pick.time_fora) is None:
            continue
        candidatos.append(pick)
    return candidatos


def buscar_odds_espn_por_fixture(
    fixtures_espn: dict[str, tuple[str, str]], espn_base_url: str
) -> dict[str, dict]:
    """Fase de rede (Fase 4 - mesmo padrao de scripts/collect_results.py:
    sem transacao aberta durante o loop rate-limited, uma falha numa
    fixture nao derruba as demais ja buscadas)."""
    payloads: dict[str, dict] = {}
    with httpx.Client() as client:
        for fixture_id, (espn_event_id, liga) in fixtures_espn.items():
            try:
                payloads[fixture_id] = fetch_summary(client, espn_base_url, liga, espn_event_id)
            except httpx.HTTPError as exc:
                log.warning("falha_ao_buscar_odds_espn", fixture_id=fixture_id, liga=liga, erro=str(exc))
            time.sleep(RATE_LIMIT_SECONDS)
    return payloads


def aplicar_resolucao(
    cur: psycopg.Cursor,
    pick: PickParaResolverOdds,
    casas_licenciadas: set[str],
    odds_por_fixture: dict[tuple[str, str, str], list[float]],
    margem_pct: float,
    odd_minima_absoluta: float,
    odd_espn: OddReferenciaEncontrada | None = None,
) -> str:
    # odd_espn (nivel 3) e' opcional e ja vem pre-computada pelo chamador
    # (`executar()`, apos a fase de rede) - esta funcao nunca faz I/O,
    # so aplica o resultado ja decidido. Default None preserva a
    # assinatura pros testes/chamadas existentes que nunca tem nivel 3
    # disponivel.
    encontrada = resolver_odd_referencia(pick, casas_licenciadas, odds_por_fixture) or odd_espn

    if encontrada is None:
        cur.execute("update picks set status = 'sem_odd' where id = %s::uuid", (pick.pick_id,))
        upsert_pick_orfao(cur, pick.pick_id, "sem odd de referencia disponivel (nivel fonte/oddspapi nao resolveram)")
        return "sem_odd"

    if encontrada.valor < odd_minima_absoluta:
        # Exclusao automatica, nunca so um alerta (documento original,
        # secao "Filtro de qualidade") - motivo gravado, nao descartado
        # silenciosamente. Mas a odd de referencia/minima "sombra" e'
        # gravada mesmo assim (Fase 6d, "Cada um deles tem odd de
        # referencia e odd minima sombra, capturadas na coleta, entao o
        # ROI e' calculavel para todos") - sem isso, um pick rejeitado
        # pelo piso nunca poderia entrar no relatorio de performance por
        # fonte, que precisa comparar publicado x rejeitado na mesma base.
        #
        # Achado do code-reviewer, documentado (nao e' bug): como
        # `encontrada.valor` e' por definicao < odd_minima_absoluta
        # aqui, `calcular_odd_minima` SEMPRE devolve exatamente o piso
        # absoluto pra esse pick - o `max(...)` nunca escolhe o outro
        # lado. Isso e' intencional, nao degeneracao acidental: a
        # "mesma formula de piso" pra todo pick (spec, "Comparabilidade")
        # responde exatamente essa pergunta pra um pick rejeitado -
        # "se esse pick tivesse batido nosso piso exato, seria lucro?"
        # - nao tenta reconstruir a odd real de mercado (que nunca foi
        # sequer oferecida a um assinante). Trocar pra odd_referencia
        # direto quebraria a comparabilidade em outra direcao (bases
        # diferentes conforme o motivo de exclusao).
        odd_minima_sombra = calcular_odd_minima(encontrada.valor, margem_pct, odd_minima_absoluta)
        cur.execute(
            """
            update picks
            set status = 'descartado', odd_referencia = %s, odd_referencia_origem = %s,
                odd_referencia_em = now(), odd_minima = %s
            where id = %s::uuid
            """,
            (encontrada.valor, encontrada.origem, odd_minima_sombra, pick.pick_id),
        )
        upsert_pick_orfao(
            cur, pick.pick_id,
            f"odd_referencia {encontrada.valor:.3f} abaixo do piso ODD_MINIMA_ABSOLUTA {odd_minima_absoluta:.2f}",
        )
        return "descartado"

    odd_minima = calcular_odd_minima(encontrada.valor, margem_pct, odd_minima_absoluta)
    cur.execute(
        """
        update picks
        set odd_referencia = %s, odd_referencia_origem = %s, odd_referencia_em = now(), odd_minima = %s
        where id = %s::uuid
        """,
        (encontrada.valor, encontrada.origem, odd_minima, pick.pick_id),
    )
    return "resolvido"


def executar() -> ResultadoEtapa:
    settings = get_settings()

    with get_connection() as conn:
        with conn.cursor() as cur:
            pendentes = buscar_picks_vinculados(cur)
            casas_licenciadas = carregar_casas_licenciadas(cur)
            odds_por_fixture = carregar_odds_referencia(cur)
            casas_licenciadas_nomes = carregar_nomes_casas_licenciadas(cur)
            candidatos_espn = picks_candidatos_a_espn(pendentes, casas_licenciadas, odds_por_fixture)
            fixtures_espn = carregar_fixtures_espn(cur, {p.fixture_id for p in candidatos_espn})

    # Fase de rede (nivel 3, ver docstring do modulo) - so pras fixtures
    # que os niveis 1/2 nao resolveram, nunca pro conjunto inteiro de
    # pendentes.
    payloads_por_fixture = buscar_odds_espn_por_fixture(fixtures_espn, settings.espn_base_url)
    odd_espn_por_pick = {
        pick.pick_id: resolvido
        for pick in candidatos_espn
        if (payload := payloads_por_fixture.get(pick.fixture_id)) is not None
        and (resolvido := resolver_odd_espn(pick, payload, casas_licenciadas_nomes)) is not None
    }

    contagem = {"resolvido": 0, "sem_odd": 0, "descartado": 0}
    with get_connection() as conn:
        with conn.cursor() as cur:
            for pick in pendentes:
                resultado = aplicar_resolucao(
                    cur, pick, casas_licenciadas, odds_por_fixture,
                    settings.margem_pct, settings.odd_minima_absoluta,
                    odd_espn=odd_espn_por_pick.get(pick.pick_id),
                )
                contagem[resultado] += 1
        conn.commit()

    detalhe = {
        "pendentes": len(pendentes), "candidatos_nivel3": len(candidatos_espn),
        "resolvidos_nivel3": len(odd_espn_por_pick), **contagem,
    }
    itens_erro = contagem["sem_odd"] + contagem["descartado"]
    return ResultadoEtapa(status="ok", itens_ok=contagem["resolvido"], itens_erro=itens_erro, detalhe=detalhe)


def main() -> int:
    resultado = executar()
    print(f"{resultado.detalhe['pendentes']} pick(s) vinculado(s)/sem_odd pra tentar resolver odd de referencia.")
    print(
        f"resolvido: {resultado.detalhe['resolvido']} | sem_odd: {resultado.detalhe['sem_odd']} "
        f"| descartado: {resultado.detalhe['descartado']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
