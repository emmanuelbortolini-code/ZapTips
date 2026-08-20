"""Logica pura do console (Fase 5c) - decide o que a Saude/Curadoria
mostram a partir de dado ja lido (app/console/queries.py). Sem
Postgres aqui, mesmo split de app/pipeline.py."""

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Sequence
from urllib.parse import quote

from app.console.queries import EstadoEtapaDetalhado, EstadoRun, HistoricoColeta, ItemSlate, MensagemNaFila, SessaoEnvio
from app.messages_generator import ordem_da_sessao
from app.settlement.performance_fonte import MetricasGrupo

# Nomes internos das sub-etapas de coleta, mesmos usados em
# scripts/run_pipeline.py::_adaptador_coleta (chave do dict `sub`) - nao
# e o nome de exibicao da fonte (ver sources.nome, "Eagle Predict"/"Sites
# de Apostas"), e a chave que aparece em detalhe_json.subetapas.
FONTES_COLETA: tuple[str, ...] = ("eagle_predict", "sda")


def formatar_roi(roi: Decimal | None) -> str:
    if roi is None:
        return "n/d"
    return f"{'+' if roi > 0 else ''}{roi:.1%}"


def formatar_percentual(valor: Decimal | None) -> str:
    if valor is None:
        return "n/d"
    return f"{valor:.1%}"


def formatar_odd(odd: Decimal | None) -> str:
    if odd is None:
        return "n/d"
    return f"{odd:.2f}"


def formatar_linha_fonte(metrica: MetricasGrupo, em_quarentena: bool) -> dict:
    return {
        "fonte": metrica.chave[0],
        "status_quarentena": "⚠️ Quarentena" if em_quarentena else "OK",
        "volume_total": metrica.volume_liquidado + metrica.volume_nao_liquidado,
        "roi_formatado": formatar_roi(metrica.roi),
        "taxa_acerto_formatada": formatar_percentual(metrica.taxa_acerto),
        "odd_media_formatada": formatar_odd(metrica.odd_media),
    }


@dataclass(frozen=True)
class ProjecaoQuota:
    chamadas: int
    limite: int | None
    restante: int | None
    projecao_fim_mes: int | None


def projetar_quota(chamadas: int, limite: int | None, hoje: date) -> ProjecaoQuota:
    dias_no_mes = calendar.monthrange(hoje.year, hoje.month)[1]
    media_diaria = chamadas / hoje.day
    projecao = round(media_diaria * dias_no_mes)
    restante = (limite - chamadas) if limite is not None else None
    return ProjecaoQuota(chamadas=chamadas, limite=limite, restante=restante, projecao_fim_mes=projecao)


def dias_fora_por_fonte(historico: Sequence[HistoricoColeta], fontes: Sequence[str]) -> dict[str, int]:
    # Espera `historico` ordenado do dia mais recente pro mais antigo
    # (mesma ordem que queries.historico_coleta devolve). Dia sem dado
    # da fonte (etapa coleta rodou mas essa subetapa nao apareceu no
    # detalhe_json) e pulado, nao quebra nem conta a sequencia.
    resultado: dict[str, int] = {}
    for fonte in fontes:
        dias_fora = 0
        for h in historico:
            sub = h.subetapas.get(fonte)
            if sub is None:
                continue
            if sub.get("status") == "ok":
                break
            dias_fora += 1
        resultado[fonte] = dias_fora
    return resultado


@dataclass(frozen=True)
class AvisoEtapa:
    etapa: str
    status: str
    mensagem: str


@dataclass(frozen=True)
class AcessoCuradoria:
    liberado: bool
    motivo_bloqueio: str | None
    avisos: tuple[AvisoEtapa, ...] = field(default_factory=tuple)


def _etapa_por_nome(estado: EstadoRun, nome: str) -> EstadoEtapaDetalhado | None:
    return next((e for e in estado.etapas if e.nome == nome), None)


