-- Fase 0: schema fundacional.
-- Enums de status sao TEXT + CHECK, nao tipo ENUM nativo do Postgres:
-- adicionar um valor novo (ex.: um status de pipeline a mais) vira um
-- ALTER TABLE ... DROP/ADD CONSTRAINT, sem o ALTER TYPE que trava lock
-- mais agressivo e nao roda dentro de transacao em versoes antigas do PG.
-- Tabelas na ordem de dependencia de FK, nao na ordem em que aparecem no
-- documento de especificacao.

create table teams (
    id uuid primary key default gen_random_uuid(),
    nome_canonico text not null,
    pais text,
    espn_team_id text unique,
    criado_em timestamptz not null default now()
);

create table team_aliases (
    id uuid primary key default gen_random_uuid(),
    team_id uuid not null references teams(id),
    alias text not null,
    alias_normalizado text not null,
    fonte text,
    confianca real
);

create index idx_team_aliases_normalizado on team_aliases(alias_normalizado);

create table casas (
    id uuid primary key default gen_random_uuid(),
    nome text not null,
    slug_oddspapi text,
    aliases text[] not null default '{}',
    licenciada_br boolean not null default false,
    ativa boolean not null default true
);

create table fixtures (
    id uuid primary key default gen_random_uuid(),
    espn_event_id text not null unique,
    oddspapi_fixture_id text,
    liga text not null,
    temporada text,
    rodada text,
    home_team_id uuid references teams(id),
    away_team_id uuid references teams(id),
    kickoff_utc timestamptz not null,
    status text not null default 'agendada'
        check (status in ('agendada', 'ao_vivo', 'encerrada', 'adiada', 'cancelada')),
    estadio text,
    placar_casa int,
    placar_fora int,
    placar_ht_casa int,
    placar_ht_fora int,
    encerrado_em timestamptz,
    atualizado_em timestamptz not null default now()
);

create index idx_fixtures_kickoff_status on fixtures(kickoff_utc, status);

create table fixture_stats (
    id uuid primary key default gen_random_uuid(),
    fixture_id uuid not null references fixtures(id),
    time_id uuid not null references teams(id),
    escanteios int,
    cartoes_amarelos int,
    cartoes_vermelhos int,
    finalizacoes int,
    posse numeric(5, 2),
    origem text,
    coletado_em timestamptz not null default now()
);

create table broadcasts (
    id uuid primary key default gen_random_uuid(),
    fixture_id uuid not null references fixtures(id),
    canal text,
    pais text,
    tipo text check (tipo in ('tv_aberta', 'tv_fechada', 'streaming')),
    origem text not null check (origem in ('espn', 'manual'))
);

-- Preenchida na mao pelo PM. Fallback primario para o Brasil enquanto a
-- sonda da Fase 1a nao confirmar se `broadcasts` cobre bem o pais.
create table broadcast_rules (
    id uuid primary key default gen_random_uuid(),
    liga text not null,
    dia_semana int check (dia_semana between 0 and 6),
    canais text[] not null default '{}',
    observacao text
);

create table odds_referencia (
    id uuid primary key default gen_random_uuid(),
    fixture_id uuid not null references fixtures(id),
    casa_id uuid not null references casas(id),
    mercado text not null,
    selecao text not null,
    linha numeric(5, 2),
    valor numeric(6, 3) not null,
    origem text not null check (origem in ('oddspapi', 'manual')),
    capturada_em timestamptz not null default now()
);

create table league_map (
    id uuid primary key default gen_random_uuid(),
    espn_league_code text not null unique,
    oddspapi_tournament_id text,
    nome text,
    ativa boolean not null default true
);

create table pipeline_runs (
    id uuid primary key default gen_random_uuid(),
    data_referencia date not null unique,
    status text not null default 'rodando'
        check (status in ('rodando', 'pronto', 'degradado', 'falhou')),
    etapa_atual text,
    iniciado_em timestamptz,
    finalizado_em timestamptz
);

create table pipeline_stages (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references pipeline_runs(id),
    etapa text not null,
    ordem int not null,
    status text not null default 'pendente'
        check (status in ('pendente', 'rodando', 'ok', 'degradado', 'falhou')),
    itens_ok int not null default 0,
    itens_erro int not null default 0,
    iniciado_em timestamptz,
    finalizado_em timestamptz,
    detalhe_json jsonb
);

create table api_quota (
    id uuid primary key default gen_random_uuid(),
    provedor text not null,
    mes_referencia text not null,
    chamadas int not null default 0,
    limite int,
    atualizado_em timestamptz not null default now(),
    unique (provedor, mes_referencia)
);

