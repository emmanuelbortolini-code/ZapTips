from app.apwin import PAGINAS, ApwinEntrada, montar_texto_bruto, parse_market_page, url_pagina


def _linha(
    kickoff="25/08/2026 20:45",
    liga="EFL Cup",
    home="Stevenage",
    away="Reading",
    percentual="100%",
    match_url="https://www.apwin.com/match/reading-stevenage/UsYUI/",
    com_view_match=True,
):
    view_match_html = f'<a href="{match_url}">View Match</a>' if com_view_match else ""
    return f"""
    <div class="columns is-variable is-4 apw-border-top m-0 is-hover stats-item is-align-items-center">
        <div class="column is-size-7">
            <p>{kickoff}</p>
            <div class="is-flex is-align-items-center mt-2">
                <figure class="image is-16x16 mr-2"><img alt="liga country flag"></figure>
                <p>{liga}</p>
            </div>
        </div>
        <a href="https://www.apwin.com/team/stevenage-fc/" class="column is-3">
            <p class="mr-2 home">{home}</p>
        </a>
        <div class="column is-narrow has-text-centered">v.s</div>
        <a href="https://www.apwin.com/team/reading-fc/" class="column is-3">
            <p class="ml-2 away">{away}</p>
        </a>
        <div class="column is-size-7 has-text-right">
            <div class="is-flex is-justify-content-end">
                <p class="stats-val has-background-success p-1 mr-2">{percentual}</p>
                {view_match_html}
            </div>
        </div>
    </div>
    """


def _pagina(*linhas):
    return f"""
    <html><body>
    <div id="stats-table">
        <p class="has-text-right has-text-weight-bold p-4 is-size-7">BTTS Probability (%)</p>
        {"".join(linhas)}
    </div>
    </body></html>
    """


def test_parse_extrai_todos_os_campos():
    html = _pagina(_linha())

    entradas = parse_market_page(html)

    assert len(entradas) == 1
    e = entradas[0]
    assert e.match_id == "UsYUI"
    assert e.match_url == "https://www.apwin.com/match/reading-stevenage/UsYUI/"
    assert e.liga_texto == "EFL Cup"
    assert e.time_casa_texto == "Stevenage"
    assert e.time_fora_texto == "Reading"
    assert e.percentual == 100.0
    assert e.kickoff_brt_texto == "25/08/2026 20:45"


def test_parse_calcula_kickoff_utc_a_partir_de_brt():
    html = _pagina(_linha(kickoff="25/08/2026 20:45"))
    entradas = parse_market_page(html)
    # BRT = UTC-3 -> 20:45 BRT = 23:45 UTC
    assert entradas[0].kickoff_utc.hour == 23
    assert entradas[0].kickoff_utc.minute == 45


def test_parse_kickoff_malformado_fica_none_sem_derrubar_a_linha():
    html = _pagina(_linha(kickoff="nao-e-data"))
    entradas = parse_market_page(html)
    assert len(entradas) == 1
    assert entradas[0].kickoff_utc is None


def test_parse_multiplas_linhas():
    html = _pagina(
        _linha(home="Stevenage", away="Reading", match_url="https://www.apwin.com/match/a/id1/"),
        _linha(home="Blackpool", away="Lincoln City", match_url="https://www.apwin.com/match/b/id2/"),
    )
    entradas = parse_market_page(html)
    assert len(entradas) == 2
    assert {e.match_id for e in entradas} == {"id1", "id2"}


def test_parse_linha_sem_view_match_e_ignorada_sem_derrubar_as_outras():
    html = _pagina(
        _linha(com_view_match=False, home="SemLink"),
        _linha(home="ComLink", match_url="https://www.apwin.com/match/x/id2/"),
    )
    entradas = parse_market_page(html)
    assert len(entradas) == 1
    assert entradas[0].time_casa_texto == "ComLink"


def test_parse_percentual_nao_numerico_e_ignorado():
    html = _pagina(_linha(percentual="N/A"))
    assert parse_market_page(html) == []


def test_parse_sem_tabela_retorna_vazio():
    assert parse_market_page("<html><body>nada aqui</body></html>") == []


def test_parse_lista_vazia_retorna_vazio():
    assert parse_market_page(_pagina()) == []


def test_url_pagina_raiz_sem_slug():
    pagina = next(p for p in PAGINAS if p.mercado == "ambas_marcam")
    assert url_pagina(pagina) == "https://www.apwin.com/decreasing-stats/"


def test_url_pagina_com_slug():
    pagina = next(p for p in PAGINAS if p.mercado == "over_under")
    assert url_pagina(pagina) == "https://www.apwin.com/decreasing-stats/over-goals/"


def test_paginas_cobre_os_4_mercados_do_escopo():
    assert {p.mercado for p in PAGINAS} == {"ambas_marcam", "over_under", "escanteios", "cartoes"}


def test_montar_texto_bruto_inclui_mercado_selecao_e_linha():
    entrada = ApwinEntrada(
        match_id="id1", match_url="https://www.apwin.com/match/a/id1/",
        kickoff_brt_texto="25/08/2026 20:45", kickoff_utc=None,
        liga_texto="EFL Cup", time_casa_texto="Stevenage", time_fora_texto="Reading",
        percentual=100.0,
    )
    pagina = next(p for p in PAGINAS if p.mercado == "over_under")

    texto = montar_texto_bruto(entrada, pagina)

    assert "Stevenage" in texto and "Reading" in texto
    assert "over_under" in texto
    assert "2.5" in texto
    assert "100.0%" in texto
