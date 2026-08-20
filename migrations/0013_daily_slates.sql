-- Fase 4: stream unico de palpites por dia (documento original, secao
-- "Stream unico de palpites"). daily_slates.data e a unica seletora do
-- dia (unique), status comeca sempre 'rascunho' - so vira 'aprovado' na
-- curadoria manual do console (Fase 5, ainda nao existe aqui).
create table daily_slates (
    id uuid primary key default gen_random_uuid(),
    data date not null unique,
    status text not null default 'rascunho' check (status in ('rascunho', 'aprovado')),
    curado_em timestamptz,
    curado_por text
);

-- odd_referencia/odd_referencia_em/odd_minima/odd_minima_origem sao uma
-- copia congelada dos mesmos campos em picks no momento da montagem do
-- slate (o pick pode seguir existindo e mudando depois; o slate_pick e
-- o que foi de fato publicado naquele dia, nao deve mudar retroativamente
-- - "slate aprovado e imutavel", documento original).
create table slate_picks (
    id uuid primary key default gen_random_uuid(),
    slate_id uuid not null references daily_slates(id),
    pick_id uuid not null references picks(id),
    ordem int not null,
    incluido_por text not null check (incluido_por in ('automatico', 'manual')),
    odd_referencia numeric(6, 3),
    odd_referencia_em timestamptz,
    odd_minima numeric(6, 3),
    odd_minima_origem text not null default 'calculada' check (odd_minima_origem in ('calculada', 'manual')),
    unique (slate_id, pick_id)
);

create index idx_slate_picks_slate on slate_picks(slate_id, ordem);
