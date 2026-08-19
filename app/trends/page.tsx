import Nav from "../Nav";

export default function Page() {
  return (
    <main className="wrap">
      <header className="top">
        <h1>FPL Optimiser</h1>
        <span className="meta">Trends · arrives in Phase 2</span>
      </header>
      <Nav current="/trends" />
      <div className="banner">
        <strong>Not built yet — Phase 2</strong>
        <p style={{ margin: "6px 0 0" }}>Team-level trends from the trend engine, each with its confidence tier, sample size and rate against the league average.</p>
      </div>
    </main>
  );
}
