-- Fase 2: coletor de cada fonte (Eagle Predict e as que vierem depois)
-- precisa de upsert idempotente na tabela sources por nome. Sem essa
-- constraint, ON CONFLICT nao tem o que usar.
alter table sources
    add constraint sources_nome_key unique (nome);
