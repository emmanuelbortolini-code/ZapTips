-- Fase 5c: a aba de Curadoria precisa mostrar "odd de referencia com
-- origem" (documento original) - slate_picks ja congela odd_referencia/
-- odd_minima no momento da montagem (comentario da migration 0013), mas
-- nunca guardou a origem. 'manual' cobre o caso em que o operador digita
-- uma odd que faltava (spec: "o campo fica editavel e eu digito na
-- mao") - grava a origem certa em vez de inventar uma das automaticas.
alter table slate_picks add column odd_referencia_origem text
    check (odd_referencia_origem in ('fonte', 'oddspapi', 'espn', 'manual'));

update slate_picks sp
set odd_referencia_origem = p.odd_referencia_origem
from picks p
where p.id = sp.pick_id and sp.odd_referencia_origem is null;