def _mensagem_aviso(etapa: EstadoEtapaDetalhado) -> str:
    detalhe = etapa.detalhe

    if detalhe.get("pulado") == "correcao_manual_em_andamento":
        return "rascunho exibido e de uma correcao manual em andamento - nao foi reconstruido nesta execucao"

    if "motivo" in detalhe:
        pendentes = detalhe.get("pendentes")
        sufixo = f", {pendentes} pendente(s)" if pendentes else ""
        return f"{etapa.status} - {detalhe['motivo']}{sufixo}"

    if "subetapas" in detalhe:
        falhas = [nome for nome, sub in detalhe["subetapas"].items() if sub.get("status") != "ok"]
        if falhas:
            return f"{etapa.status} - fonte(s) com problema: {', '.join(falhas)}"

    if etapa.itens_erro:
        return f"{etapa.status} - {etapa.itens_erro} item(ns) com erro"

    return etapa.status


def avaliar_acesso_curadoria(estado: EstadoRun) -> AcessoCuradoria:
    if not estado.existe:
        return AcessoCuradoria(liberado=False, motivo_bloqueio="O pipeline ainda nao rodou hoje.")

    fixtures = _etapa_por_nome(estado, "fixtures")
    if fixtures is not None and fixtures.status == "falhou":
        return AcessoCuradoria(
            liberado=False, motivo_bloqueio="Execucao abortada na etapa fixtures - sem partidas, nao ha slate."
        )

    slate = _etapa_por_nome(estado, "slate")
    if slate is None or slate.status == "pendente":
        return AcessoCuradoria(
            liberado=False,
            motivo_bloqueio=f"Execucao ainda nao chegou na etapa slate (etapa atual: {estado.etapa_atual or '-'}).",
        )
    if slate.status == "rodando":
        return AcessoCuradoria(liberado=False, motivo_bloqueio="Etapa slate em andamento.")

    # slate.status in ("ok", "degradado") a partir daqui - liberado.
    avisos = tuple(
        AvisoEtapa(etapa=e.nome, status=e.status, mensagem=_mensagem_aviso(e))
        for e in estado.etapas
        if e.status != "ok" or e.detalhe.get("pulado")
    )
    return AcessoCuradoria(liberado=True, motivo_bloqueio=None, avisos=avisos)


@dataclass(frozen=True)
class Bloqueio:
    codigo: str
    mensagem: str


def bloqueios_de_aprovacao(
    itens: Sequence[ItemSlate],
    conflitos: dict,
    odd_minima_absoluta: float,
) -> tuple[Bloqueio, ...]:
    # Regra "fonte em quarentena nunca aparece" nao precisa de checagem
    # aqui: app.console.queries.carregar_itens_slate ja filtra na SQL,
    # entao um item de fonte em quarentena e estruturalmente impossivel
    # de chegar em `itens` - bloqueio por design, nao por checagem
    # redundante em runtime.
    bloqueios = []

    sem_odd = [i for i in itens if i.odd_referencia is None or i.odd_minima is None]
    if sem_odd:
        bloqueios.append(Bloqueio("sem_odd_referencia", f"{len(sem_odd)} item(ns) sem odd de referencia ou piso definidos."))

    # Defesa em profundidade: o motor automatico (resolve_odds.py) ja
    # exclui pick com odd abaixo do piso absoluto antes de chegar no
    # slate - mas uma odd de referencia OU um piso digitados
    # manualmente na curadoria (acoes.editar_odd_referencia/editar_piso)
    # passam por aqui de novo. Checar so odd_referencia nao bastava
    # (achado HIGH do code-reviewer): editar_piso grava odd_minima
    # direto, sem tocar odd_referencia, e um piso abaixo do absoluto
    # com odd_referencia valida passava batido.
    abaixo_do_piso = [
        i for i in itens
        if (i.odd_referencia is not None and i.odd_referencia < odd_minima_absoluta)
        or (i.odd_minima is not None and i.odd_minima < odd_minima_absoluta)
    ]
    if abaixo_do_piso:
        bloqueios.append(
            Bloqueio("odd_abaixo_do_piso", f"{len(abaixo_do_piso)} item(ns) com odd de referencia ou piso abaixo do absoluto {odd_minima_absoluta:.2f}.")
        )

    if conflitos:
        bloqueios.append(Bloqueio("conflito_nao_resolvido", f"{len(conflitos)} conflito(s) sem decisao explicita."))

    return tuple(bloqueios)


