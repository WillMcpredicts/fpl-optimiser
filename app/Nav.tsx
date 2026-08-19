export default function Nav({ current }: { current: string }) {
  const tabs = [
    ["/", "Predicted points"],
    ["/squad", "Squad"],
    ["/transfers", "Transfers"],
    ["/optimiser", "Optimiser"],
    ["/trends", "Trends"],
  ];
  return (
    <nav className="tabs">
      {tabs.map(([href, label]) => (
        <a key={href} href={href} aria-current={href === current ? "page" : undefined}>
          {label}
        </a>
      ))}
    </nav>
  );
}
