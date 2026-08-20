from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

from app.console.queries import EstadoRun
from app.console.rules import (
    AcessoEnvio,
    LIMITE_AVISO_CARACTERES,
    avaliar_acesso_envio,
    excede_limite_caracteres,
    expira_em_horas,
    montar_link_whatsapp,
)
from tests.test_console_rules_acesso import _estado, _etapa


def test_montar_link_whatsapp_remove_o_mais_do_telefone():
    link = montar_link_whatsapp("+5511999991111", "ola")
    assert link.startswith("https://wa.me/5511999991111?text=")
    assert "+" not in link.split("?text=")[0].split("wa.me/")[1]


def test_montar_link_whatsapp_url_encoda_acento_emoji_e_quebra_de_linha():
    corpo = "Não aposte 🔞\nabaixo de 1.82"
    link = montar_link_whatsapp("+5511999991111", corpo)

    texto_codificado = link.split("?text=")[1]
    assert "%0A" in texto_codificado  # quebra de linha
    assert unquote(texto_codificado) == corpo


def test_montar_link_whatsapp_encoda_caracteres_especiais_de_url():
    corpo = "50% & mais #hashtag + extra"
    link = montar_link_whatsapp("+5511999991111", corpo)

    texto_codificado = link.split("?text=")[1]
    assert unquote(texto_codificado) == corpo
    # safe='' garante que ate '/' e '&' do corpo sao escapados, nao
    # tratados como parte da estrutura da URL
    assert "&" not in texto_codificado or "%26" in link


def test_excede_limite_caracteres_false_dentro_do_limite():
    assert excede_limite_caracteres("x" * LIMITE_AVISO_CARACTERES) is False


def test_excede_limite_caracteres_true_acima_do_limite():
    assert excede_limite_caracteres("x" * (LIMITE_AVISO_CARACTERES + 1)) is True


def test_expira_em_horas_true_quando_dentro_da_janela():
    agora = datetime(2026, 8, 11, 10, 0, tzinfo=timezone.utc)
    kickoff = agora + timedelta(hours=1)
    assert expira_em_horas(kickoff, agora, horas=2) is True


def test_expira_em_horas_false_quando_fora_da_janela():
    agora = datetime(2026, 8, 11, 10, 0, tzinfo=timezone.utc)
    kickoff = agora + timedelta(hours=5)
    assert expira_em_horas(kickoff, agora, horas=2) is False


def test_avaliar_acesso_envio_bloqueado_quando_curadoria_bloqueada():
    estado = EstadoRun(existe=False, status=None, etapa_atual=None, etapas=())

    acesso = avaliar_acesso_envio(estado, slate_status="aprovado")

    assert acesso.liberado is False
    assert "nao rodou hoje" in acesso.motivo_bloqueio


def test_avaliar_acesso_envio_bloqueado_quando_slate_nao_aprovado():
    estado = _estado("pronto", "slate", [_etapa("fixtures", "ok"), _etapa("slate", "ok")])

    acesso = avaliar_acesso_envio(estado, slate_status="rascunho")

    assert acesso.liberado is False
    assert "aprovado" in acesso.motivo_bloqueio


def test_avaliar_acesso_envio_liberado_quando_aprovado():
    estado = _estado("pronto", "slate", [_etapa("fixtures", "ok"), _etapa("slate", "ok")])

    acesso = avaliar_acesso_envio(estado, slate_status="aprovado")

    assert acesso == AcessoEnvio(liberado=True, motivo_bloqueio=None)
