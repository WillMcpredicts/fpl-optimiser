import { isConfigured, selectRows } from "./supabase";

const TREND_SEASON = process.env.TREND_SEASON ?? "2025-26";

/** Stats whose split-half reliability shows a genuine, persistent team trait. */
export const STRUCTURAL_STATS = new Set([
  "head_xg_share_for",
  "setpiece_xg_share_for",
]);

/** Measured on 2025-26: rate over GW1-19 against GW20-38, ~231 shots a half. */
export const RELIABILITY: Record<string, number> = {
  head_xg_share_for: 0.73,
  setpiece_xg_share_for: 0.51,
  xg_per_shot_conceded: 0.39,
  head_xg_conceded_per_shot_faced: 0.34,
  head_shots_conceded_per_shot_faced: 0.28,
  right_flank_shots_conceded_per_shot_faced: 0.25,
  setpiece_shots_conceded_per_shot_faced: 0.16,
  setpiece_xg_conceded_per_shot_faced: 0.14,
  fastbreak_shots_conceded_per_shot_faced: 0.1,
  left_flank_shots_conceded_per_shot_faced: 0.01,
  box_shots_conceded_per_shot_faced: -0.31,
};

/**
 * The matchup test: does knowing the opponent's headed weakness add anything
 * beyond knowing the attacker's headed tendency? Walk-forward over 2025-26,
 * 660 team-matches. Damping factor applied to the opponent term, tuned on the
 * same data it is scored against -- so these figures flatter it, if anything.
 */
export const MATCHUP_TEST = {
  n: 660,
  correlation: 0.166,
  correlationAttackerOnly: 0.138,
  tStatistic: 4.31,
  bestDamping: 0.4,
  gainOverAttackerOnly: 0.67, // percent MAE improvement at best damping
  gainOverBaseline: -0.1, // still worse than "assume league average"
};

export type TrendFlag = {
  team_id: number;
  stat_type: string;
  direction: string;
  confidence: "watch" | "medium" | "high";
  sample_size: number;
  z_score: number;
  shrunk_rate: number;
  league_mean: number;
  first_window_confirmed: boolean;
  second_window_confirmed: boolean;
  points_multiplier: number;
  label: string | null;
  as_of_gw: number;
};

export type BacktestRow = {
  stat_type: string;
  confidence: string;
  flags_evaluated: number;
  baseline_mae: number;
  trend_mae: number;
  improvement_pct: number;
  hit_rate: number;
  passed: boolean;
};

export type TrendsData = {
  season: string;
  flags: TrendFlag[];
  backtest: BacktestRow[];
  teamName: Record<number, string>;
  gateEnabled: boolean;
  configured: boolean;
  error: string | null;
};

export async function loadTrends(): Promise<TrendsData> {
  const empty: TrendsData = {
    season: TREND_SEASON,
    flags: [],
    backtest: [],
    teamName: {},
    gateEnabled: false,
    configured: isConfigured(),
    error: null,
  };
  if (!isConfigured()) return { ...empty, error: "Supabase is not configured." };

  try {
    const [flags, backtest, teams, gate] = await Promise.all([
      selectRows<TrendFlag>("trend_flags", `season=eq.${TREND_SEASON}&select=*`),
      selectRows<BacktestRow>("backtest_results", `season=eq.${TREND_SEASON}&select=*`),
      selectRows<{ id: number; short_name: string }>(
        "teams",
        `season=eq.${TREND_SEASON}&select=id,short_name`,
      ),
      selectRows<{ enabled: boolean }>("trend_engine_gate", "select=enabled"),
    ]);
    return {
      ...empty,
      flags,
      backtest,
      teamName: Object.fromEntries(teams.map((t) => [t.id, t.short_name])),
      gateEnabled: Boolean(gate[0]?.enabled),
    };
  } catch (err) {
    return { ...empty, error: (err as Error).message };
  }
}
