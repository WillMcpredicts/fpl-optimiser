import Nav from "../Nav";
import SquadForm from "./SquadForm";
import { bestXi, loadSquad } from "@/lib/squad";
import { selectRows, isConfigured } from "@/lib/supabase";
import { POSITION_NAMES, type Position } from "@/lib/types";

export const dynamic = "force-dynamic";

const SEASON = process.env.FPL_SEASON ?? "2026-27";

async function loadOptions() {
  if (!isConfigured()) return { options: [], gw: 1 };
  const [players, teams, predictions] = await Promise.all([
    selectRows<{
      id: number;
      web_name: string;
      team_id: number;
      element_type: number;
      now_cost: number;
    }>("players", `season=eq.${SEASON}&select=id,web_name,team_id,element_type,now_cost`),
    selectRows<{ id: number; short_name: string }>("teams", `season=eq.${SEASON}&select=id,short_name`),
    selectRows<{ player_id: number; gw: number; final_score: number }>(
      "predicted_points",
      `season=eq.${SEASON}&select=player_id,gw,final_score`,
    ),
  ]);
  const gws = [...new Set(predictions.map((p) => p.gw))].sort((a, b) => a - b).slice(0, 3);
  const totals = new Map<number, number>();
  for (const p of predictions) {
    if (gws.includes(p.gw)) {
      totals.set(p.player_id, (totals.get(p.player_id) ?? 0) + Number(p.final_score));
    }
  }
  const teamName = new Map(teams.map((t) => [t.id, t.short_name]));
  return {
    gw: gws[0] ?? 1,
    options: players.map((p) => ({
      id: p.id,
      web_name: p.web_name,
      team: teamName.get(p.team_id) ?? "?",
      team_id: p.team_id,
      element_type: p.element_type,
      now_cost: p.now_cost ?? 0,
      points_3gw: totals.get(p.id) ?? 0,
    })),
  };
}

