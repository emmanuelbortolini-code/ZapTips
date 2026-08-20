-- Fase 5b: "Nenhum numero entra na lista sem registro de opt-in com
-- data, origem e evidencia" (documento original) - o schema desde a
-- Fase 0 so tinha data+origem, os dois nullable, e nao existia coluna de
-- evidencia nenhuma. users esta comprovadamente vazia (nenhum modulo ate
-- aqui grava nela - "captacao do zero, nao existe base previa", CLAUDE.md)
-- entao o NOT NULL abaixo nao precisa de backfill nem default. Depois de
-- existir gente de verdade, essa migration exigiria inventar registro de
-- consentimento retroativo - exatamente o que a regra probe.
alter table users add column opt_in_evidencia text;
alter table users alter column opt_in_em set not null;
alter table users alter column opt_in_origem set not null;
alter table users alter column opt_in_evidencia set not null;

-- Um mesmo comprovante de Pix nao paga duas assinaturas. Idempotencia
-- real pro erro humano que este CLI de fato produz: rodar o mesmo
-- comando duas vezes (historico do terminal). Parcial porque
-- referencia_pagamento e opcional no schema desde a Fase 0.
create unique index uq_subscriptions_referencia_pagamento
    on subscriptions (referencia_pagamento)
    where referencia_pagamento is not null;
