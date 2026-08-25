from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Vazio ate o .env real ser preenchido com a connection string do Supabase.
    # Scripts que nao tocam o banco (ex.: sonda_espn.py) funcionam sem ela;
    # migrate.py falha com erro claro de conexao se ficar vazia.
    database_url: str = ""

    oddspapi_api_key: str = ""
    oddspapi_base_url: str = "https://api.oddspapi.io/v4"

    espn_base_url: str = "https://site.api.espn.com/apis/site/v2/sports/soccer"

    anthropic_api_key: str = ""

    # Piso e margem: ver Fase 4 do prompt-claude-code-palpites.md.
    odd_minima_absoluta: float = 1.40
    margem_pct: float = 0.04
    slate_max_picks: int = 5

    banca_inicial_padrao: float = 1000
    stake_pct_padrao: float = 0.02
    stake_modo_padrao: str = "fixo"

    horario_envio: str = "09:00"
    intervalo_envio_segundos: int = 30
    antecedencia_minima_horas: int = 2
    queue_enabled: bool = True
    max_assinantes_ativos: int = 50

    # Fase 5c: identifica quem aprovou o slate (daily_slates.curado_por,
    # texto livre desde a Fase 4) - so um operador hoje, mas o campo
    # existe pra quando isso deixar de ser verdade.
    operador_nome: str = "console"

    # Fase 5d (pendencia D5 da Fase 5c): alerta - nunca bloqueio - quando
    # a odd citada pela fonte diverge muito da odd de referencia
    # calculada. Nao esta na lista de bloqueios de aprovacao da spec.
    divergencia_odd_alerta_pct: float = 0.10

    # "Proximo passo" #8 do documento original: alerta quando o volume
    # de nao_liquidavel passar de 15% dos palpites de uma fonte.
    nao_liquidavel_alerta_pct: float = 0.15

    # Obrigatorio em toda mensagem enviada (Fase 4, "Template") - nunca
    # opcional. Rascunho, ajustavel sem tocar codigo (so o texto muda).
    rodape_legal: str = (
        "🔞 Aposte com responsabilidade. Conteudo para maiores de 18 anos.\n"
        "Se precisar de ajuda, procure o Jogadores Anonimos.\n"
        "Para sair desta lista, responda SAIR."
    )


def get_settings() -> Settings:
    return Settings()
