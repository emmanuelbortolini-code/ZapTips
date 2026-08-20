-- Fase 5d-D: modo sessao da aba Envio. Sessao e metadado de OPERACAO, nao
-- de usuario final - por isso nao tem user_id (guard de cobertura LGPD em
-- tests/test_users_export_cobertura.py nao precisa dela, e ela nunca deve
-- virar um ponteiro "assinante atual" persistido: a parada em foco e
-- sempre derivada de messages + app.messages_generator.ordem_da_sessao em
-- tempo real, nunca lida desta tabela).
--
-- data e slate_id podem divergir em teoria (nada aqui forca
-- data = (select data from daily_slates where id = slate_id)) - a unica
-- funcao que insere (app.console.acoes.iniciar_sessao) sempre passa os
-- dois vindos do mesmo daily_slates, entao a garantia e por construcao no
-- codigo, nao por trigger.
create table envio_sessoes (
    id uuid primary key default gen_random_uuid(),
    data date not null,
    slate_id uuid not null references daily_slates(id),
    status text not null default 'ativa' check (status in ('ativa', 'pausada', 'encerrada')),
    iniciada_em timestamptz not null default now(),
    iniciada_por text not null,
    pausada_em timestamptz,
    retomada_em timestamptz,
    encerrada_em timestamptz,
    encerrada_por text,
    motivo_encerramento text check (motivo_encerramento in ('manual', 'fila_vazia')),
    check ((status = 'encerrada') = (encerrada_em is not null))
);

-- No maximo 1 sessao aberta por dia. Parcial (nao unique(data) puro) de
-- proposito: D17 confirma que encerrar e iniciar uma segunda sessao no
-- mesmo dia e permitido - unique(data) sem o "where" proibiria isso, o
-- mesmo erro que a migration 0014 teve que desfazer em daily_slates.
create unique index uniq_envio_sessao_aberta_por_dia on envio_sessoes (data) where encerrada_em is null;

create index idx_envio_sessoes_data on envio_sessoes (data, iniciada_em desc);
