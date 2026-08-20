"""Relatorio diario (Fase 7, spec: "envios do dia, pulos e motivos,
opt-outs, liquidacoes e taxa de nao liquidados"). Funcao pura de
formatacao separada da leitura, mesmo padrao DB-shape/pura do resto do
projeto.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import psycopg

from app.pipeline import limites_utc_do_dia


@dataclass(frozen=True)
class RelatorioDiario:
    data: date
    enviados: int
    pulados: int
    pulados_por_motivo: dict[str, int]
    opt_outs: int
    liquidados: int
    liquidados_por_resultado: dict[str, int]
    nao_liquidados: int
    taxa_nao_liquidados: Decimal | None


def buscar_relatorio_diario(cur: psycopg.Cursor, data_ref: date) -> RelatorioDiario:
    inicio_utc, fim_utc = limites_utc_do_dia(data_ref)

    cur.execute(
        "select count(*) from messages where status = 'enviada' and enviada_em >= %s and enviada_em < %s",
        (inicio_utc, fim_utc),
    )
    enviados = cur.fetchone()[0]

    cur.execute(
        "select motivo_pulo, count(*) from messages "
        "where status = 'pulada' and gerada_em >= %s and gerada_em < %s group by motivo_pulo",
        (inicio_utc, fim_utc),
    )
    pulados_por_motivo = {motivo or "sem motivo": total for motivo, total in cur.fetchall()}
    pulados = sum(pulados_por_motivo.values())

    cur.execute("select count(*) from users where opt_out_em >= %s and opt_out_em < %s", (inicio_utc, fim_utc))
    opt_outs = cur.fetchone()[0]

    cur.execute(
        "select resultado, count(*) from pick_results "
        "where liquidado_em >= %s and liquidado_em < %s group by resultado",
        (inicio_utc, fim_utc),
    )
    por_resultado = {resultado: total for resultado, total in cur.fetchall()}
    nao_liquidados = por_resultado.pop("nao_liquidavel", 0)
    liquidados = sum(por_resultado.values())

    total_tentado = liquidados + nao_liquidados
    taxa_nao_liquidados = Decimal(nao_liquidados) / total_tentado if total_tentado else None

    return RelatorioDiario(
        data=data_ref, enviados=enviados, pulados=pulados, pulados_por_motivo=pulados_por_motivo,
        opt_outs=opt_outs, liquidados=liquidados, liquidados_por_resultado=por_resultado,
        nao_liquidados=nao_liquidados, taxa_nao_liquidados=taxa_nao_liquidados,
    )
