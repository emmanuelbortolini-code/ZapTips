from datetime import datetime, timezone

from app.sda import (
    SdaCard,
    limpar_url,
    montar_texto_bruto,
    normalizar_repeticoes_adjacentes,
    parse_listing_page,
)


def _pagina(*artigos: str) -> str:
    return f"<html><body>{''.join(artigos)}</body></html>"


def _card(
    url="https://www.sites-de-apostas.net/prognosticos-noticias/palpite-x",
    titulo="Palpite Cruzeiro x Mirassol – Brasileirão – 09/08/2026",
    status_label="Começa em",
    tipster="Paulo Matuck",
    tipster_url="https://www.sites-de-apostas.net/autores/paulo-matuck",
    data="09.08.2026",
    hora="11:00",
    oneliner="Ambos os times marcam,  - sim - odds 1.90",
    casa="Betano",
) -> str:
    tipster_html = ""
    if tipster:
        href = f' href="{tipster_url}"' if tipster_url else ""
        tipster_html = f'<a class="tip-preview__author-url"{href}><span class="tipster-name">{tipster}</span></a>'

    data_html = f'<span class="tip-preview__event-date">{data}</span>' if data else ""
    hora_html = f'<span class="tip-preview-event-time-hour">{hora}</span>' if hora else ""
    oneliner_html = (
        f'<div class="tip-preview__cta"><span class="tip-preview__cta-oneliner">{oneliner}</span>'
        f'<img alt="{casa}"></div>'
        if oneliner
        else ""
    )

    return f"""
    <article class="tip-preview-item">
      {tipster_html}
      <a class="tip-preview__link" href="{url}">{titulo}</a>
      <p>{status_label} |</p>
      {data_html}
      {hora_html}
      {oneliner_html}
    </article>
    """


def test_parse_card_ativo_extrai_todos_os_campos():
    html = _pagina(_card())

    cards = parse_listing_page(html)

    assert len(cards) == 1
    card = cards[0]
    assert card.status == "ativo"
    assert card.url == "https://www.sites-de-apostas.net/prognosticos-noticias/palpite-x"
    assert card.titulo == "Palpite Cruzeiro x Mirassol – Brasileirão – 09/08/2026"
    assert card.tipster == "Paulo Matuck"
    assert card.tipster_url == "https://www.sites-de-apostas.net/autores/paulo-matuck"
    assert card.data == "09.08.2026"
    assert card.hora == "11:00"
    assert card.oneliner == "Ambos os times marcam, - sim - odds 1.90"
    assert card.casa == "Betano"


def test_parse_card_encerrado_identifica_pelo_rotulo_nao_pela_posicao():
    html = _pagina(_card(status_label="Terminado"))

    cards = parse_listing_page(html)

    assert cards[0].status == "encerrado"


def test_parse_card_sem_rotulo_conhecido_e_ignorado():
    html = _pagina(_card(status_label="Algo desconhecido"))

    assert parse_listing_page(html) == []


def test_parse_card_sem_link_e_ignorado():
    html = _pagina('<article class="tip-preview-item"><p>Começa em |</p></article>')

    assert parse_listing_page(html) == []


def test_parse_card_vazio_estilo_prosa_sem_derrubar():
    # Achado do documento: alguns autores publicam so prosa, sem
    # tipster/data/hora/oneliner preenchidos no card.
    html = _pagina(_card(tipster=None, data=None, hora=None, oneliner=None, casa=None))

    cards = parse_listing_page(html)

    assert len(cards) == 1
    card = cards[0]
    assert card.tipster is None
    assert card.data is None
    assert card.hora is None
    assert card.oneliner is None
    assert card.publicado_em is None


def test_parse_card_calcula_publicado_em_em_utc_a_partir_de_brt():
    html = _pagina(_card(data="09.08.2026", hora="11:00"))

    card = parse_listing_page(html)[0]

    # BRT = UTC-3, sem horario de verao.
    assert card.publicado_em == datetime(2026, 8, 9, 14, 0, tzinfo=timezone.utc)


