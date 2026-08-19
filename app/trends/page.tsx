import Nav from "../Nav";
import {
  MATCHUP_TEST,
  OPPONENT_GENEROSITY,
  RELIABILITY,
  STRUCTURAL_STATS,
  loadTrends,
} from "@/lib/trends";

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
        <strong>One trend is live. The rest are not, and the difference is evidence.</strong>
        <p style={{ margin: "6px 0 0" }}>
          <strong>Live:</strong> how generous each opponent is to each position, in FPL
          points. It improves predictions by {OPPONENT_GENEROSITY.overallGain}% on data it
          has never seen, measured on top of the fixture adjustment already applied. It is
          damped to {OPPONENT_GENEROSITY.damping} and capped at {OPPONENT_GENEROSITY.cap}%,
          and never touches forwards.
        </p>
        <p style={{ margin: "6px 0 0" }}>
          <strong>Not live:</strong> everything derived from shot patterns — headers
          conceded, set-piece vulnerability, zones. Those failed the same test.
        </p>
      </div>

      <h2 style={{ fontSize: 15, margin: "26px 0 8px" }}>The trend that works</h2>
      <div className="explain">
        <p>
          The idea: some sides concede points disproportionately to a position, for
          structural reasons. Face a dominant possession team and your defenders spend the
          match clearing and blocking, so their defensive-contribution points rise whatever
          the score. That is a repeatable, causal effect — not a coincidence of the fixture
          list.
        </p>
        <p>
          It was tested the hard way. Not against a naive baseline, but{" "}
          <em>incrementally</em>: the Elo fixture adjustment is applied first, and this has
          to earn whatever is left. That matters, because a strong team both concedes few
          points and has a high Elo — test it naively and you mostly re-discover fixture
          difficulty and flatter the result. Damping was tuned on gameweeks 10–24 and
          scored on 25–38, which it never saw.
        </p>
        <div className="table-scroll" style={{ margin: "12px 0" }}>
          <table>
            <thead>
              <tr>
                <th className="left">Position</th>
                <th>Player-GWs tested</th>
                <th>Gain over fixture adjustment</th>
                <th className="left">In the model?</th>
              </tr>
            </thead>
            <tbody>
              {OPPONENT_GENEROSITY.byPosition.map((r) => (
                <tr key={r.pos}>
                  <td className="left"><span className="pos">{r.pos}</span></td>
                  <td>{r.n}</td>
                  <td className={r.gain > 0 ? "pos-val" : "neg-val"}>
                    {r.gain > 0 ? "+" : ""}{r.gain}%
                  </td>
                  <td className="left">
                    <span className={`pill ${r.used ? "high" : "low"}`}>
                      {r.used ? "yes" : "no"}
                    </span>{" "}
                    <span className="meta">{r.reason}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          The gain is uniform across keepers, defenders and midfielders — 0.54%, 0.55%,
          0.54%. Noise does not line up like that across three independent groups. Forwards
          are negative and excluded: what a forward scores against a given side is dominated
          by which forward it is, not who they play.
        </p>
        <p>
          Keepers are excluded too, for a different reason. The effect is real within a
          season but does not survive the summer (r = 0.01), because keeper points come from
          saves and clean sheets, which depend on personnel that changes. Midfielders carry
          best across seasons (r = 0.59), defenders weakly (0.30) — so last season seeds
          this one at those weights, and the live season takes over as it accumulates.
        </p>
        <p className="meta">
          For scale: the Elo fixture adjustment itself is worth{" "}
          {OPPONENT_GENEROSITY.eloGainForContext}% on the same test. This adds
          {" "}{OPPONENT_GENEROSITY.overallGain}% on top. It is a refinement, not the engine.
        </p>
      </div>

      <h2 style={{ fontSize: 15, margin: "26px 0 8px" }}>The trends that do not work</h2>

      <h3 style={{ fontSize: 14, margin: "16px 0 8px", color: "var(--muted)" }}>
        Why shot-pattern trends were rejected
      </h3>
      <div className="explain">
        <p>
          Take a specific, reasonable idea: <em>Brentford concede a lot of headed goals, so
          a Spurs player who scores headers should get a small uplift when they play
          Brentford.</em> That is the kind of nuance this page exists to test.
        </p>
        <p>
          It has two halves, and they turn out to be very different claims.
        </p>
        <p>
          <strong>&ldquo;Spurs score lots of headers&rdquo;</strong> is a real, lasting team
          trait. Measured across last season, a team&rsquo;s headed share of its own chances
          in the first half of the season predicts the second half well (r = 0.73). It is a
          coached style: who they sign, how they cross, who attacks the near post.
        </p>
        <p>
          <strong>&ldquo;Brentford concede lots of headers&rdquo;</strong> mostly is not. The
          same measurement on the defensive side comes out at r = 0.28, close to noise. The
          reason is that how a team concedes by body part is largely decided by{" "}
          <em>who they happened to play</em>. Face three crossing sides in a row and you
          look vulnerable to headers; face three teams who pass through the middle and you
          look solid. That is the fixture list talking, not the defence.
        </p>
      </div>

      <h2 style={{ fontSize: 15, margin: "26px 0 8px" }}>So I tested the combination directly</h2>
      <div className="explain">
        <p>
          Reliability alone does not settle it, because the two halves might still combine
          into something useful. So the exact idea was tested on its own terms: for every
          team-match last season, predict the headed chances a side creates, using only
          games played before it. Three predictors, compared on {MATCHUP_TEST.n}{" "}
          team-matches:
        </p>
        <ul>
          <li><strong>Baseline</strong> — assume the league average.</li>
          <li><strong>Attacker only</strong> — use how header-heavy the attacking side is.</li>
          <li><strong>Attacker × defence</strong> — the full idea, scaling by how vulnerable
            the opponent has been to headers.</li>
        </ul>
        <p>
          The full idea <em>does</em> correlate best with what actually happened
          (r = {MATCHUP_TEST.correlation} against {MATCHUP_TEST.correlationAttackerOnly}{" "}
          for attacker alone; t = {MATCHUP_TEST.tStatistic}, so that is not chance). The
          instinct is sound and the direction is real.
        </p>
        <p>
          But the size is tiny. Even after tuning how much weight the opponent term gets, it
          beats attacker-alone by <strong>{MATCHUP_TEST.gainOverAttackerOnly}%</strong>, and
          is still <strong>slightly worse than simply assuming the league average</strong>.
          That tuning was also done on the same data it was scored against, so the true
          figure is lower still.
        </p>
        <p>
          Detectable is not the same as useful. A {MATCHUP_TEST.gainOverAttackerOnly}% edge
          on one component of one stat, inside a projection where minutes dominate
          everything, cannot justify moving a player&rsquo;s score. So it does not.
        </p>
        <p className="meta">
          The half that <em>is</em> real is already counted: a player who scores headers has
          those headers in their own xG history, which is what the model actually uses.
        </p>
      </div>

      <h2 style={{ fontSize: 15, margin: "26px 0 8px" }}>Reading the tables below</h2>
      <div className="explain">
        <p>
          <strong>Reliability (r)</strong> answers &ldquo;is this a lasting property of the
          team, or an accident of who they played?&rdquo; It compares each team&rsquo;s rate
          in the first half of the season against the second. 1.0 would mean perfectly
          consistent; 0 means the first half tells you nothing about the second. Above ~0.5
          is a real trait; below ~0.25 is noise.
        </p>
        <p>
          <strong>Confidence</strong> on a flag is about evidence, not size. A flag is only{" "}
          <em>high</em> if the pattern showed up in two separate, non-overlapping four-match
          windows. One window on its own is a <em>watch</em> item — patterns appear in small
          samples constantly, and most evaporate.
        </p>
        <p>
          <strong>Sample</strong> is how many real events the rate rests on. Under five and
          it is recorded but never promoted to a flag at all.
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
