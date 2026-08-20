"""Simulacao de banca (Fase 6b) - dois niveis de extrato sobre o mesmo
motor: `master_ledger` (mestre, publicado, um so por operacao) e `bets`
(por usuario, recorte do mestre com a banca dele aplicada).

`bets` ja existia desde a Fase 0 (`migrations/0001_init.sql`), com um
comentario ("Regra de ouro do extrato") e ja referenciada em
`app.users.EXPORT_TABELAS` (Fase 5b) - a intencao de tel-la populada por
usuario nunca foi abandonada, apesar da prosa da secao 6b do documento
("nao duplique o extrato mestre 200 vezes") descrever so o
`master_ledger`. As duas coisas nao competem: `master_ledger` centraliza
o FATO da liquidacao (resultado, odd publicada, fator) uma vez so;
`bets` materializa a projecao de CADA usuario sobre esse fato (stake e
banca sao inerentemente pessoais - banca_inicial/stake_pct/modo_stake
variam por usuario, `user_bankroll_config`), nao uma copia redundante.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Sequence
from zoneinfo import ZoneInfo

# subscriptions.inicio/fim sao datas de calendario do Brasil (registradas
# via scripts/subs.py), nao UTC - mesmo fuso operacional ja usado em
# app.pipeline.data_operacional, pelo mesmo motivo (achado do
# code-reviewer: um kickoff as 22h BRT vira o dia seguinte em UTC).
_FUSO_ASSINATURA = ZoneInfo("America/Sao_Paulo")

Resultado = Literal["green", "meio_green", "void", "meio_red", "red"]
ModoStake = Literal["fixo", "proporcional"]

_FATOR_RESULTADO: dict[Resultado, str] = {
    "void": "1",
    "meio_red": "0.5",
    "red": "0",
}


def calcular_fator_retorno(resultado: Resultado, odd: Decimal) -> Decimal:
    # green -> odd, meio_green -> (odd+1)/2 dependem da odd; os outros
    # tres sao constantes - tabela fixa da spec (secao 6b, "Calculo").
    if resultado == "green":
        return odd
    if resultado == "meio_green":
        return (odd + 1) / 2
    return Decimal(_FATOR_RESULTADO[resultado])


# Peso de cada resultado na taxa de acerto - compartilhado entre
# app.settlement.metricas (Fase 6c, por usuario) e
# app.settlement.performance_fonte (Fase 6d, por fonte), pra nao
# duplicar a mesma convencao em dois lugares (achado real da revisao
# holistica pos-Fase 2: duplicacao de regra de negocio e' o tipo de
# coisa que diverge silenciosamente quando um lado muda e o outro nao).
# Decisao desta sessao, sem confirmacao com o PM: void fica FORA do
# dict de proposito - excluido do denominador (devolve o stake sem
# nenhum risco assumido, nao e' nem acerto nem erro, convencao padrao
# de mercado de apostas). So a spec confirma "meio-green como 0,5"; o
# resto (void fora, meio_red no denominador com peso 0) e' extrapolacao
# razoavel, nao literal.
_PESO_TAXA_ACERTO: dict[Resultado, Decimal] = {
    "green": Decimal("1"),
    "meio_green": Decimal("0.5"),
    "meio_red": Decimal("0"),
    "red": Decimal("0"),
}


def calcular_taxa_acerto(resultados: Sequence[Resultado]) -> Decimal | None:
    decididos = [r for r in resultados if r in _PESO_TAXA_ACERTO]
    if not decididos:
        return None
    return sum((_PESO_TAXA_ACERTO[r] for r in decididos), Decimal("0")) / len(decididos)


@dataclass(frozen=True)
class EntradaLedger:
    # Uma linha do master_ledger, na forma que o replay de banca precisa
    # - kickoff_utc e pick_id sao a chave de ordenacao deterministica
    # (spec: "Ordenacao deterministica por kickoff, com desempate pelo
    # id do palpite"). message_id fica None pro extrato mestre (nao e'
    # de ninguem especifico) e populado pro extrato de um usuario (qual
    # mensagem entregou aquele pick pra ele).
    pick_id: str
    fixture_id: str
    kickoff_utc: datetime
    odd: Decimal
    resultado: Resultado
    fator_retorno: Decimal
    message_id: str | None = None


def ordenar_deterministico(entradas: list[EntradaLedger]) -> list[EntradaLedger]:
    return sorted(entradas, key=lambda e: (e.kickoff_utc, e.pick_id))


@dataclass(frozen=True)
class Aposta:
    # Uma linha calculada de `bets` - stake_valor/banca_antes/banca_depois
    # sao Decimal ate a borda de escrita (mesma convencao de Decimal ja
    # firmada desde a Fase 4, nunca float em dinheiro/odd).
    pick_id: str
    fixture_id: str
    message_id: str | None
    odd: Decimal
    stake_valor: Decimal
    stake_pct: Decimal
    resultado: Resultado
    retorno: Decimal
    banca_antes: Decimal
    banca_depois: Decimal
    sequencia: int


def simular_extrato(
    entradas: list[EntradaLedger],
    *,
    banca_inicial: Decimal,
    stake_pct: Decimal,
    modo_stake: ModoStake,
) -> list[Aposta]:
    # "Reprocessar o extrato inteiro tem que dar exatamente o mesmo
    # resultado, sempre" (spec) - funcao pura, sem leitura de relogio
    # nem de estado externo, determinada 100% pelas entradas e pela
    # config recebida.
    ordenadas = ordenar_deterministico(entradas)

    apostas: list[Aposta] = []
    banca_atual = banca_inicial
    for indice, entrada in enumerate(ordenadas, start=1):
        banca_base = banca_inicial if modo_stake == "fixo" else banca_atual
        stake_valor = banca_base * stake_pct
        retorno = stake_valor * entrada.fator_retorno
        banca_antes = banca_atual
        banca_depois = banca_antes - stake_valor + retorno

        apostas.append(
            Aposta(
                pick_id=entrada.pick_id,
                fixture_id=entrada.fixture_id,
                message_id=entrada.message_id,
                odd=entrada.odd,
                stake_valor=stake_valor,
                stake_pct=stake_pct,
                resultado=entrada.resultado,
                retorno=retorno,
                banca_antes=banca_antes,
                banca_depois=banca_depois,
                sequencia=indice,
            )
        )
        banca_atual = banca_depois

    return apostas


def filtrar_por_periodos_assinatura(
    entradas: list[EntradaLedger], periodos: list[tuple[date, date]]
) -> list[EntradaLedger]:
    # "Se o usuario ficou inadimplente e voltou, o periodo sem pagamento
    # nao gera entradas e a banca continua de onde parou" - o replay em
    # simular_extrato ja continua a banca naturalmente (nao reseta entre
    # entradas), entao o "continua de onde parou" cai de graca so filtrando
    # as entradas fora de qualquer periodo, sem tratamento especial pro
    # gap. So a PRIMEIRA entrada do extrato usa banca_inicial (efeito
    # colateral de simular_extrato comecar com banca_atual = banca_inicial).
    def _data_local(kickoff_utc: datetime) -> date:
        return kickoff_utc.astimezone(_FUSO_ASSINATURA).date()

    return [e for e in entradas if any(inicio <= _data_local(e.kickoff_utc) <= fim for inicio, fim in periodos)]
