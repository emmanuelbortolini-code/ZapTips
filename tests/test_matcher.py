import app.matcher as matcher_module
from app.matcher import TeamAlias, match_team_name, normalize_team_name


def test_normalize_lowercases_and_strips_accents():
    assert normalize_team_name("Atlético Mineiro") == "atletico mineiro"


def test_normalize_removes_dash_state_suffix():
    assert normalize_team_name("Cruzeiro-MG") == "cruzeiro"


def test_normalize_removes_slash_state_suffix():
    assert normalize_team_name("Palmeiras/SP") == "palmeiras"


def test_normalize_removes_club_type_token_as_suffix():
    assert normalize_team_name("Botafogo FC") == "botafogo"


def test_normalize_removes_club_type_token_as_prefix():
    assert normalize_team_name("SC Corinthians Paulista") == "corinthians paulista"


def test_normalize_collapses_whitespace():
    assert normalize_team_name("  Flamengo   Rio  ") == "flamengo rio"


def test_normalize_does_not_strip_letters_that_only_contain_club_token():
    # "ac" nao deve ser removido de dentro de "bragantino" nem similar;
    # so remove o token "ac" isolado, delimitado por palavra.
    assert normalize_team_name("Bragantino") == "bragantino"


def test_normalize_remove_sufixo_estado_mesmo_com_token_de_clube_depois():
    assert normalize_team_name("Botafogo-RJ FC") == "botafogo"


def test_normalize_remove_token_de_clube_mesmo_antes_do_sufixo_estado():
    assert normalize_team_name("Botafogo FC-RJ") == "botafogo"


def test_match_exact_hit_returns_status_exato_com_score_maximo():
    aliases = [TeamAlias(team_id="t1", alias_normalizado="flamengo")]

    resultado = match_team_name("Flamengo", aliases)

    assert resultado.status == "exato"
    assert resultado.team_id == "t1"
    assert resultado.score == 100.0


def test_match_fuzzy_hit_acima_do_threshold_retorna_status_fuzzy():
    aliases = [TeamAlias(team_id="t1", alias_normalizado="gremio")]

    resultado = match_team_name("Gremio FBPA", aliases)

    assert resultado.status == "fuzzy"
    assert resultado.team_id == "t1"
    assert resultado.score >= 85.0


def test_match_abaixo_do_threshold_vai_para_revisao_manual():
    aliases = [TeamAlias(team_id="t1", alias_normalizado="flamengo")]

    resultado = match_team_name("Vasco da Gama", aliases)

    assert resultado.status == "revisao_manual"
    assert resultado.team_id is None


def test_match_sem_aliases_cadastrados_vai_para_revisao_manual():
    resultado = match_team_name("Flamengo", [])

    assert resultado.status == "revisao_manual"
    assert resultado.team_id is None


def test_match_ambiguo_entre_dois_times_vai_para_revisao_manual():
    # Cenario real: America-MG e America-RN normalizam para o mesmo alias
    # depois que o sufixo de estado e removido. Sem contexto de partida
    # (janela de kickoff), nao da para desempatar - fica para revisao humana.
    aliases = [
        TeamAlias(team_id="america-mg", alias_normalizado="america"),
        TeamAlias(team_id="america-rn", alias_normalizado="america"),
    ]

    resultado = match_team_name("America", aliases)

    assert resultado.status == "revisao_manual"
    assert resultado.team_id is None
    assert resultado.score == 100.0


def test_match_escolhe_melhor_score_entre_varios_aliases_nao_ambiguos():
    aliases = [
        TeamAlias(team_id="t1", alias_normalizado="flamengo"),
        TeamAlias(team_id="t2", alias_normalizado="fluminense"),
    ]

    resultado = match_team_name("Flamengo", aliases)

    assert resultado.status == "exato"
    assert resultado.team_id == "t1"


def test_match_desempate_dentro_do_mesmo_time_prefere_alias_exato_independente_da_ordem():
    # "Botafogo" bate 100 tanto contra "botafogo" (exato) quanto contra
    # "botafogo rj" (fuzzy, subconjunto de token). Os dois aliases sao do
    # mesmo time, entao nao e ambiguidade - mas o resultado nao pode
    # depender da ordem em que o repositorio devolveu as linhas.
    alias_exato = TeamAlias(team_id="t1", alias_normalizado="botafogo")
    alias_fuzzy = TeamAlias(team_id="t1", alias_normalizado="botafogo rj")

    resultado_a = match_team_name("Botafogo", [alias_fuzzy, alias_exato])
    resultado_b = match_team_name("Botafogo", [alias_exato, alias_fuzzy])

    assert resultado_a.status == resultado_b.status == "exato"
    assert resultado_a.alias_correspondente == resultado_b.alias_correspondente == "botafogo"


def test_match_no_limiar_exato_e_aceito_como_fuzzy(monkeypatch):
    monkeypatch.setattr(matcher_module.fuzz, "token_set_ratio", lambda a, b: 85.0)
    aliases = [TeamAlias(team_id="t1", alias_normalizado="time base")]

    resultado = match_team_name("Time Alvo", aliases)

    assert resultado.status == "fuzzy"
    assert resultado.score == 85.0


def test_match_logo_abaixo_do_limiar_vai_para_revisao_manual(monkeypatch):
    monkeypatch.setattr(matcher_module.fuzz, "token_set_ratio", lambda a, b: 84.9)
    aliases = [TeamAlias(team_id="t1", alias_normalizado="time base")]

    resultado = match_team_name("Time Alvo", aliases)

    assert resultado.status == "revisao_manual"
    assert resultado.team_id is None


def test_match_nao_confia_em_fuzzy_contra_abreviacao_curta_nao_relacionada():
    # Achado real rodando contra os aliases seedados da ESPN: "Galo"
    # (apelido do Atletico-MG, que a ESPN nao cadastra) batia fuzzy contra
    # "GAL", a abreviacao do Galatasaray, com score 85.71 - coincidencia de
    # caracteres em strings curtas, sem nenhuma relacao real entre os times.
    aliases = [TeamAlias(team_id="galatasaray", alias_normalizado="gal")]

    resultado = match_team_name("Galo", aliases)

    assert resultado.status == "revisao_manual"
    assert resultado.team_id is None


def test_match_ainda_aceita_exato_mesmo_com_alias_curto():
    aliases = [TeamAlias(team_id="t1", alias_normalizado="gal")]

    resultado = match_team_name("GAL", aliases)

    assert resultado.status == "exato"
    assert resultado.team_id == "t1"
