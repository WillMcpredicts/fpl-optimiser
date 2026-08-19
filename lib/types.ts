export type Position = 1 | 2 | 3 | 4;

export const POSITION_NAMES: Record<Position, string> = {
  1: "GKP",
  2: "DEF",
  3: "MID",
  4: "FWD",
};

export type FixtureDetail = {
  fixture_id: number;
  opponent: string | null;
  opponent_elo: number | null;
  is_home: boolean;
  attack_multiplier: number;
  expected_goals_conceded: number;
  clean_sheet_probability: number;
  points: number;
};

export type ConfidenceBreakdown = {
  confidence: "low" | "medium" | "high";
  evidence_90s: number;
  current_season_90s: number;
  games_observed: number;
  availability: number;
  availability_reason: string;
  fixtures_this_gw: number;
  components: Record<string, number>;
  rates: Record<string, number>;
  fixtures: FixtureDetail[];
  trend_engine: string;
  notes: string[];
};

export type Prediction = {
  player_id: number;
  gw: number;
  base_score: number;
  fixture_adjustment: number;
  trend_adjustment: number;
  bps_adjustment: number;
  final_score: number;
  minutes_probability: number;
  expected_minutes: number;
  confidence_breakdown: ConfidenceBreakdown;
};

export type PlayerRow = {
  player_id: number;
  web_name: string;
  team: string;
  position: Position;
  price: number;
  status: string | null;
  news: string | null;
  selected_by_percent: number | null;
  penalties_order: number | null;
  corners_fk_order: number | null;
  direct_fk_order: number | null;
  cost_change_event: number | null;
  cost_change_start: number | null;
  transfers_in_event: number | null;
  transfers_out_event: number | null;
  form: number | null;
  points_per_game: number | null;
  /** Points by source, summed across the horizon. */
  sources: Record<string, number>;
  /** Per-gameweek final scores, keyed by gameweek. */
  byGw: Record<number, Prediction>;
  /** Sum of final_score across the projected horizon. */
  total: number;
  nextGw: number;
};

export type Dataset = {
  gameweeks: number[];
  players: PlayerRow[];
  source: "supabase" | "snapshot" | "none";
  generatedAt: string | null;
  modelVersion: string | null;
  /** Non-fatal problems worth showing rather than hiding. */
  warnings: string[];
};
