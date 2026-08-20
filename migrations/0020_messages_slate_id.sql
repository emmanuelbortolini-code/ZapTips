-- Fase 5d: sem isso nao da pra responder "esta mensagem veio de qual
-- slate?", nem limpar mensagens 'pronta' cuja fixture saiu do slate
-- numa correcao (ver app/messages_generator.py). Nullable porque
-- messages esta vazia hoje, mas nao ha motivo pra inventar valor se um
-- dia nao houver slate associado.
alter table messages add column slate_id uuid references daily_slates(id);