def divergencia_relativa(odd_citada: float | None, odd_referencia: float | None) -> Decimal | None:
    # Decimal, nao float - mesma razao de app.odds_resolution.
    # calcular_odd_minima (Fase 4): essa comparacao decide um alerta
    # visivel pro operador, imprecisao binaria empurrando o valor pro
    # lado errado da fronteira e o tipo de bug sutil que so aparece
    # tempos depois.
    if odd_citada is None or odd_referencia is None or odd_referencia == 0:
        return None
    citada = Decimal(str(odd_citada))
    referencia = Decimal(str(odd_referencia))
    return abs(citada - referencia) / referencia


def tem_alerta_divergencia(item: ItemSlate, limite_pct: float) -> bool:
    # Alerta, nunca bloqueio (D10, Fase 5d) - nao entra em
    # bloqueios_de_aprovacao.
    divergencia = divergencia_relativa(item.odd_citada, item.odd_referencia)
    if divergencia is None:
        return False
    return divergencia > Decimal(str(limite_pct))


LIMITE_AVISO_CARACTERES = 1500


def montar_link_whatsapp(telefone_e164: str, corpo: str) -> str:
    # safe='' - o default de urllib.parse.quote deixa '/' passar sem
    # escapar, o que nao e o que se quer dentro de um query param. Sem
    # isso, um corpo com '/' (comum em placar/data) quebraria o
    # parsing da URL em alguns clientes.
    telefone_sem_mais = telefone_e164.lstrip("+")
    return f"https://wa.me/{telefone_sem_mais}?text={quote(corpo, safe='')}"


def excede_limite_caracteres(corpo: str) -> bool:
    return len(corpo) > LIMITE_AVISO_CARACTERES


def expira_em_horas(kickoff_utc: datetime, agora: datetime, horas: float) -> bool:
    return kickoff_utc - agora <= timedelta(hours=horas)


@dataclass(frozen=True)
class AcessoEnvio:
    liberado: bool
    motivo_bloqueio: str | None


def avaliar_acesso_envio(estado: EstadoRun, slate_status: str | None) -> AcessoEnvio:
    # "So abre depois do slate aprovado" (documento original) - reusa o
    # mesmo gate da Curadoria (pipeline tem que ter chegado na etapa
    # slate) e adiciona a exigencia propria desta aba.
    acesso_curadoria = avaliar_acesso_curadoria(estado)
    if not acesso_curadoria.liberado:
        return AcessoEnvio(liberado=False, motivo_bloqueio=acesso_curadoria.motivo_bloqueio)
    if slate_status != "aprovado":
        return AcessoEnvio(liberado=False, motivo_bloqueio="Slate de hoje ainda nao foi aprovado.")
    return AcessoEnvio(liberado=True, motivo_bloqueio=None)


@dataclass(frozen=True)
class ParadaSessao:
    user_id: str
    nome: str | None
    telefone_e164: str
    posicao: int  # 1-based, posicao no dia inteiro (ordem_da_sessao) - nunca na fila restante.
    mensagens: tuple[MensagemNaFila, ...] = field(default_factory=tuple)


