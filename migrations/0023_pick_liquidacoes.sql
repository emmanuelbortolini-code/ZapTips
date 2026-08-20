-- Fase 6a: registro do resultado categorico de cada pick liquidado
-- (app.settlement.engine.liquidar). Deliberadamente SEM `odd`/`ordem`/
-- `fator_retorno` - esses campos (spec, secao 6b "Simulacao de banca")
-- so fazem sentido pro `master_ledger` (o "extrato mestre publicado"),
-- que exige o criterio de elegibilidade "entra no extrato" (slate
-- aprovado + enviado a pelo menos um assinante + antes do kickoff) -
-- um filtro de NEGOCIO que a Fase 6b ainda nao implementou. Misturar
-- esse filtro aqui faria a liquidacao de 6a (que deve valer para
-- QUALQUER pick vinculado com fixture encerrada, publicado ou nao)
-- depender de uma decisao que ainda nao foi tomada.
--
-- `master_ledger` sera construida na Fase 6b lendo desta tabela e
-- aplicando o filtro de elegibilidade - nao o contrario.
create table pick_liquidacoes (
    id uuid primary key default gen_random_uuid(),
    pick_id uuid not null references picks(id),
    fixture_id uuid not null references fixtures(id),
    resultado text not null
        check (resultado in ('green', 'meio_green', 'void', 'meio_red', 'red')),
    evidencia jsonb not null default '{}'::jsonb,
    revisado_por_humano boolean not null default false,
    motivo_revisao_manual text,
    liquidado_em timestamptz not null default now()
);

-- Um pick liquida uma vez so - reprocessar um pick ja presente aqui e'
-- decisao explicita (revisao manual corrigindo um resolver automatico),
-- nunca um upsert silencioso de rerun.
create unique index uniq_pick_liquidacoes_pick_id on pick_liquidacoes (pick_id);

create index idx_pick_liquidacoes_fixture on pick_liquidacoes (fixture_id);
