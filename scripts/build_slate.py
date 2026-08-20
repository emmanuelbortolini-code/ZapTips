"""Monta o daily_slate do dia (Fase 4, ver app/slate.py).

Filtra picks status='vinculado' com odd_referencia ja resolvida (Fase 4,
resolve_odds.py) e fixture com kickoff nas proximas 24h. Aplica deteccao
de conflito e o limite `SLATE_MAX_PICKS` (ver app/slate.py). Gera o slate
com status='rascunho' - aprovacao e curadoria manual, console da Fase 5,
fora de escopo aqui.

Idempotente por consulta, nao por constraint: se ja existe um slate
'rascunho' pra hoje, reaproveita (apaga e reconstroi so os slate_picks)
em vez de duplicar - so um slate 'aprovado' e imutavel (documento
original, "Slate aprovado e imutavel"). Rodar de novo antes da aprovacao
so atualiza o rascunho com o estado mais recente de picks/odds. Um slate
ja 'aprovado' nunca e tocado por este script.

Uso:
    uv run python -m scripts.build_slate
"""

import sys
from datetime import date, datetime

import psycopg
import structlog

from app.config import get_settings
from app.db import get_connection
from app.messages_generator import carregar_assinantes_elegiveis
from app.picks_orfaos import upsert_pick_orfao
from app.pipeline import ResultadoEtapa, data_operacional
from app.slate import PickParaSlate, instante_de_corte, montar_slate

log = structlog.get_logger()

_MOTIVO_POR_STATUS = {
    "descartado": "descartado por conflito - outra selecao teve maior consenso na mesma fixture/mercado",
    "revisao_manual": "conflito de selecoes na mesma fixture/mercado sem consenso (empate) - decisao manual necessaria",
}


def buscar_picks_candidatos(cur: psycopg.Cursor, corte: datetime) -> tuple[list[PickParaSlate], list[str]]:
    # "s.quarentena is not true" - achado CRITICAL do code-reviewer na
    # Fase 5c: sem isso, um pick de fonte em quarentena entra em
    # slate_picks normalmente (o filtro do console e so na exibicao da
    # aba de curadoria, nao no motor que monta o slate) e pode acabar
    # aprovado sem nenhum aviso, porque a lista renderizada some vazia.
    # "Palpite de fonte em quarentena nunca entra em daily_slates, nem
    # por curadoria manual" (documento original) exige que o corte seja
    # aqui, na montagem, nao so na tela.
    #
    # `corte` e o nivel A do corte de antecedencia minima (D2, Fase 5d) -
    # filtrado em Python, nao em SQL, porque precisamos saber QUAIS
    # picks foram excluidos por isso (pra registrar o motivo em
    # picks_orfaos), nao so descartar silenciosamente.
    cur.execute(
        """
        select p.id, p.fixture_id, p.mercado, p.selecao, p.time_casa, p.time_fora,
               p.odd_referencia, p.odd_referencia_em, p.odd_referencia_origem, p.odd_minima,
               p.confianca_tipster, f.kickoff_utc
        from picks p
        join fixtures f on f.id = p.fixture_id
        join raw_picks rp on rp.id = p.raw_pick_id
        join sources s on s.id = rp.source_id
        where p.status = 'vinculado'
          and p.odd_referencia is not null
          and f.kickoff_utc between now() and now() + interval '24 hours'
          and s.quarentena is not true
        """
    )
    candidatos: list[PickParaSlate] = []
    excluidos_por_antecedencia: list[str] = []
    for row in cur.fetchall():
        if row[11] < corte:
            excluidos_por_antecedencia.append(str(row[0]))
            continue
        candidatos.append(
            PickParaSlate(
                pick_id=str(row[0]), fixture_id=str(row[1]), mercado=row[2], selecao=row[3],
                time_casa=row[4], time_fora=row[5],
                odd_referencia=float(row[6]), odd_referencia_em=row[7], odd_referencia_origem=row[8],
                odd_minima=float(row[9]), confianca_tipster=float(row[10]) if row[10] is not None else 0.0,
            )
        )
    return candidatos, excluidos_por_antecedencia


