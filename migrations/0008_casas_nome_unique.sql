-- Fase 2, Fonte 2 (SDA): seed das casas licenciadas citadas por essa
-- fonte precisa de upsert idempotente por nome. Novibet, BetBoom e VBET
-- nao tem slug_oddspapi (nao existem no provedor, ver CLAUDE.md Fase 1b)
-- entao a constraint unica existente em slug_oddspapi nao serve pra elas.
alter table casas
    add constraint casas_nome_key unique (nome);
