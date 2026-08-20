from datetime import datetime, timezone

from app.eagle_predict import is_betting_tip_post, parse_channel_page

CANAL = "eaglepredict"


def _pagina(*blocos: str) -> str:
    return f"<html><body><div class='tgme_channel_history'>{''.join(blocos)}</div></body></html>"


def _bloco_normal(msg_id: str, dt: str, texto: str) -> str:
    return f"""
    <div class="tgme_widget_message" data-post="{CANAL}/{msg_id}">
      <div class="tgme_widget_message_bubble">
        <div class="tgme_widget_message_text js-message_text" dir="auto">{texto}</div>
        <div class="tgme_widget_message_footer">
          <time class="time" datetime="{dt}">00:00</time>
        </div>
      </div>
    </div>
    """


def _bloco_resposta(msg_id: str, dt: str, texto_real: str, texto_citado: str) -> str:
    # Reproduz a estrutura real: DOIS blocos com a mesma classe base
    # "tgme_widget_message_text" quando a mensagem e uma resposta - o da
    # citacao (truncada, irrelevante) vem ANTES do texto real no DOM.
    return f"""
    <div class="tgme_widget_message" data-post="{CANAL}/{msg_id}">
      <div class="tgme_widget_message_bubble">
        <a class="tgme_widget_message_reply">
          <div class="tgme_widget_message_text js-message_reply_text" dir="auto">{texto_citado}</div>
        </a>
        <div class="tgme_widget_message_text js-message_text" dir="auto">{texto_real}</div>
        <div class="tgme_widget_message_footer">
          <time class="time" datetime="{dt}">00:00</time>
        </div>
      </div>
    </div>
    """


def test_parse_extrai_id_data_e_texto_de_post_normal():
    html = _pagina(_bloco_normal("100", "2026-08-03T04:40:06+00:00", "Odds @1.25 on BETANO"))

    posts = parse_channel_page(html, CANAL)

    assert len(posts) == 1
    assert posts[0].message_id == "100"
    assert posts[0].url == "https://t.me/eaglepredict/100"
    assert posts[0].published_at == datetime(2026, 8, 3, 4, 40, 6, tzinfo=timezone.utc)
    assert posts[0].texto == "Odds @1.25 on BETANO"


def test_parse_post_resposta_pega_o_texto_real_nao_a_citacao_truncada():
    # Achado real rodando contra o canal de verdade: um seletor generico
    # ".tgme_widget_message_text" pega o bloco de CITACAO truncada (da
    # mensagem respondida) em vez do texto de verdade, quando a mensagem
    # e uma resposta. Isso fazia uma mensagem tipo "Congrats to all who
    # won!" (sem odd nenhuma) parecer, incorretamente, um post de tip -
    # porque a citacao truncada continha "Odds @" da mensagem antiga.
    html = _pagina(
        _bloco_resposta(
            "101",
            "2026-08-03T05:00:00+00:00",
            texto_real="Congrats to all who won!",
            texto_citado="Odds @1.15 on BETANO",
        )
    )

    posts = parse_channel_page(html, CANAL)

    assert len(posts) == 1
    assert posts[0].texto == "Congrats to all who won!"
    assert not is_betting_tip_post(posts[0].texto)


def test_parse_ignora_bloco_sem_data_post():
    html = _pagina('<div class="tgme_widget_message"></div>')

    assert parse_channel_page(html, CANAL) == []


def test_parse_ignora_bloco_sem_texto_ex_midia_sem_legenda():
    html = f"""
    <div class="tgme_widget_message" data-post="{CANAL}/102">
      <time class="time" datetime="2026-08-03T05:00:00+00:00">00:00</time>
    </div>
    """

    assert parse_channel_page(_pagina(html), CANAL) == []


def test_parse_ignora_bloco_com_datetime_vazio():
    html = f"""
    <div class="tgme_widget_message" data-post="{CANAL}/104">
      <div class="tgme_widget_message_text js-message_text">Odds @1.5 on BETANO</div>
      <time class="time" datetime="">00:00</time>
    </div>
    """

    assert parse_channel_page(_pagina(html), CANAL) == []


def test_parse_ignora_bloco_com_datetime_malformado():
    html = f"""
    <div class="tgme_widget_message" data-post="{CANAL}/105">
      <div class="tgme_widget_message_text js-message_text">Odds @1.5 on BETANO</div>
      <time class="time" datetime="nao-e-uma-data">00:00</time>
    </div>
    """

    assert parse_channel_page(_pagina(html), CANAL) == []


def test_parse_ignora_bloco_sem_horario():
    html = f"""
    <div class="tgme_widget_message" data-post="{CANAL}/103">
      <div class="tgme_widget_message_text js-message_text">Odds @1.5 on BETANO</div>
    </div>
    """

    assert parse_channel_page(_pagina(html), CANAL) == []


def test_parse_multiplos_posts_na_mesma_pagina():
    html = _pagina(
        _bloco_normal("200", "2026-08-01T00:00:00+00:00", "post 1"),
        _bloco_normal("201", "2026-08-02T00:00:00+00:00", "post 2"),
    )

    posts = parse_channel_page(html, CANAL)

    assert [p.message_id for p in posts] == ["200", "201"]


def test_is_betting_tip_post_marcador_real_odds_arroba():
    assert is_betting_tip_post("blah blah Odds @1.25 on BETANO") is True


def test_is_betting_tip_post_marcador_estilizado_do_documento_nao_existe_no_canal_real():
    # O documento original citava "Football Betting Tip" como marcador,
    # mas o canal real usa fonte unicode estilizada que varia
    # ("𝗙𝗼𝗼𝘁𝗯𝗮𝗹𝗹 𝗧𝗶𝗽 𝟮") - esse texto nunca aparece literalmente.
    assert is_betting_tip_post("Football Betting Tip") is False


def test_is_betting_tip_post_post_promocional_sem_odd():
    assert is_betting_tip_post("Get up to 50% bonus on your deposit!") is False
