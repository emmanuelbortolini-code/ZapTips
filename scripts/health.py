"""CLI de saude (Fase 7, spec: "O CLI python -m app.health devolve o
mesmo [que a aba Saude do console] em texto, para eu conferir sem abrir
o navegador"). Renomeado pra scripts/ - mesma decisao D1 ja tomada em
scripts/users.py/scripts/subs.py/scripts/liquidacao.py: o projeto
mantem toda logica de negocio/CLI fora de app/.

Reaproveita literalmente as mesmas funcoes de app.console.queries/rules
que alimentam a aba `/saude` (Fase 5c) - nunca uma segunda
implementacao da mesma pergunta, pra nao arriscar os dois lados
divergirem.

Uso:
    uv run python -m scripts.health
"""

import sys

from app.config import get_settings
from app.console.queries import carregar_estado_run, encerradas_sem_liquidacao, fontes_alerta_nao_liquidados, historico_coleta, mensagens_expiradas, orfaos_aguardando_partida, quota_mes, revisao_manual_pendente
from app.console.rules import FONTES_COLETA, dias_fora_por_fonte, projetar_quota
from app.db import get_connection
from app.pipeline import data_operacional
from app.subs import listar_vencendo

DIAS_HISTORICO_COLETA = 14


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL vazia, abortando.")
        return 1

    hoje = data_operacional()

    with get_connection() as conn:
        with conn.cursor() as cur:
            estado = carregar_estado_run(cur, hoje)
            historico = historico_coleta(cur, dias=DIAS_HISTORICO_COLETA)
            chamadas, limite = quota_mes(cur, hoje.strftime("%Y-%m"))
            quota = projetar_quota(chamadas, limite, hoje)
            orfaos = orfaos_aguardando_partida(cur)
            sem_liquidacao = encerradas_sem_liquidacao(cur)
            revisao_pendente = revisao_manual_pendente(cur)
            expiradas = mensagens_expiradas(cur)
            alertas_fontes = fontes_alerta_nao_liquidados(cur, settings.nao_liquidavel_alerta_pct)
            vencendo = listar_vencendo(cur, hoje=hoje)

    print(f"ZapTips - saude ({hoje.isoformat()})")
    print()

    print(f"Pipeline de hoje: {'sem execucao ainda' if not estado.existe else estado.status}")
    for etapa in estado.etapas:
        print(f"  [{etapa.ordem}] {etapa.nome}: {etapa.status} (ok={etapa.itens_ok} erro={etapa.itens_erro})")
    print()

    print("Coleta por fonte (dias fora do ar nos ultimos %d dias):" % DIAS_HISTORICO_COLETA)
    dias_fora = dias_fora_por_fonte(historico, FONTES_COLETA)
    for fonte in FONTES_COLETA:
        print(f"  {fonte}: {dias_fora[fonte]}d fora")
    print()

    print(f"Cota OddsPapi do mes: {quota.chamadas}", end="")
    if quota.limite is not None:
        print(f"/{quota.limite} (restam {quota.restante}, projecao fim do mes: {quota.projecao_fim_mes})")
    else:
        print(" (sem limite configurado)")
    print()

    print(f"Picks orfaos aguardando fixture: {orfaos}")
    print(f"Fixtures encerradas sem liquidacao: {sem_liquidacao}")
    print(f"Picks pendentes de revisao manual: {revisao_pendente}")
    print(f"Mensagens expiradas: {expiradas}")
    print()

    if not alertas_fontes:
        print(f"Nenhuma fonte acima de {settings.nao_liquidavel_alerta_pct:.0%} de nao-liquidados.")
    else:
        print(f"Fontes acima de {settings.nao_liquidavel_alerta_pct:.0%} de nao-liquidados:")
        for alerta in alertas_fontes:
            print(f"  {alerta.fonte}: {alerta.percentual:.0%} ({alerta.total_tentado} tentados)")
    print()

    if not vencendo:
        print("Nenhuma assinatura vencendo em breve.")
    else:
        print("Assinaturas vencendo:")
        for item in vencendo:
            renovado = " (ja renovado)" if item.ja_renovado else ""
            print(f"  {item.nome or item.telefone_e164}: vence {item.fim} (em {item.dias_restantes}d){renovado}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
