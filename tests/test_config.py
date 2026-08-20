from app.config import get_settings


def test_settings_carrega_com_defaults_de_negocio():
    settings = get_settings()

    assert settings.odd_minima_absoluta == 1.40
    assert settings.stake_modo_padrao == "fixo"
    assert settings.slate_max_picks == 5
    assert settings.max_assinantes_ativos == 50


def test_settings_aceita_database_url_vazia_sem_quebrar():
    # migrate.py falha ao tentar conectar com string vazia; o objetivo aqui
    # e so garantir que scripts sem acesso a banco (ex.: sonda_espn.py)
    # conseguem instanciar Settings antes do .env real existir.
    settings = get_settings()

    assert isinstance(settings.database_url, str)
