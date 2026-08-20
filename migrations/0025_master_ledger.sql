-- Fase 6b: extrato mestre. Diferente de `pick_results` (Fase 6a, guarda
-- a liquidacao de QUALQUER pick vinculado com fixture encerrada,
-- publicado ou nao), master_ledger so recebe o que "entrou no extrato"
-- (spec, secao 6b): pick de slate aprovado, efetivamente enviado a pelo
-- menos um assinante, antes do kickoff. app/settlement/master_ledger.py
-- aplica esse filtro lendo de pick_results + slate_picks + messages.
--
-- `odd` vem de slate_picks.odd_minima (a copia congelada no momento da
-- aprovacao - "slate aprovado e' imutavel", Fase 4), nunca de
-- picks.odd_minima direto (que pode em teoria mudar depois via console).
-- Essa e' "a decisao mais importante da fase" (spec): o extrato publicado
-- assume que a aposta foi feita no piso publicado, nunca na odd de
-- referencia nem na odd citada pelo tipster.
create table master_ledger (
    id uuid primary key default gen_random_uuid(),
    pick_id uuid not null unique references picks(id),
    fixture_id uuid not null references fixtures(id),
    ordem int not null,
    odd numeric(6, 3) not null,
    resultado text not null
        check (resultado in ('green', 'meio_green', 'void', 'meio_red', 'red')),
    fator_retorno numeric(8, 4) not null,
    liquidado_em timestamptz not null default now()
);

-- `ordem` e' recalculada do zero a cada rebuild (app/settlement/
-- master_ledger.py::montar_entradas ordena por kickoff+pick_id e
-- reenumera 1..N) - unique garante que o rebuild nunca deixa dois
-- picks com a mesma posicao.
create unique index uniq_master_ledger_ordem on master_ledger (ordem);
