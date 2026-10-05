import type { StrategyPreset, TraderConfig } from '../../shared/types';
import { DEFAULT_CONFIG } from './settings-store';

const merge = (over: Partial<TraderConfig>): TraderConfig => ({
  ...DEFAULT_CONFIG,
  ...over,
});

export const BUILTIN_STRATEGIES: StrategyPreset[] = [
  {
    id: 'krypt-edge',
    name: 'Edge Stack',
    tagline: 'Both backtested edges at once — crypto whales + sports momentum.',
    description:
      "EXPERIMENTAL — a later audit over 13,700 resolved signals measured this preset's whale leg net-NEGATIVE after fees (crypto whales underperform their own entry price) and its momentum leg at exactly zero. The early +15.6¢ result (n=81) did not survive the larger sample. Kept for experimentation only; do not size real money on it, and paper-trade anything before arming.",
    riskLabel: 'experimental',
    backtest: null,
    config: merge({
      tradeWhales: true,
      tradeMomentum: true,
      contrarianOnly: true,
      allowedCategories: null,
      allowedWhaleCategories: ['crypto', 'exotics', 'entertainment'],
      allowedMomentumCategories: ['sports'],
      allowedMomentumSignalTypes: ['trade_cluster'],
      minConfidenceWhale: 55.0,
      minEdgePtsWhale: 5.0,
      minConfidenceMomentum: 40.0,
      minEntryPriceCents: 15,
      maxEntryPriceCents: 85,
    }),
  },
  {
    id: 'krypt-sports-momentum',
    name: 'Sports Momentum',
    tagline: 'Contrarian trade-clusters, sports only.',
    description:
      "Highest raw edge, but noisier (single category, smaller sample). Contrarian momentum in SPORTS backtested strongly positive net-of-fee while news/world momentum lost. Fixed from the old preset: confidence ≥ 40 (the old 50 gate cut the edge to noise — momentum scores top out near 60) and a wider 15-70¢ band. In-sample +18.2¢/contract (t=2.2, n=37). EXPERIMENTAL / in-sample — paper-trade to confirm.",
    riskLabel: 'experimental',
    badge: 'new',
    backtest: { netCents: 18.2, t: 2.2, n: 37 },
    config: merge({
      tradeWhales: false,
      tradeMomentum: true,
      contrarianOnly: true,
      allowedCategories: ['sports'],
      allowedMomentumSignalTypes: ['trade_cluster'],
      minConfidenceMomentum: 40.0,
      minEntryPriceCents: 15,
      maxEntryPriceCents: 70,
    }),
  },
  {
    id: 'krypt-crypto-whale',
    name: 'Crypto Whale',
    tagline: 'Whale-following, crypto markets only.',
    description:
      "Most reliable edge (highest t-stat, 97% win). Whale signals in CRYPTO backtested strongly positive net-of-fee while sports whales lost. Fixed from the old preset: the entry cap is raised to 98¢ because crypto whales follow high-price favorites — the old 85¢ cap was throwing away most of its own edge — and the edge gate is lowered to 2pts, because the scorer caps confidence at 97 so above ~92¢ the computable edge shrinks toward zero (a 5pt gate silently re-capped entries at 92¢). In-sample +9.3¢/contract (t=3.5, n=36). EXPERIMENTAL / in-sample on a small sample — paper-trade to confirm.",
    riskLabel: 'experimental',
    badge: 'new',
    backtest: { netCents: 9.3, t: 3.5, n: 36 },
    config: merge({
      tradeWhales: true,
      tradeMomentum: false,
      allowedCategories: ['crypto'],
      minConfidenceWhale: 55.0,
      minEdgePtsWhale: 2.0,
      minEntryPriceCents: 15,
      maxEntryPriceCents: 98,
    }),
  },
];

export const SECRET_STRATEGY: StrategyPreset = {
  id: 'krypt-secret',
  name: 'Secret Strategy',
  tagline: 'Pure chaos. Every signal, 10% chance, no rules.',
  description:
    "🎰 NOT a real strategy — it's a coin-flip for fun. Ignores EVERY gate: any whale or momentum signal, any confidence, any edge, any category, any price gets a flat 10% random roll to trade. No skill, no backtest, pure gambling. The Visualizer turns into a roulette wheel. Only turn this on with money you're happy to throw away.",
  riskLabel: 'aggressive',
  badge: 'new',
  secret: true,
  backtest: null,
  config: merge({
    tradeWhales: true,
    tradeMomentum: true,
    contrarianOnly: false,
    gamblingMode: true,
    gamblingTradeProbability: 0.10,
    allowedCategories: null,
    allowedWhaleCategories: null,
    allowedMomentumCategories: null,
    allowedMomentumSignalTypes: ['trade_cluster'],
    minConfidenceWhale: 0,
    minConfidenceMomentum: 0,
    minEdgePtsWhale: -1000,
    minEdgePtsMomentum: -1000,
    minEntryPriceCents: 1,
    maxEntryPriceCents: 99,
  }),
};

const ALL_STRATEGIES: StrategyPreset[] = [...BUILTIN_STRATEGIES, SECRET_STRATEGY];

export function listStrategies(): StrategyPreset[] {
  return ALL_STRATEGIES;
}

export function findStrategy(id: string): StrategyPreset | undefined {
  return ALL_STRATEGIES.find((s) => s.id === id);
}
