const WORDS: Record<string, [string, string]> = {
  bot_positions: ['bot trade', 'bot trades'],
  bot_runs: ['bot session', 'bot sessions'],
  pnl_snapshots: ['balance snapshot', 'balance snapshots'],
  daily_stats: ['daily total', 'daily totals'],
  order_events: ['order log entry', 'order log entries'],
  alerts: ['momentum signal', 'momentum signals'],
  whale_trades: ['whale signal', 'whale signals'],
  crypto15m_positions: ['15-minute crypto trade', '15-minute crypto trades'],
  crypto15m_signals: ['15-minute crypto signal', '15-minute crypto signals'],
  crypto15m_ticks: ['15-minute price sample', '15-minute price samples'],
  perp_farm_fills: ['perpetuals fill', 'perpetuals fills'],
  terminal_rules: ['standing instruction', 'standing instructions'],
  paper_fills: ['paper fill', 'paper fills'],
  paper_orders: ['paper order', 'paper orders'],
  mcp_orders: ['AI agent order', 'AI agent orders'],
  mcp_actions: ['AI agent action', 'AI agent actions'],
  autopilot_runs: ['Autopilot run', 'Autopilot runs'],
  markets: ['cached market', 'cached markets'],
  events: ['cached event', 'cached events'],
  trades: ['cached trade', 'cached trades'],
  market_snapshots: ['market snapshot', 'market snapshots'],
};

export function resetSummaryWords(deleted: Record<string, unknown> | null | undefined): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(deleted ?? {})) {
    if (k.startsWith('_')) continue;
    const n = Number(v);
    if (!Number.isFinite(n) || n <= 0) continue;
    const w = WORDS[k] ?? [k.replace(/_/g, ' '), k.replace(/_/g, ' ')];
    parts.push(`${n.toLocaleString()} ${n === 1 ? w[0] : w[1]}`);
  }
  if (!parts.length) return 'nothing';
  if (parts.length === 1) return parts[0];
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
}
