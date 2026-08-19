-- The trend engine records how hard it shrank each rate and why.
--
-- `shrinkage_k` is the empirical Bayes constant in units of the denominator:
-- how many league-average opportunities are added before a team's own rate is
-- believed. A large k means the engine judged the apparent spread to be noise.
--
-- `between_stdev` is the estimated spread of TRUE team rates, and is the
-- denominator of shrunk_z. Storing it makes a flag's z reconstructible rather
-- than something the UI has to take on trust.

alter table team_rate_stats
  add column if not exists shrinkage_k  numeric,
  add column if not exists between_stdev numeric;
