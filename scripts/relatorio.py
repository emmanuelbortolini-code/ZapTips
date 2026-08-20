"""CLI de relatorios - metricas de extrato por usuario (Fase 6c),
performance por fonte (Fase 6d) e relatorio diario (Fase 7). Regra dura
da spec, valida pra usuario/fontes: `nao_liquidados`/taxa de acerto
nunca aparecem sem o ROI do lado - impresso na mesma linha, de proposito.

Uso:
    uv run python -m scripts.relatorio usuario --user-id <uuid> [--periodo 7d|30d|tudo]
    uv run python -m scripts.relatorio fontes [--days 30]
    uv run python -m scripts.relatorio diario [--data AAAA-MM-DD]
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.db import get_connection
from app.pipeline import data_operacional
from app.relatorio_diario import buscar_relatorio_diario
from app.settlement.performance_fonte import MetricasGrupo, sugerir_acoes
from app.settlement.relatorio_fonte import (
    buscar_quarentena_por_fonte,
    gerar_relatorio_por_fonte,
    gerar_relatorio_por_fonte_e_mercado,
    gerar_relatorio_por_fonte_e_tipster,
)
from app.settlement.relatorio_usuario import gerar_relatorio_usuario
from scripts._cli_args import data_arg, uuid_arg

_DIAS_JANELA_SUGESTAO = 60

_DIAS_POR_JANELA = {"7d": 7, "30d": 30}


def _resolver_desde(periodo: str) -> datetime | None:
    if periodo == "tudo":
        return None
    return datetime.now(timezone.utc) - timedelta(days=_DIAS_POR_JANELA[periodo])


def _cmd_usuario(args: argparse.Namespace) -> int:
    desde = _resolver_desde(args.periodo)
    settings = get_settings()

    with get_connection() as conn:
        with conn.cursor() as cur:
            m = gerar_relatorio_usuario(cur, args.user_id, desde, settings)

    variacao_pct = f", {m.variacao_percentual:.2%}" if m.variacao_percentual is not None else ""
    print(f"Periodo: {args.periodo}")
    print(f"Banca atual: R$ {m.banca_atual:.2f} (variacao: R$ {m.variacao_absoluta:.2f}{variacao_pct})")

    roi_texto = f"{m.roi:.2%}" if m.roi is not None else "-"
    print(f"Total apostado: R$ {m.total_apostado:.2f} | Lucro: R$ {m.lucro:.2f} | ROI: {roi_texto}", end="")
    print(f" | Nao liquidados no periodo: {m.nao_liquidados_no_periodo}")

    if m.taxa_acerto is not None:
        print(f"Taxa de acerto: {m.taxa_acerto:.1%}")
    if m.odd_media is not None:
        print(f"Odd media: {m.odd_media:.3f}")

    recuperacao = f" (recuperado em {m.dias_para_recuperar}d)" if m.dias_para_recuperar is not None else ""
    print(f"Drawdown maximo: R$ {m.drawdown_maximo:.2f}{recuperacao}")

    if m.sequencia_atual is not None:
        tipo, contagem = m.sequencia_atual
        print(f"Sequencia atual: {contagem}x {tipo}")

    print(f"Apostas no periodo: {m.apostas_no_periodo}")
    return 0


def _imprimir_grupos(titulo: str, grupos: list[MetricasGrupo]) -> None:
    print(f"-- {titulo} --")
    if not grupos:
        print("(nenhum dado no periodo)")
        return
    for g in sorted(grupos, key=lambda g: g.chave):
        chave_texto = " / ".join(g.chave)
        # ROI sempre na mesma linha que taxa_acerto - regra dura da spec
        # ("nenhuma taxa de acerto e exibida sem o ROI ao lado").
        roi_texto = f"{g.roi:.2%}" if g.roi is not None else "-"
        linha = f"{chave_texto}: liquidado={g.volume_liquidado} sem_odd={g.volume_sem_odd} ROI={roi_texto}"
        if g.taxa_acerto is not None:
            linha += f" taxa_acerto={g.taxa_acerto:.1%}"
        if g.percentual_nao_liquidados is not None:
            linha += f" nao_liquidados={g.percentual_nao_liquidados:.1%}"
        if g.odd_media is not None:
            linha += f" odd_media={g.odd_media:.3f}"
        if g.diferenca_media_odd is not None:
            linha += f" diff_odd_citada_vs_referencia={g.diferenca_media_odd:+.3f}"
        print(linha)


def _cmd_fontes(args: argparse.Namespace) -> int:
    desde = datetime.now(timezone.utc) - timedelta(days=args.days)
    desde_janela_sugestao = datetime.now(timezone.utc) - timedelta(days=_DIAS_JANELA_SUGESTAO)

    with get_connection() as conn:
        with conn.cursor() as cur:
            por_fonte = gerar_relatorio_por_fonte(cur, desde)
            por_mercado = gerar_relatorio_por_fonte_e_mercado(cur, desde)
            por_tipster = gerar_relatorio_por_fonte_e_tipster(cur, desde)
            quarentena_por_fonte = buscar_quarentena_por_fonte(cur)
            por_mercado_janela_sugestao = gerar_relatorio_por_fonte_e_mercado(cur, desde_janela_sugestao)

    print(f"Performance por fonte (ultimos {args.days} dias)\n")
    _imprimir_grupos("Por fonte", por_fonte)
    print()
    _imprimir_grupos("Por fonte + mercado", por_mercado)
    print()
    _imprimir_grupos("Por fonte + tipster", por_tipster)

    sugestoes = sugerir_acoes(por_mercado_janela_sugestao, quarentena_por_fonte=quarentena_por_fonte)
    if sugestoes:
        print(f"\nSugestoes (janela fixa de {_DIAS_JANELA_SUGESTAO} dias, volume minimo 30, sempre por mercado):")
        for s in sugestoes:
            print(f"  {s.tipo}: {' / '.join(s.chave)} | ROI {s.roi:.2%} | volume {s.volume}")

    return 0


def _cmd_diario(args: argparse.Namespace) -> int:
    data_ref = args.data if args.data is not None else data_operacional()

    with get_connection() as conn:
        with conn.cursor() as cur:
            r = buscar_relatorio_diario(cur, data_ref)

    print(f"Relatorio diario: {r.data}")
    print(f"Envios: {r.enviados} | Pulos: {r.pulados} | Opt-outs: {r.opt_outs}")
    if r.pulados_por_motivo:
        print("Pulos por motivo:")
        for motivo, total in sorted(r.pulados_por_motivo.items(), key=lambda item: -item[1]):
            print(f"  {motivo}: {total}")

    taxa_texto = f"{r.taxa_nao_liquidados:.1%}" if r.taxa_nao_liquidados is not None else "-"
    print(f"Liquidacoes: {r.liquidados} | Nao liquidados: {r.nao_liquidados} | Taxa nao liquidados: {taxa_texto}")
    if r.liquidados_por_resultado:
        print("Liquidacoes por resultado:")
        for resultado, total in sorted(r.liquidados_por_resultado.items(), key=lambda item: -item[1]):
            print(f"  {resultado}: {total}")

    return 0


def _montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.relatorio")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_usuario = sub.add_parser("usuario")
    p_usuario.add_argument("--user-id", dest="user_id", required=True, type=uuid_arg)
    p_usuario.add_argument("--periodo", choices=("7d", "30d", "tudo"), default="tudo")
    p_usuario.set_defaults(func=_cmd_usuario)

    p_fontes = sub.add_parser("fontes")
    p_fontes.add_argument("--days", type=int, default=30)
    p_fontes.set_defaults(func=_cmd_fontes)

    p_diario = sub.add_parser("diario")
    p_diario.add_argument("--data", type=data_arg, default=None)
    p_diario.set_defaults(func=_cmd_diario)

    return parser


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL vazia, abortando.")
        return 1

    args = _montar_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