def montar_paradas(
    universo_user_ids: Sequence[str], fila: Sequence[MensagemNaFila], data: date
) -> tuple[ParadaSessao, ...]:
    # O nucleo do achado central da Fase 5d-D: `universo_user_ids` tem
    # que ser ESTAVEL durante a sessao inteira (D19 - todo mundo que teve
    # mensagem gerada hoje, nao so quem ainda esta pendente). Se fosse
    # recalculado sobre a fila restante, `n` diminuiria a cada mensagem
    # resolvida e ordem_da_sessao trocaria de offset, reembaralhando quem
    # ja era a proxima parada. Aqui a ordem e calculada uma vez sobre o
    # universo estavel; so o AGRUPAMENTO usa a fila (que sim, encolhe).
    ordem = ordem_da_sessao(universo_user_ids, data)
    posicao_por_user = {user_id: i + 1 for i, user_id in enumerate(ordem)}

    por_usuario: dict[str, list[MensagemNaFila]] = {}
    for msg in fila:
        por_usuario.setdefault(msg.user_id, []).append(msg)

    # Defensivo: user_id na fila mas fora do universo (nao deveria
    # acontecer - universo_da_sessao e superconjunto por design - mas a
    # fila e o dado real e a ordem e so apresentacao, entao nunca lancar
    # excecao aqui) entra no fim, em ordem estavel.
    proxima_posicao_extra = len(ordem) + 1
    paradas = []
    for user_id, mensagens in por_usuario.items():
        if user_id in posicao_por_user:
            posicao = posicao_por_user[user_id]
        else:
            posicao = proxima_posicao_extra
            proxima_posicao_extra += 1
        primeira = mensagens[0]
        paradas.append(
            ParadaSessao(user_id=user_id, nome=primeira.nome, telefone_e164=primeira.telefone_e164, posicao=posicao, mensagens=tuple(mensagens))
        )

    return tuple(sorted(paradas, key=lambda p: p.posicao))


def parada_atual(paradas: Sequence[ParadaSessao]) -> ParadaSessao | None:
    # Deliberadamente trivial - o nome documenta a regra ("a parada atual
    # e a primeira parada com mensagem pronta na ordem do dia"), nunca um
    # cursor/ponteiro persistido. Reentrancia vem de recalcular isso a
    # cada requisicao a partir do estado real de messages.
    return paradas[0] if paradas else None


@dataclass(frozen=True)
class ProgressoSessao:
    total: int
    concluidas: int
    restantes: int
    mensagens_pendentes: int
    duracao_estimada: timedelta


def progresso(paradas: Sequence[ParadaSessao], universo_user_ids: Sequence[str], intervalo_segundos: int) -> ProgressoSessao:
    total = len(universo_user_ids)
    restantes = len(paradas)
    mensagens_pendentes = sum(len(p.mensagens) for p in paradas)
    return ProgressoSessao(
        total=total, concluidas=total - restantes, restantes=restantes,
        mensagens_pendentes=mensagens_pendentes, duracao_estimada=timedelta(seconds=restantes * intervalo_segundos),
    )


@dataclass(frozen=True)
class AcessoSessao:
    pode_iniciar: bool
    motivo: str | None


def avaliar_acesso_sessao(
    acesso_envio: AcessoEnvio, sessao_aberta: SessaoEnvio | None, paradas: Sequence[ParadaSessao]
) -> AcessoSessao:
    if not acesso_envio.liberado:
        return AcessoSessao(pode_iniciar=False, motivo=acesso_envio.motivo_bloqueio)
    if sessao_aberta is not None:
        return AcessoSessao(pode_iniciar=False, motivo="Ja existe uma sessao de envio aberta hoje.")
    if not paradas:
        return AcessoSessao(pode_iniciar=False, motivo="Nenhuma mensagem pronta para enviar hoje.")
    return AcessoSessao(pode_iniciar=True, motivo=None)


@dataclass(frozen=True)
class ResumoSessao:
    enviadas: int
    expiradas: int
    prontas_restantes: int
    puladas: tuple[tuple[str | None, str, str], ...] = field(default_factory=tuple)


def montar_resumo(enviadas: int, expiradas: int, prontas_restantes: int, puladas: Sequence[tuple[str | None, str, str]]) -> ResumoSessao:
    return ResumoSessao(enviadas=enviadas, expiradas=expiradas, prontas_restantes=prontas_restantes, puladas=tuple(puladas))
