import Nav from "../Nav";
import { HORIZONS, loadOptimal, type OptimalRow } from "@/lib/optimal";
import { POSITION_NAMES, type Position } from "@/lib/types";

export const dynamic = "force-dynamic";

function SquadTable({ row, gws, ownedKnown }: { row: OptimalRow; gws: number[]; ownedKnown: boolean }) {
  const order = [...row.detail.squad].sort((a, b) => a.pos - b.pos || b.total - a.total);
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th className="left">Player</th>
            <th className="left">Team</th>
            <th className="left">Pos</th>
            <th>£</th>
            {gws.map((gw) => (
              <th key={gw}>GW{gw}</th>
            ))}
            <th>3 GWs</th>
            {ownedKnown ? <th className="left">Status</th> : null}
          </tr>
        </thead>
        <tbody>
          {order.map((p) => (
            <tr key={p.player_id}>
              <td className="left">{p.name}</td>
              <td className="left">{p.team}</td>
              <td className="left">
                <span className="pos">{POSITION_NAMES[p.pos as Position]}</span>
              </td>
              <td>{(p.cost / 10).toFixed(1)}</td>
              {gws.map((gw) => {
                const role = row.detail.roles[String(gw)];
                const starting = role?.starters.includes(p.player_id);
                const captain = role?.captain === p.player_id;
                return (
                  <td key={gw} className={starting ? "" : "meta"}>
                    {(p.per_gw[String(gw)] ?? 0).toFixed(2)}
                    {captain ? <span className="xi-badge starter" style={{ marginLeft: 4 }}>C</span> : null}
                    {!starting ? <span className="xi-badge" style={{ marginLeft: 4 }}>b</span> : null}
                  </td>
                );
              })}
              <td><strong>{p.total.toFixed(2)}</strong></td>
              {ownedKnown ? (
                <td className="left">
                  <span className={`pill ${p.owned ? "high" : "medium"}`}>
                    {p.owned ? "keep" : "buy"}
                  </span>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function OptimiserPage({
  searchParams,
}: {
  searchParams: Promise<{ h?: string }>;
}) {
  const params = await searchParams;
  const requested = Number(params.h ?? 6);
  const data = await loadOptimal(
    HORIZONS.includes(requested) ? requested : 6,
  );
  const gws = data.gameweeks;

  const horizonToggle = (
    <div className="controls" style={{ marginBottom: 14 }}>
      <span className="meta">Optimise for:</span>
      {HORIZONS.map((h) => (
        <a
          key={h}
          href={`/optimiser?h=${h}`}
          className="xi-badge"
          style={{
            padding: "5px 12px",
            textDecoration: "none",
            borderColor: h === data.horizon ? "var(--accent)" : undefined,
            color: h === data.horizon ? "var(--text)" : undefined,
          }}
        >
          {h === 1 ? "This gameweek" : `${h} gameweeks`}
        </a>
      ))}
      <span className="meta">
        The best move over one week is often not the best over six — a hard fixture now
        with an easy run after is a bad short transfer and a good long one.
      </span>
    </div>
  );

  if (data.error) {
    return (
      <main className="wrap">
        <header className="top"><h1>FPL Optimiser</h1></header>
        <Nav current="/optimiser" />
        <div className="banner"><strong>Error:</strong> {data.error}</div>
      </main>
    );
  }

  if (!data.dream && data.reachable.length === 0) {
    return (
      <main className="wrap">
        <header className="top"><h1>FPL Optimiser</h1></header>
        <Nav current="/optimiser" />
        <div className="banner">
          <strong>Not built yet</strong>
          <p style={{ margin: "6px 0 0" }}>
            Run <code>.venv/bin/python ingest/run.py optimise</code>, or wait for the next
            scheduled ingestion.
          </p>
        </div>
      </main>
    );
  }

  if (data.stale) {
    return (
      <main className="wrap">
        <header className="top">
          <h1>FPL Optimiser</h1>
          <span className="meta">Optimiser · results out of date</span>
        </header>
        <Nav current="/optimiser" />
        {horizonToggle}
        <div className="banner">
          <strong>Your squad has changed since these were worked out</strong>
          <p style={{ margin: "6px 0 0" }}>
            The stored results were built from a different squad, so every
            recommendation below would be for a team you no longer have. They are hidden
            rather than shown, because a confident answer to the wrong question is worse
            than no answer.
          </p>
          <p style={{ margin: "6px 0 0" }}>
            The optimiser runs on a schedule, so this clears itself within a few hours.
            To refresh now:
          </p>
          <p style={{ margin: "6px 0 0" }}>
            <code>cd ~/fpl-optimiser/ingest &amp;&amp; ../.venv/bin/python run.py optimise</code>
          </p>
        </div>
      </main>
    );
  }

  const bestN = data.best?.transfers_allowed ?? 0;
  const bestNet = Number(data.best?.net_points ?? 0);

  return (
    <main className="wrap">
      <header className="top">
        <h1>FPL Optimiser</h1>
        <span className="meta">
          Optimiser · GW{gws[0]}–{gws[gws.length - 1]} · exact solve
        </span>
      </header>
      <Nav current="/optimiser" />
      {horizonToggle}

      <div className="banner">
        <strong>
          {bestN === 0
            ? "Best move: hold. No transfer pays for itself."
            : `Best move: ${bestN} transfer${bestN === 1 ? "" : "s"}, net ${bestNet >= 0 ? "+" : ""}${bestNet.toFixed(2)} points`}
        </strong>
        <p style={{ margin: "6px 0 0" }}>
          Your squad projects <strong>{data.baseline.toFixed(1)}</strong> starting-XI points
          over {gws.length} gameweek{gws.length === 1 ? "" : "s"}. The best squad buildable from a clean £100.0m projects{" "}
          <strong>{Number(data.dream?.xi_points ?? 0).toFixed(1)}</strong> — so you are within{" "}
          {(Number(data.dream?.xi_points ?? 0) - data.baseline).toFixed(1)} points of perfect,
          before any transfer costs.
        </p>
      </div>

      {(() => {
        const roles = data.best?.detail.roles ?? data.dream?.detail.roles ?? {};
        const squad = data.best?.detail.squad ?? data.dream?.detail.squad ?? [];
        const byId = new Map(squad.map((p) => [p.player_id, p]));
        const caps = gws
          .map((gw) => {
            const cid = roles[String(gw)]?.captain;
            const p = cid ? byId.get(cid) : null;
            return p ? { gw, name: p.name, team: p.team, pts: p.per_gw[String(gw)] ?? 0 } : null;
          })
          .filter(Boolean) as { gw: number; name: string; team: string; pts: number }[];
        if (!caps.length) return null;
        return (
          <>
            <h2 style={{ fontSize: 15, margin: "22px 0 8px" }}>Captain, week by week</h2>
            <p className="meta" style={{ marginTop: 0 }}>
              The captain doubles, so this is the highest-leverage call you make each week —
              and it changes, because fixtures do. Figures are the extra points captaincy
              adds on top of the player already scoring.
            </p>
            <div className="table-scroll" style={{ marginBottom: 26 }}>
              <table>
                <thead>
                  <tr>
                    <th>GW</th>
                    <th className="left">Captain</th>
                    <th className="left">Team</th>
                    <th>Their projection</th>
                    <th>Extra from the armband</th>
                  </tr>
                </thead>
                <tbody>
                  {caps.map((c) => (
                    <tr key={c.gw}>
                      <td>{c.gw}</td>
                      <td className="left"><strong>{c.name}</strong></td>
                      <td className="left">{c.team}</td>
                      <td>{c.pts.toFixed(2)}</td>
                      <td className="pos-val">+{c.pts.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        );
      })()}

      {data.chips.length > 0 ? (
        <>
          <h2 style={{ fontSize: 15, margin: "22px 0 8px" }}>Chips</h2>
          <p className="meta" style={{ marginTop: 0 }}>
            Bench Boost is worth what your bench scores; Triple Captain is worth one extra
            copy of your best single score. Wildcard and Free Hit are not planned here —
            their value depends on what you would transfer to, which is the optimiser&rsquo;s
            job, and pricing them from the current squad would mislead.
          </p>
          <div className="table-scroll" style={{ marginBottom: 26 }}>
            <table>
              <thead>
                <tr>
                  <th className="left">Chip</th>
                  <th>GW</th>
                  <th>Worth</th>
                  <th className="left">What you would be playing</th>
                  <th className="left">Best week?</th>
                </tr>
              </thead>
              <tbody>
                {data.chips
                  .slice()
                  .sort((a, b) => a.chip.localeCompare(b.chip) || a.gw - b.gw)
                  .map((c) => (
                    <tr key={`${c.chip}-${c.gw}`} className={c.is_best ? "plan-row" : ""}>
                      <td className="left">
                        {c.chip === "bboost" ? "Bench Boost" : "Triple Captain"}
                      </td>
                      <td>{c.gw}</td>
                      <td><strong>+{Number(c.value_points).toFixed(2)}</strong></td>
                      <td className="left meta">
                        {c.chip === "3xc"
                          ? `${c.detail.captain ?? "—"} (${c.detail.team ?? "—"})`
                          : (c.detail.bench ?? [])
                              .map((b) => `${b.name} ${b.points.toFixed(1)}`)
                              .join(", ")}
                      </td>
                      <td className="left">
                        {c.is_best ? <span className="pill high">best</span> : <span className="meta">—</span>}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      {data.plan.length > 0 ? (() => {
        const planTotal = data.plan.reduce((a, w) => a + Number(w.xi_points), 0);
        const holdTotal = data.plan.reduce((a, w) => a + Number(w.hold_points), 0);
        const hitTotal = data.plan.reduce((a, w) => a + w.hits, 0) * 4;
        const net = planTotal - hitTotal;
        const gain = net - holdTotal;
        return (
          <>
            <h2 style={{ fontSize: 15, margin: "22px 0 8px" }}>
              Week by week, using your free transfers
            </h2>
            <p className="meta" style={{ marginTop: 0 }}>
              One free transfer a week, banked up to five, planned across the whole
              horizon at once rather than a week at a time. A move that looks marginal
              now can be clearly worth it if it pays for five more gameweeks, and a
              transfer worth making later is worth banking for.
            </p>
            <div className="table-scroll" style={{ marginBottom: 8 }}>
              <table>
                <thead>
                  <tr>
                    <th>GW</th>
                    <th>Hold</th>
                    <th>With plan</th>
                    <th>Gain</th>
                    <th>Hit</th>
                    <th className="left">Transfers</th>
                  </tr>
                </thead>
                <tbody>
                  {data.plan.map((w) => {
                    const d = Number(w.xi_points) - Number(w.hold_points);
                    return (
                      <tr key={w.gw} className={w.transfers.length ? "plan-row" : ""}>
                        <td>{w.gw}</td>
                        <td className="meta">{Number(w.hold_points).toFixed(2)}</td>
                        <td><strong>{Number(w.xi_points).toFixed(2)}</strong></td>
                        <td className={d > 0.005 ? "pos-val" : "meta"}>
                          {d > 0.005 ? `+${d.toFixed(2)}` : "—"}
                        </td>
                        <td className={w.hits ? "neg-val" : "meta"}>
                          {w.hits ? `-${w.hits * 4}` : "0"}
                        </td>
                        <td className="left">
                          {w.transfers.length === 0 ? (
                            <span className="meta">bank the transfer</span>
                          ) : (
                            w.transfers.map((t, i) => (
                              <div key={i}>
                                {t.out} <span className="meta">({t.out_team})</span> →{" "}
                                <strong>{t.in}</strong>{" "}
                                <span className="meta">({t.in_team})</span>
                              </div>
                            ))
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="banner" style={{ marginBottom: 26 }}>
              <strong>
                Plan is worth {gain >= 0 ? "+" : ""}{gain.toFixed(2)} points over{" "}
                {data.plan.length} gameweeks against holding
              </strong>
              <p style={{ margin: "6px 0 0" }}>
                {holdTotal.toFixed(1)} holding, {net.toFixed(1)} with the plan
                {hitTotal ? ` after ${hitTotal} in hits` : ", taking no hits"}. That is{" "}
                {(gain / data.plan.length).toFixed(2)} a gameweek — inside the model&rsquo;s
                own margin of error, so treat the sequence as a direction of travel rather
                than instructions. Only the first move is worth acting on now; the rest
                will change as real results arrive.
              </p>
            </div>
          </>
        );
      })() : null}

      <h2 style={{ fontSize: 15, margin: "22px 0 8px" }}>How far is it worth going?</h2>
      <p className="meta" style={{ marginTop: 0 }}>
        Each row is a separate exact solve: the best squad reachable with at most that many
        transfers, given your bank and what your players would sell for. You have{" "}
        {data.freeTransfers} free transfer{data.freeTransfers === 1 ? "" : "s"}; every one
        beyond that costs 4 points.
      </p>
      <div className="table-scroll" style={{ marginBottom: 26 }}>
        <table>
          <thead>
            <tr>
              <th>Transfers</th>
              <th>XI points</th>
              <th>Gain</th>
              <th>Hit</th>
              <th>Net gain</th>
              <th className="left">Verdict</th>
            </tr>
          </thead>
          <tbody>
            {data.reachable.map((r) => {
              const gain = Number(r.xi_points) - data.baseline;
              const net = Number(r.net_points);
              const isBest = r.transfers_allowed === bestN;
              return (
                <tr key={r.id} className={isBest ? "plan-row" : ""}>
                  <td>{r.transfers_allowed}</td>
                  <td>{Number(r.xi_points).toFixed(1)}</td>
                  <td className={gain >= 0 ? "pos-val" : "neg-val"}>
                    {gain >= 0 ? "+" : ""}
                    {gain.toFixed(2)}
                  </td>
                  <td className={r.hit_cost ? "neg-val" : "meta"}>
                    {r.hit_cost ? `-${r.hit_cost}` : "0"}
                  </td>
                  <td>
                    <strong className={net >= 0 ? "pos-val" : "neg-val"}>
                      {net >= 0 ? "+" : ""}
                      {net.toFixed(2)}
                    </strong>
                  </td>
                  <td className="left">
                    <span className={`pill ${isBest ? "high" : net < 0 ? "low" : "medium"}`}>
                      {isBest ? "best" : net < 0 ? "loses points" : "worse"}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {data.best && bestN > 0 ? (
        <>
          <h2 style={{ fontSize: 15, margin: "22px 0 8px" }}>
            The squad after {bestN} transfer{bestN === 1 ? "" : "s"}
          </h2>
          <p className="meta" style={{ marginTop: 0 }}>
            Players marked <span className="pill medium">buy</span> are the changes. The XI
            is chosen per gameweek — a player benched one week can start the next without a
            transfer, and <span className="xi-badge starter">C</span> marks the captain.
          </p>
          <SquadTable row={data.best} gws={gws} ownedKnown />
        </>
      ) : null}

      {data.dream ? (
        <>
          <h2 style={{ fontSize: 15, margin: "26px 0 8px" }}>
            For reference: the best £100.0m squad in the game
          </h2>
          <p className="meta" style={{ marginTop: 0 }}>
            Ignoring your current team entirely. Note the bench — the optimiser deliberately
            buys the cheapest possible fourth-choice players, because bench points do not
            score and that money buys a better eleven.
          </p>
          <SquadTable row={data.dream} gws={gws} ownedKnown={false} />
        </>
      ) : null}

      <p className="meta" style={{ marginTop: 14 }}>
        Solved exactly as a mixed-integer program, not chosen greedily: budget, the
        three-per-club cap and the formation rules interact, so the best squad is not the
        best players picked one at a time. The objective is starting-XI points with
        captaincy doubled, which is what actually scores.
      </p>
    </main>
  );
}