def buscar_rascunho_existente(cur: psycopg.Cursor, data_slate: date) -> str | None:
    # substitui_slate_id is null: um rascunho de correcao manual (que
    # referencia um slate ja aprovado, ver migration 0014) nunca deve ser
    # apagado/reconstruido por uma rodada automatica deste script -
    # achado do code-reviewer. So reaproveita o rascunho "original".
    # curadoria_iniciada_em is null (migration 0019, Fase 5c): defesa em
    # profundidade - o guard principal e existe_curadoria_em_andamento,
    # checado antes de chegar aqui, mas esta funcao tambem nunca reaproveita
    # (e portanto nunca apaga slate_picks de) um rascunho ja em curadoria.
    cur.execute(
        """
        select id from daily_slates
        where data = %s and status = 'rascunho' and substitui_slate_id is null and curadoria_iniciada_em is null
        order by criado_em desc limit 1
        """,
        (data_slate,),
    )
    row = cur.fetchone()
    return str(row[0]) if row else None


def existe_correcao_em_andamento(cur: psycopg.Cursor, data_slate: date) -> bool:
    cur.execute(
        "select 1 from daily_slates where data = %s and status = 'rascunho' and substitui_slate_id is not null limit 1",
        (data_slate,),
    )
    return cur.fetchone() is not None


def existe_curadoria_em_andamento(cur: psycopg.Cursor, data_slate: date) -> bool:
    # Achado real da Fase 5c: sem isso, um re-run automatico (Fase 7)
    # nao apagaria o rascunho em curadoria (buscar_rascunho_existente ja
    # o ignora), mas CRIARIA UM SEGUNDO rascunho vazio pra mesma data -
    # pior que apagar, porque o rascunho curado fica orfao (invisivel,
    # nao apagado) atras do novo. Por isso o abort tem que ser cedo,
    # antes de chegar em criar_ou_reaproveitar_slate - mesmo padrao ja
    # usado pra existe_correcao_em_andamento.
    cur.execute(
        """
        select 1 from daily_slates
        where data = %s and status = 'rascunho' and substitui_slate_id is null and curadoria_iniciada_em is not null
        limit 1
        """,
        (data_slate,),
    )
    return cur.fetchone() is not None


def criar_ou_reaproveitar_slate(cur: psycopg.Cursor, data_slate: date) -> str:
    # SELECT-entao-INSERT sem lock: existe uma corrida teorica entre duas
    # execucoes concorrentes deste script (ambas veem "sem rascunho" e
    # criam um daily_slates duplicado pra mesma data). Aceito sem lock
    # explicito porque a arquitetura do projeto ja decide isso em outro
    # nivel - "roda so na maquina local do PM... scheduler via APScheduler
    # em processo unico" (CLAUDE.md, "Ambiente de execucao") - nunca ha
    # dois processos concorrentes rodando este script por design, nem na
    # Fase 7. Revisitar so se isso mudar.
    slate_id = buscar_rascunho_existente(cur, data_slate)
    if slate_id is not None:
        cur.execute("delete from slate_picks where slate_id = %s::uuid", (slate_id,))
        return slate_id

    cur.execute("insert into daily_slates (data) values (%s) returning id", (data_slate,))
    return str(cur.fetchone()[0])


def inserir_slate_picks(cur: psycopg.Cursor, slate_id: str, incluidos: list[PickParaSlate]) -> None:
    for ordem, pick in enumerate(incluidos, start=1):
        cur.execute(
            """
            insert into slate_picks (
                slate_id, pick_id, ordem, incluido_por, odd_referencia, odd_referencia_em,
                odd_referencia_origem, odd_minima
            )
            values (%s::uuid, %s::uuid, %s, 'automatico', %s, %s, %s, %s)
            """,
            (
                slate_id, pick.pick_id, ordem, pick.odd_referencia, pick.odd_referencia_em,
                pick.odd_referencia_origem, pick.odd_minima,
            ),
        )


