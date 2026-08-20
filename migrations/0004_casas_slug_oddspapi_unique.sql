-- Fase 1g: adapter do OddsPapi faz upsert idempotente de casas por
-- slug_oddspapi (bet365/betano/superbet). Sem essa constraint, ON
-- CONFLICT nao tem o que usar.
alter table casas
    add constraint casas_slug_oddspapi_key unique (slug_oddspapi);
