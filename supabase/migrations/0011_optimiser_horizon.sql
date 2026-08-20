-- Optimiser results per planning horizon.
--
-- The best move over one gameweek is often not the best move over six: a player
-- with a hard fixture this week and an easy run after is a bad one-week
-- transfer and a good six-week one. Storing each horizon separately lets the
-- page show both rather than implying there is a single right answer.

alter table optimal_squads
  add column if not exists horizon int;

update optimal_squads set horizon = 6 where horizon is null;

drop index if exists optimal_squads_lookup_idx;
create index if not exists optimal_squads_lookup_idx
  on optimal_squads (season, gw, horizon, mode, transfers_allowed);
