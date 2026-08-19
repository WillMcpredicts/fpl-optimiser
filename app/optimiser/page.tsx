import Nav from "../Nav";
import { loadOptimal, type OptimalRow } from "@/lib/optimal";
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

export default async function OptimiserPage() {
  const data = await loadOptimal();
  const gws = data.gameweeks;

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

      <div className="banner">
        <strong>
          {bestN === 0
            ? "Best move: hold. No transfer pays for itself."
            : `Best move: ${bestN} transfer${bestN === 1 ? "" : "s"}, net ${bestNet >= 0 ? "+" : ""}${bestNet.toFixed(2)} points`}
        </strong>
        <p style={{ margin: "6px 0 0" }}>
          Your squad projects <strong>{data.baseline.toFixed(1)}</strong> starting-XI points
          over {gws.length} gameweeks. The best squad buildable from a clean £100.0m projects{" "}
          <strong>{Number(data.dream?.xi_points ?? 0).toFixed(1)}</strong> — so you are within{" "}
          {(Number(data.dream?.xi_points ?? 0) - data.baseline).toFixed(1)} points of perfect,
          before any transfer costs.
        </p>
      </div>

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