def test_parse_card_com_data_mas_sem_hora_assume_meia_noite_brt():
    html = _pagina(_card(data="09.08.2026", hora=None))

    card = parse_listing_page(html)[0]

    assert card.publicado_em == datetime(2026, 8, 9, 3, 0, tzinfo=timezone.utc)


def test_parse_card_com_data_malformada_publicado_em_fica_none():
    html = _pagina(_card(data="nao-e-uma-data", hora="11:00"))

    card = parse_listing_page(html)[0]

    assert card.data == "nao-e-uma-data"
    assert card.publicado_em is None


def test_parse_card_com_hora_malformada_assume_meia_noite():
    html = _pagina(_card(data="09.08.2026", hora="nao-e-hora"))

    card = parse_listing_page(html)[0]

    assert card.publicado_em == datetime(2026, 8, 9, 3, 0, tzinfo=timezone.utc)


def test_parse_card_com_data_impossivel_publicado_em_fica_none():
    html = _pagina(_card(data="32.13.2026", hora="11:00"))

    card = parse_listing_page(html)[0]

    assert card.publicado_em is None


def test_parse_multiplos_cards_um_ativo_um_encerrado():
    html = _pagina(
        _card(url="https://x.com/a", status_label="Começa em"),
        _card(url="https://x.com/b", status_label="Terminado"),
    )

    cards = parse_listing_page(html)

    assert [(c.url, c.status) for c in cards] == [
        ("https://x.com/a", "ativo"),
        ("https://x.com/b", "encerrado"),
    ]


def test_limpar_url_remove_query_string():
    suja = "https://www.sites-de-apostas.net/prognosticos-noticias/palpite-x?utm_campaign=palpite"

    assert limpar_url(suja) == "https://www.sites-de-apostas.net/prognosticos-noticias/palpite-x"


def test_limpar_url_sem_query_string_fica_igual():
    limpa = "https://www.sites-de-apostas.net/prognosticos-noticias/palpite-x"

    assert limpar_url(limpa) == limpa


def test_normalizar_repeticoes_com_espaco():
    assert normalizar_repeticoes_adjacentes("odds 1.57 1.57") == "odds 1.57"


def test_normalizar_repeticoes_concatenada_sem_espaco():
    assert normalizar_repeticoes_adjacentes("SuperbetSuperbet") == "Superbet"


def test_normalizar_repeticoes_nao_mexe_em_texto_sem_duplicacao():
    assert normalizar_repeticoes_adjacentes("Mais 2 gols, - odds 1.75") == "Mais 2 gols, - odds 1.75"


def test_normalizar_repeticoes_string_vazia():
    assert normalizar_repeticoes_adjacentes("") == ""


def test_montar_texto_bruto_combina_titulo_tipster_oneliner_casa():
    card = SdaCard(
        url="https://x.com/a", status="ativo", titulo="Palpite A x B – Liga – 09/08/2026",
        tipster="Fulano", tipster_url=None, data="09.08.2026", hora="11:00",
        oneliner="Mais 2.5 gols, - odds 1.82", casa="Superbet", publicado_em=None,
    )

    texto = montar_texto_bruto(card)

    assert "Palpite A x B" in texto
    assert "Fulano" in texto
    assert "Mais 2.5 gols" in texto
    assert "Superbet" in texto


def test_montar_texto_bruto_card_vazio_so_tem_titulo():
    card = SdaCard(
        url="https://x.com/a", status="ativo", titulo="Palpite A x B – Liga – 09/08/2026",
        tipster=None, tipster_url=None, data=None, hora=None, oneliner=None, casa=None,
        publicado_em=None,
    )

    assert montar_texto_bruto(card) == "Palpite A x B – Liga – 09/08/2026"
