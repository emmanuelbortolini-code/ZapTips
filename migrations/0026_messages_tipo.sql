-- Fase 6e: "fechamento do palpite" entra na MESMA fila de `messages`
-- (spec, "Dois formatos novos de mensagem, entrando na mesma fila do
-- console"), so' que com `tipo` diferente - sem essa coluna, nao daria
-- pra saber qual template ja foi usado nem para escopar a idempotency
-- key por tipo (um usuario pode legitimamente ter uma mensagem
-- 'palpite' e uma 'fechamento' pra MESMA fixture/data, sem colidir).
--
-- 'resumo_semanal' fica de fora deste ALTER de proposito: nao tem
-- fixture (e' um agregado da semana), e messages.fixture_id continua
-- not null por decisao desta sessao - o escopo de reescrever
-- fila_envio/templates/sessao pra mensagem sem partida ficou pra depois
-- (ver CLAUDE.md, Fase 6e).
alter table messages add column tipo text not null default 'palpite'
    check (tipo in ('palpite', 'fechamento'));

-- Mesma (user_id, fixture_id, data) pode ter um 'palpite' E um
-- 'fechamento' sem colidir - a idempotency_key ja inclui o tipo desde a
-- geracao (app.messages_generator.montar_idempotency_key_fechamento),
-- entao nenhum backfill e' necessario aqui.
