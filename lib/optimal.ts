import { isConfigured, selectRows } from "./supabase";

const SEASON = process.env.FPL_SEASON ?? "2026-27";

export type OptimalPlayer = {
  player_id: number;
  name: string;
  team: string;
  pos: number;
  cost: number;
  owned?: boolean;
  per_gw: Record<string, number>;
  total: number;
};

export type OptimalRow = {
  id: number;
  mode: "dream" | "reachable";
  transfers_allowed: number | null;
  budget: number;
  xi_points: number;
  squad_cost: number;
  hit_cost: number;
  net_points: number;
  detail: {
    gameweeks: number[];
    baseline_xi_points?: number;
    free_transfers?: number;
    squad: OptimalPlayer[];
    out?: { player_id: number }[];
    roles: Record<string, { starters: number[]; captain: number | null }>;
  };
};

export type OptimalData = {
  configured: boolean;
  error: string | null;
  gameweeks: number[];
  dream: OptimalRow | null;
  reachable: OptimalRow[];
  baseline: number;
  freeTransfers: number;
  best: OptimalRow | null;
  playerNames: Record<number, { name: string; team: string; cost: number; pos: number }>;
};

export async function loadOptimal(): Promise<OptimalData> {
  const empty: OptimalData = {
    configured: isConfigured(),
    error: null,
    gameweeks: [],
    dream: null,
    reachable: [],
    baseline: 0,
    freeTransfers: 1,
    best: null,
    playerNames: {},
  };
  if (!isConfigured()) return { ...empty, error: "Supabase is not configured." };

  try {
    const [rows, players, teams] = await Promise.all([
      selectRows<OptimalRow>(
        "optimal_squads",
        `season=eq.${SEASON}&select=*&order=transfers_allowed.asc`,
      ),
      selectRows<{ id: number; web_name: string; team_id: number; now_cost: number; element_type: number }>(
        "players",
        `season=eq.${SEASON}&select=id,web_name,team_id,now_cost,element_type`,
      ),
      selectRows<{ id: number; short_name: string }>("teams", `season=eq.${SEASON}&select=id,short_name`),
    ]);
    if (!rows.length) return empty;

    const teamName = new Map(teams.map((t) => [t.id, t.short_name]));
    const playerNames: OptimalData["playerNames"] = {};
    for (const p of players) {
      playerNames[p.id] = {
        name: p.web_name,
        team: teamName.get(p.team_id) ?? "?",
        cost: p.now_cost ?? 0,
        pos: p.element_type,
      };
    }

    const dream = rows.find((r) => r.mode === "dream") ?? null;
    const reachable = rows
      .filter((r) => r.mode === "reachable")
      .sort((a, b) => (a.transfers_allowed ?? 0) - (b.transfers_allowed ?? 0));

    // The best move is the transfer count with the highest NET points, which is
    // frequently zero or one -- taking hits is usually a losing trade.
    const best =
      reachable.length > 0
        ? reachable.reduce((a, b) => (Number(b.net_points) > Number(a.net_points) ? b : a))
        : null;

    return {
      ...empty,
      gameweeks: (dream ?? reachable[0])?.detail.gameweeks ?? [],
      dream,
      reachable,
      baseline: Number(reachable[0]?.detail.baseline_xi_points ?? 0),
      freeTransfers: reachable[0]?.detail.free_transfers ?? 1,
      best,
      playerNames,
    };
  } catch (err) {
    return { ...empty, error: (err as Error).message };
  }
}
