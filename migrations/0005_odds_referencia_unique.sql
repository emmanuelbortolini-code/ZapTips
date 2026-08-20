-- Fase 1g: coleta de odds de referencia via OddsPapi precisa de upsert
-- idempotente. `linha` e nullable (sempre null para 1x2, o unico mercado
-- coletado nesta etapa), e unique constraints comuns tratam NULL como
-- distinto de qualquer outro NULL - usa indice de expressao com coalesce
-- para normalizar isso.
create unique index odds_referencia_dedup_idx
    on odds_referencia (fixture_id, casa_id, mercado, selecao, coalesce(linha, -1));
