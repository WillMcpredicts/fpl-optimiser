import Nav from "../Nav";

export default function Page() {
  return (
    <main className="wrap">
      <header className="top">
        <h1>FPL Optimiser</h1>
        <span className="meta">Transfers · arrives in Phase 3</span>
      </header>
      <Nav current="/transfers" />
      <div className="banner">
        <strong>Not built yet — Phase 3</strong>
        <p style={{ margin: "6px 0 0" }}>Ranked transfer options across a 3-gameweek horizon, each showing net points gain after any -4 hit.</p>
      </div>
    </main>
  );
}
