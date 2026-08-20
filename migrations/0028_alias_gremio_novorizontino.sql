-- Achado real (2026-08-20, ver docs/HISTORICO.md "Grêmio Novorizontino"):
-- app.matcher recusava resolver o participante da OddsPapi "Grêmio
-- Novorizontino SP" contra o time "Novorizontino" (score 100, mas
-- ambiguo) - nao e bug do matcher, e ambiguidade real: existe outro
-- time cadastrado, "Grêmio" (RS), e "Grêmio Novorizontino" e' o nome
-- oficial completo do clube de Novo Horizonte-SP (mesmo padrao de
-- "Grêmio Foot-Ball Porto Alegrense" pro Grêmio gaucho) - o token
-- "gremio" aparece nos dois, entao o fuzzy nunca deveria chutar sozinho
-- aqui. Corrigido com alias EXATO (prioridade sobre fuzzy no matcher,
-- Fase 1c), sem tocar no time "Grêmio" nem na logica de desambiguacao.
insert into team_aliases (team_id, alias, alias_normalizado)
select id, 'Grêmio Novorizontino', 'gremio novorizontino'
from teams where nome_canonico = 'Novorizontino'
on conflict (team_id, alias_normalizado) do nothing;

insert into team_aliases (team_id, alias, alias_normalizado)
select id, 'Grêmio Novorizontino SP', 'gremio novorizontino sp'
from teams where nome_canonico = 'Novorizontino'
on conflict (team_id, alias_normalizado) do nothing;