create table sources (
    id uuid primary key default gen_random_uuid(),
    nome text not null,
    tipo text not null check (tipo in ('site', 'telegram', 'manual', 'rss')),
    endpoint text,
    ativo boolean not null default true,
    -- Toda fonte nova nasce em quarentena. Sair e decisao manual do PM,
    -- nunca configuracao default (ver Fase 2, secao "Regras de quarentena").
    quarentena boolean not null default true,
    config_json jsonb,
    ultimo_sucesso_em timestamptz
);

create table raw_picks (
    id uuid primary key default gen_random_uuid(),
    source_id uuid not null references sources(id),
    texto_bruto text not null,
    url_origem text,
    autor text,
    publicado_em timestamptz,
    coletado_em timestamptz not null default now(),
    hash_conteudo text not null unique
);

create table picks (
    id uuid primary key default gen_random_uuid(),
    raw_pick_id uuid not null references raw_picks(id),
    -- bloco_id referencia pick_blocos, criada na Fase 2 (decomposicao de
    -- multiplas do Andy's Bet Club). Sem FK ainda porque a tabela nao existe.
    bloco_id uuid,
    fixture_id uuid references fixtures(id),
    mercado text,
    selecao text,
    linha numeric(5, 2),
    odd_citada numeric(6, 3),
    casa_id uuid references casas(id),
    odd_coletada_em timestamptz,
    odd_referencia numeric(6, 3),
    odd_referencia_origem text,
    odd_referencia_em timestamptz,
    odd_minima numeric(6, 3),
    confianca_tipster numeric(6, 3),
    stat_fonte numeric(6, 3),
    stat_fonte_tipo text,
    tipster text,
    status text not null default 'extraido'
        check (status in ('extraido', 'vinculado', 'revisao_manual', 'descartado', 'sem_odd')),
    score_matching numeric(5, 2),
    extraido_em timestamptz not null default now()
);

create table picks_orfaos (
    id uuid primary key default gen_random_uuid(),
    pick_id uuid not null references picks(id),
    motivo text,
    tentativas int not null default 0,
    ultima_tentativa_em timestamptz
);

create table users (
    id uuid primary key default gen_random_uuid(),
    nome text,
    telefone_e164 text not null unique,
    fuso_horario text not null default 'America/Sao_Paulo',
    idioma text not null default 'pt-BR',
    opt_in_em timestamptz,
    opt_in_origem text,
    opt_out_em timestamptz,
    status text not null default 'ativo'
        check (status in ('ativo', 'inadimplente', 'cancelado', 'pausado'))
);

create table subscriptions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references users(id),
    inicio date not null,
    fim date not null,
    valor numeric(10, 2),
    meio_pagamento text check (meio_pagamento in ('pix', 'transferencia', 'outro')),
    referencia_pagamento text,
    registrado_em timestamptz not null default now(),
    registrado_por text
);

create table user_preferences (
    user_id uuid primary key references users(id),
    ligas_excluidas text[] not null default '{}',
    mercados_excluidos text[] not null default '{}',
    odd_min numeric(6, 3),
    odd_max numeric(6, 3),
    max_msgs_dia int,
    horario_envio time
);

create table messages (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references users(id),
    fixture_id uuid not null references fixtures(id),
    pick_ids uuid[] not null default '{}',
    corpo_renderizado text,
    status text not null default 'pronta'
        check (status in ('pronta', 'enviada', 'pulada', 'expirada')),
    idempotency_key text not null unique,
    gerada_em timestamptz not null default now(),
    enviada_em timestamptz,
    motivo_pulo text
);

create index idx_messages_status_gerada on messages(status, gerada_em);

create table pick_results (
    id uuid primary key default gen_random_uuid(),
    pick_id uuid not null unique references picks(id),
    fixture_id uuid not null references fixtures(id),
    resultado text not null
        check (resultado in ('green', 'red', 'meio_green', 'meio_red', 'void', 'nao_liquidavel')),
    resolver text,
    evidencia_json jsonb,
    liquidado_em timestamptz,
    revisado_por_humano boolean not null default false
);

create table user_bankroll_config (
    user_id uuid primary key references users(id),
    banca_inicial numeric(10, 2) not null default 1000,
    stake_pct numeric(5, 4) not null default 0.02,
    modo_stake text not null default 'fixo' check (modo_stake in ('fixo', 'proporcional')),
    iniciado_em timestamptz not null default now()
);

create table bets (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references users(id),
    message_id uuid references messages(id),
    pick_id uuid not null references picks(id),
    fixture_id uuid not null references fixtures(id),
    odd numeric(6, 3) not null,
    stake_valor numeric(10, 2) not null,
    stake_pct numeric(5, 4) not null,
    resultado text not null,
    retorno numeric(10, 2) not null,
    banca_antes numeric(10, 2) not null,
    banca_depois numeric(10, 2) not null,
    sequencia int not null,
    registrado_em timestamptz not null default now(),
    liquidado_em timestamptz
);
