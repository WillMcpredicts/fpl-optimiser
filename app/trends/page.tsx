import Nav from "../Nav";
import { RELIABILITY, STRUCTURAL_STATS, loadTrends } from "@/lib/trends";

export const dynamic = "force-dynamic";

function pct(v: number) {
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

export default async function TrendsPage() {
  const data = await loadTrends();

  const byTeam = new Map<number, typeof data.flags>();
  for (const f of data.flags) {
    byTeam.set(f.team_id, [...(byTeam.get(f.team_id) ?? []), f]);
  }
  const teams = [...byTeam.entries()].sort((a, b) =>
    (data.teamName[a[0]] ?? "").localeCompare(data.teamName[b[0]] ?? ""),
  );

  const order = { high: 0, medium: 1, watch: 2 } as Record<string, number>;
  const backtest = [...data.backtest].sort(
    (a, b) => (order[a.confidence] ?? 9) - (order[b.confidence] ?? 9) || b.flags_evaluated - a.flags_evaluated,
  );

  return (
    <main className="wrap">
      <header className="top">
        <h1>FPL Optimiser</h1>
        <span className="meta">
          Trends · {data.season} · trend engine {data.gateEnabled ? "ON" : "OFF"}
        </span>
      </header>
      <Nav current="/trends" />

      <div className="banner">
        <strong>These do not affect any predicted points score</strong>
        <p style={{ margin: "6px 0 0" }}>
          The trend engine was backtested against the whole of {data.season} and did not
          earn its place. Seven high-confidence flags in an entire season is too few to
          conclude anything from, and medium-confidence flags predicted forward
          performance <em>worse</em> than simply assuming the league average. The gate in{" "}
          <code>trend_engine_gate</code> is off and every{" "}
          <code>trend_adjustment</code> is zero. What follows is context for your own
          judgement, not an input to the model.
        </p>
      </div>

      {data.error ? <div className="banner"><strong>Error:</strong> {data.error}</div> : null}

      <h2 style={{ fontSize: 15, margin: "22px 0 8px" }}>Is each pattern a real team trait?</h2>
      <p className="meta" style={{ marginTop: 0 }}>
        Split-half reliability: a team&rsquo;s rate over GW1&ndash;19 against GW20&ndash;38,
        roughly 231 shots per half. Attacking patterns persist because they are a coached
        style. How a team concedes by body part or zone is mostly a property of whichever
        opponents it happened to face &mdash; which is why those flags are shown but never used.
      </p>
      <div className="table-scroll" style={{ marginBottom: 26 }}>
        <table>
          <thead>
            <tr>
              <th className="left">Pattern</th>
              <th>Reliability (r)</th>
              <th className="left">Reading</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(RELIABILITY)
              .sort((a, b) => b[1] - a[1])
              .map(([stat, r]) => (
                <tr key={stat}>
                  <td className="left">{stat.replace(/_/g, " ")}</td>
                  <td>{r.toFixed(2)}</td>
                  <td className="left">
                    <span className={`pill ${r > 0.5 ? "high" : r > 0.25 ? "medium" : "low"}`}>
                      {r > 0.5 ? "stable" : r > 0.25 ? "weak" : "noise"}
                    </span>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      {backtest.length > 0 ? (
        <>
          <h2 style={{ fontSize: 15, margin: "22px 0 8px" }}>Backtest, walk-forward</h2>
          <p className="meta" style={{ marginTop: 0 }}>
            At each gameweek, flags built only from gameweeks already played, then scored
            against the following three. &ldquo;Improvement&rdquo; compares the trend
            estimate against simply assuming the league mean. Negative means the flag made
            the prediction worse.
          </p>
          <div className="table-scroll" style={{ marginBottom: 26 }}>
            <table>
              <thead>
                <tr>
                  <th className="left">Pattern</th>
                  <th className="left">Tier</th>
                  <th>Flags</th>
                  <th>Baseline MAE</th>
                  <th>Trend MAE</th>
                  <th>Improvement</th>
                  <th>Hit rate</th>
                  <th className="left">Verdict</th>
                </tr>
              </thead>
              <tbody>
                {backtest.map((b) => (
                  <tr key={`${b.stat_type}-${b.confidence}`}>
                    <td className="left">{b.stat_type.replace(/_/g, " ")}</td>
                    <td className="left">
                      <span className={`pill ${b.confidence}`}>{b.confidence}</span>
                    </td>
                    <td>{b.flags_evaluated}</td>
                    <td className="meta">{Number(b.baseline_mae).toFixed(4)}</td>
                    <td className="meta">{Number(b.trend_mae).toFixed(4)}</td>
                    <td>
                      <span className={`delta ${b.improvement_pct >= 0 ? "pos-val" : "neg-val"}`}>
                        {pct(Number(b.improvement_pct))}
                      </span>
                    </td>
                    <td>{Number(b.hit_rate).toFixed(2)}</td>
                    <td className="left">{b.passed ? "pass" : "fail"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      <h2 style={{ fontSize: 15, margin: "22px 0 8px" }}>
        Flags by team, end of {data.season}
      </h2>
      {teams.length === 0 ? (
        <p className="meta">
          No flags stored. Run <code>ingest/shots.py</code> then <code>ingest/trends.py</code>.
        </p>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th className="left">Team</th>
                <th className="left">Pattern</th>
                <th className="left">Direction</th>
                <th className="left">Confidence</th>
                <th>Sample</th>
                <th>Rate</th>
                <th>League avg</th>
                <th>z</th>
                <th className="left">Windows</th>
                <th className="left">Trait</th>
              </tr>
            </thead>
            <tbody>
              {teams.map(([teamId, flags]) =>
                flags
                  .sort((a, b) => Math.abs(b.z_score) - Math.abs(a.z_score))
                  .map((f) => {
                    const r = RELIABILITY[f.stat_type];
                    const structural = STRUCTURAL_STATS.has(f.stat_type);
                    return (
                      <tr key={`${teamId}-${f.stat_type}`}>
                        <td className="left">{data.teamName[teamId] ?? teamId}</td>
                        <td className="left">{f.label ?? f.stat_type}</td>
                        <td className="left">{f.direction}</td>
                        <td className="left">
                          <span className={`pill ${f.confidence}`}>{f.confidence}</span>
                        </td>
                        <td>{f.sample_size}</td>
                        <td>{Number(f.shrunk_rate).toFixed(4)}</td>
                        <td className="meta">{Number(f.league_mean).toFixed(4)}</td>
                        <td>{Number(f.z_score).toFixed(2)}</td>
                        <td className="left meta">
                          {f.first_window_confirmed ? "last4" : "—"}
                          {f.second_window_confirmed ? " + prev4" : ""}
                        </td>
                        <td className="left">
                          <span className={`pill ${structural ? "high" : "low"}`}>
                            {structural ? "stable style" : `r=${r?.toFixed(2) ?? "?"}`}
                          </span>
                        </td>
                      </tr>
                    );
                  }),
              )}
            </tbody>
          </table>
        </div>
      )}
      <p className="meta" style={{ marginTop: 12 }}>
        Sample size is the number of opportunities the rate is measured over. Anything
        under five events is computed and stored but never promoted to a flag.
      </p>
    </main>
  );
}