def aplicar_decisoes_conflito(cur: psycopg.Cursor, decisoes: list[tuple[str, str]]) -> None:
    for pick_id, novo_status in decisoes:
        cur.execute("update picks set status = %s where id = %s::uuid", (novo_status, pick_id))
        upsert_pick_orfao(cur, pick_id, _MOTIVO_POR_STATUS[novo_status])


def executar() -> ResultadoEtapa:
    settings = get_settings()
    hoje = data_operacional()

    with get_connection() as conn:
        with conn.cursor() as cur:
            if existe_correcao_em_andamento(cur, hoje):
                # Nao e falha da etapa (F6, CLAUDE.md Fase 5a) - e o
                # script recusando deliberadamente pisar no trabalho de
                # curadoria manual em andamento. O run pode fechar
                # 'pronto' mesmo com isso.
                return ResultadoEtapa(status="ok", detalhe={"pulado": "correcao_manual_em_andamento", "data": str(hoje)})
            if existe_curadoria_em_andamento(cur, hoje):
                # Mesmo raciocinio, achado na Fase 5c: o rascunho original
                # ja esta sendo curado no console - um re-run automatico
                # nao pode nem reaproveitar nem criar um segundo rascunho.
                return ResultadoEtapa(status="ok", detalhe={"pulado": "curadoria_em_andamento", "data": str(hoje)})

            n_assinantes = len(carregar_assinantes_elegiveis(cur, hoje))
            corte = instante_de_corte(
                data_slate=hoje, horario_envio=settings.horario_envio,
                intervalo_segundos=settings.intervalo_envio_segundos,
                n_assinantes=n_assinantes, antecedencia_horas=settings.antecedencia_minima_horas,
            )
            candidatos, excluidos_por_antecedencia = buscar_picks_candidatos(cur, corte)

    incluidos, decisoes = montar_slate(candidatos, settings.slate_max_picks)

    with get_connection() as conn:
        with conn.cursor() as cur:
            aplicar_decisoes_conflito(cur, decisoes)
            for pick_id in excluidos_por_antecedencia:
                upsert_pick_orfao(
                    cur, pick_id,
                    f"excluido por antecedencia minima - kickoff antes do corte de {corte.isoformat()}",
                )
            slate_id = criar_ou_reaproveitar_slate(cur, hoje)
            inserir_slate_picks(cur, slate_id, incluidos)
        conn.commit()

    detalhe = {
        "data": str(hoje),
        "slate_id": slate_id,
        "candidatos": len(candidatos),
        "incluidos": len(incluidos),
        "decisoes_conflito": len(decisoes),
        "excluidos_por_antecedencia": len(excluidos_por_antecedencia),
    }
    return ResultadoEtapa(status="ok", itens_ok=len(incluidos), itens_erro=len(decisoes), detalhe=detalhe)


_MENSAGEM_POR_PULADO = {
    "correcao_manual_em_andamento": (
        "Ja existe uma correcao manual em andamento pra {data} (rascunho referenciando "
        "um slate aprovado) - abortando pra nao apagar o trabalho de curadoria."
    ),
    "curadoria_em_andamento": (
        "O rascunho de {data} ja esta em curadoria no console - abortando pra nao apagar "
        "nem duplicar o trabalho em andamento."
    ),
}


def main() -> int:
    resultado = executar()

    pulado = resultado.detalhe.get("pulado")
    if pulado:
        print(_MENSAGEM_POR_PULADO[pulado].format(data=resultado.detalhe["data"]))
        return 1

    print(f"{resultado.detalhe['candidatos']} pick(s) candidato(s) (vinculados, com odd, kickoff nas proximas 24h).")
    print(
        f"slate {resultado.detalhe['data']} (id {resultado.detalhe['slate_id']}): {resultado.detalhe['incluidos']} "
        f"pick(s) incluido(s), {resultado.detalhe['decisoes_conflito']} decisao(oes) de conflito aplicada(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
