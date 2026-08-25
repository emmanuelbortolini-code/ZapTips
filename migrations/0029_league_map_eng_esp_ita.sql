-- Expande league_map (Fase 1g so tinha bra.1/bra.2 - ver migration
-- 0006) pras 3 proximas ligas do documento original com cobertura ESPN
-- (app/ligas.py::LIGAS) e cobertura confirmada com dado real na
-- OddsPapi: Premier League, LaLiga, Serie A (Italia). tournamentId
-- confirmado via GET /tournaments em 2026-08-25 (sportId=10),
-- casando por tournamentSlug+categorySlug exato pra nunca colidir com
-- torneio de mesmo nome em outro pais (ex.: "Serie A" existe em varios
-- paises - o alvo aqui e' categorySlug='italy').
--
-- Escopo intencionalmente parado em 5 ligas totais (as 2 ja existentes
-- + estas 3): achado real desta sessao, GET /odds-by-tournaments
-- devolve 400 "Too many tournament IDs specified... maximum of 5" -
-- scripts/collect_odds.py hoje faz UMA chamada por casa cobrindo todo
-- `league_map` numa tacada so; mais que 5 ligas ativas quebraria essa
-- chamada (ou exigiria lotear em varias chamadas, triplicando o
-- consumo diario de cota - fora do orcamento de 250/mes). As 6 ligas
-- restantes do documento original (ger.1, fra.1, bra.copa_do_brazil,
-- uefa.champions, conmebol.libertadores, conmebol.sudamericana) ficam
-- de fora por essa razao, nao por falta de cobertura confirmada -
-- tournamentId de todas as 9 ja foi levantado e confirmado com
-- futureFixtures > 0 real, documentado no historico da sessao.
insert into league_map (espn_league_code, oddspapi_tournament_id, nome, ativa)
values
    ('eng.1', '17', 'Premier League', true),
    ('esp.1', '8', 'LaLiga', true),
    ('ita.1', '23', 'Serie A (Italia)', true)
on conflict (espn_league_code) do nothing;