export default async function SquadPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; saved?: string; gw?: string }>;
}) {
  const params = await searchParams;
  const [data, { options, gw }] = await Promise.all([loadSquad(), loadOptions()]);

  // Which gameweek's XI to show. Defaults to the next one, because that is the
  // decision actually in front of you; the horizon total is the wrong basis for
  // picking a team on Saturday.
  const selectedGw = Number(params.gw ?? data.gameweeks[0] ?? 0);
  const gwScore = (p: (typeof data.players)[number]) => p.perGw?.[selectedGw] ?? 0;
  const xiForGw = bestXi(data.players, gwScore);
  const starters = data.players
    .filter((p) => xiForGw.has(p.player_id))
    .sort((a, b) => gwScore(b) - gwScore(a));
  const bench = data.players
    .filter((p) => !xiForGw.has(p.player_id))
    .sort((a, b) => gwScore(b) - gwScore(a));

  // A weak pick is a starter in the bottom third of comparably priced players
  // in the same position -- cheap alternatives exist that score more.
  const weak = new Set(
    starters
      .filter((p) => p.bracketPercentile !== null && p.bracketPercentile < 0.34)
      .map((p) => p.player_id),
  );

  const row = (p: (typeof data.players)[number]) => (
    <tr key={p.player_id}>
      <td className="left">
        {p.web_name}
        {p.is_captain ? <span className="xi-badge" style={{ marginLeft: 6 }}>C</span> : null}
        {p.status && p.status !== "a" ? <span className="flag" title={p.news ?? ""}> ⚠</span> : null}
      </td>
      <td className="left">{p.team}</td>
      <td className="left">
        <span className="pos">{POSITION_NAMES[p.position as Position]}</span>
      </td>
      <td>{(p.selling_price / 10).toFixed(1)}</td>
      <td><strong>{(p.perGw?.[selectedGw] ?? 0).toFixed(2)}</strong></td>
      <td><strong>{p.points_3gw.toFixed(2)}</strong></td>
      <td>{(p.points_3gw / (p.selling_price / 10)).toFixed(2)}</td>
      <td className={weak.has(p.player_id) ? "weak" : ""}>
        {p.bracketPercentile === null ? "—" : `${Math.round(p.bracketPercentile * 100)}%`}
      </td>
      <td className="left">
        <span className={`xi-badge ${p.inBestXi ? "starter" : ""}`}>
          {p.inBestXi ? "XI" : "bench"}
        </span>
      </td>
      <td className="left meta">{p.news ?? ""}</td>
    </tr>
  );

  return (
    <main className="wrap">
      <header className="top">
        <h1>FPL Optimiser</h1>
        <span className="meta">
          Squad{data.hasSquad ? ` · GW${data.gw} · ${data.source}` : ""}
        </span>
      </header>
      <Nav current="/squad" />

      {params.error ? (
        <div className="banner"><strong>Could not save:</strong> {params.error}</div>
      ) : null}
      {params.saved ? (
        <div className="banner">
          <strong>Squad saved.</strong>
          <p style={{ margin: "6px 0 0" }}>
            Transfer suggestions are produced by the planner, not the browser. Run{" "}
            <code>.venv/bin/python ingest/run.py plan</code> or wait for the next scheduled
            ingestion, then check the Transfers page.
          </p>
        </div>
      ) : null}
      {data.error ? <div className="banner"><strong>Error:</strong> {data.error}</div> : null}

      {data.hasSquad ? (
        <>
          <p className="meta" style={{ marginTop: 0 }}>
            Squad value £{(data.squadValue / 10).toFixed(1)}m · bank £{(data.bank / 10).toFixed(1)}m ·{" "}
            {data.freeTransfers} free transfer{data.freeTransfers === 1 ? "" : "s"} · GW{selectedGw} XI projects{" "}
            <strong>{starters.reduce((a, p) => a + gwScore(p), 0).toFixed(1)}</strong>, and the
            whole squad{" "}
            <strong>{data.players.reduce((a, p) => a + p.points_3gw, 0).toFixed(1)}</strong>{" "}
            across GW{data.gameweeks[0]}–{data.gameweeks[data.gameweeks.length - 1]}.
          </p>
          <div className="controls" style={{ marginBottom: 12 }}>
            <span className="meta">Pick the XI for:</span>
            {data.gameweeks.map((gw) => (
              <a
                key={gw}
                href={`/squad?gw=${gw}`}
                className="xi-badge"
                style={{
                  padding: "5px 11px",
                  textDecoration: "none",
                  borderColor: gw === selectedGw ? "var(--accent)" : undefined,
                  color: gw === selectedGw ? "var(--text)" : undefined,
                }}
              >
                GW{gw}
              </a>
            ))}
            <span className="meta">
              Chosen for GW{selectedGw} alone — you field a team for one week, not for the
              whole horizon.
            </span>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th className="left">Player</th>
                  <th className="left">Team</th>
                  <th className="left">Pos</th>
                  <th>£</th>
                  <th>GW{selectedGw}</th>
                  <th>{data.gameweeks.length} GWs</th>
                  <th>Pts per £m</th>
                  <th>vs price bracket</th>
                  <th className="left">Role</th>
                  <th className="left">News</th>
                </tr>
              </thead>
              <tbody>
                {starters.map(row)}
                {bench.map(row)}
              </tbody>
            </table>
          </div>
          <p className="meta" style={{ marginTop: 10 }}>
            &ldquo;vs price bracket&rdquo; is where a player ranks against others in the same
            position within £0.5m of their price. A starter below 34% is flagged: cheaper or
            equally priced alternatives are projected to score more.
            {weak.size > 0
              ? ` ${weak.size} starting pick${weak.size === 1 ? "" : "s"} flagged.`
              : " No starting picks flagged."}
          </p>
        </>
      ) : (
        <div className="banner">
          <strong>No squad imported yet</strong>
          <p style={{ margin: "6px 0 0" }}>
            FPL&rsquo;s <code>my-team</code> endpoint needs an authenticated session, and this
            project deliberately does not handle FPL login, so enter your 15 below. From GW2
            you can also pull your last locked squad with{" "}
            <code>python ingest/squad.py fpl &lt;manager_id&gt; &lt;gw&gt;</code>.
          </p>
        </div>
      )}

      <h2 style={{ fontSize: 15, margin: "26px 0 10px" }}>
        {data.hasSquad ? "Replace squad" : "Enter your squad"}
      </h2>
      <SquadForm options={options} gw={gw} initial={data.players.map((p) => p.player_id)} />
    </main>
  );
}
