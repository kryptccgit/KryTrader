import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, FlaskConical, Gauge, Orbit, Plug, Search } from 'lucide-react';
import type { ForecastScoreboard, ForecasterScore, McpActivity, McpTradeMode } from '@shared/market';
import { ConnectAgent } from './ConnectAgent';
import { activityBus, type ActivityRecord, type AgentCallActivity } from '../state/activity';
import { useApp } from '../state/AppStateProvider';
import { configuredAgents, hubAgentIdentity, tagLabel } from '../utils/agents';
import { cls, fmtUsd } from '../utils/format';


const FEED_MAX = 7;
const FEED_WINDOW_MS = 30 * 60_000;

function useAgentCalls(): { rec: ActivityRecord; ev: AgentCallActivity }[] {
  const pick = (rs: ActivityRecord[]) => rs
    .filter((r) => r.ev.kind === 'agentCall' && r.ev.call === 'call')
    .slice(-FEED_MAX)
    .reverse()
    .map((rec) => ({ rec, ev: rec.ev as AgentCallActivity }));
  const [rows, setRows] = useState(() => pick(activityBus.recent(FEED_WINDOW_MS)));
  useEffect(() => activityBus.subscribe((r) => {
    if (r.ev.kind === 'agentCall') setRows(pick(activityBus.recent(FEED_WINDOW_MS)));
  }), []);
  return rows;
}

function ago(at: number): string {
  const s = Math.max(0, Math.round((Date.now() - at) / 1000));
  return s < 60 ? `${s}s` : s < 3600 ? `${Math.round(s / 60)}m` : `${Math.round(s / 3600)}h`;
}

function Stage({ n, icon: Icon, title, children, tone }: {
  n: number; icon: React.ComponentType<{ className?: string }>; title: string;
  children: React.ReactNode; tone?: 'done' | 'live' | 'idle';
}) {
  return (
    <div className={cls(
      'flex min-w-0 flex-col rounded-xl border p-3',
      tone === 'done' ? 'border-krypt-win/30 bg-krypt-win/[0.04]'
        : tone === 'live' ? 'border-krypt-purple/40 bg-krypt-purple/[0.06]'
          : 'border-krypt-border bg-krypt-surface2',
    )}>
      <div className="mb-2 flex items-center gap-2">
        <span className="grid h-5 w-5 place-items-center rounded-full bg-white/10 font-mono text-[10px] text-white">{n}</span>
        <Icon className="h-3.5 w-3.5 text-krypt-purple" />
        <span className="text-xs font-semibold uppercase tracking-wider text-white">{title}</span>
      </div>
      {children}
    </div>
  );
}

export function AgentFlow({
  board, activity, mode, onAutopilot, onHub, clientsSeen,
}: {
  board: ForecastScoreboard | null;
  activity: McpActivity | null;
  mode: McpTradeMode;
  clientsSeen: string[];
  onAutopilot: () => void;
  onHub: () => void;
}) {
  const calls = useAgentCalls();
  const { config } = useApp();
  const agents = useMemo(() => configuredAgents(config), [config]);
  const paper = activity?.paper ?? null;
  const paperOrders = (activity?.orders ?? []).filter((o) => o.mode === 'paper');
  const fills = paperOrders.filter((o) => o.ok).length;
  const forecasters: ForecasterScore[] = board?.byForecaster ?? [];
  const connected = clientsSeen.length > 0 || calls.length > 0;

  return (
    <div className="mb-6 grid gap-3 lg:grid-cols-[1.35fr_1fr]">
      <Stage n={1} icon={Plug} title="Connect your agent" tone={connected ? 'done' : 'live'}>
        <ConnectAgent onAutopilot={onAutopilot} />
      </Stage>

      <Stage n={2} icon={Search} title="Watch it research" tone={calls.length ? 'live' : 'idle'}>
        {calls.length === 0 ? (
          <p className="text-[11px] leading-relaxed text-krypt-muted">
            Every tool call your agent makes shows up here as it happens — the markets it reads,
            the forecasts it commits to, and every time a rail says no.
          </p>
        ) : (
          <ul className="space-y-1">
            {calls.map(({ rec, ev }) => {
              const id = hubAgentIdentity(ev, agents);
              return (
                <li key={rec.seq} className="flex items-baseline gap-2 text-[11px]">
                  <span className="h-2 w-2 shrink-0 translate-y-[1px] rounded-full" style={{ background: id.color }} />
                  <span className="shrink-0 text-krypt-muted">{tagLabel(id)}</span>
                  <span className={cls('min-w-0 truncate font-mono',
                    ev.outcome === 'ok' ? 'text-white/90' : 'text-krypt-warn')}
                  title={ev.reason ?? undefined}>
                    {ev.outcome === 'ok' ? ev.summary : `refused: ${ev.reason ?? ev.summary}`}
                  </span>
                  <span className="ml-auto shrink-0 font-mono text-[10px] text-krypt-dim">{ago(rec.at)}</span>
                </li>
              );
            })}
          </ul>
        )}
        <button type="button" onClick={onHub} className="krypt-btn-ghost mt-2 self-start text-xs">
          <Orbit className="h-3.5 w-3.5" /> Watch it in the Agent Hub <ArrowRight className="h-3 w-3" />
        </button>
      </Stage>

      <Stage n={3} icon={FlaskConical} title="It trades on paper" tone={fills ? 'live' : 'idle'}>
        <p className="text-[11px] leading-relaxed text-krypt-muted">
          {mode === 'paper' && <>Agent trading is <span className="text-white">paper</span>: real order books, imaginary money. </>}
          {mode === 'off' && <>Agent trading is <span className="text-white">read-only</span> — switch to Paper below to let it practise. </>}
          {mode === 'live' && <span className="text-krypt-loss">Agent trading is LIVE: orders spend your real balance. </span>}
          Every buy needs a forecast that beats the price after fees.
        </p>
        <div className="mt-2 grid grid-cols-3 gap-2 text-center">
          <Mini label="paper fills" value={paperOrders.length ? String(fills) : '—'} />
          <Mini label="refused" value={paperOrders.length ? String(paperOrders.length - fills) : '—'} />
          <Mini label="realised" value={paper && fills > 0 ? fmtUsd(paper.realizedUsd, { sign: true }) : '—'} />
        </div>
      </Stage>

      <Stage n={4} icon={Gauge} title="Does it beat the market?" tone={forecasters.some((f) => f.nPaired) ? 'live' : 'idle'}>
        {forecasters.length === 0 ? (
          <p className="text-[11px] leading-relaxed text-krypt-muted">
            Each forecast is scored against the market price at that moment, once the market
            settles (Brier, lower is better). Until enough settle, nobody — your agent included —
            has shown an edge.
          </p>
        ) : (
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-krypt-dim">
                <th className="pb-1 text-left font-normal">Forecaster</th>
                <th className="pb-1 text-right font-normal">settled</th>
                <th className="pb-1 text-right font-normal">Brier</th>
                <th className="pb-1 text-right font-normal">vs market</th>
              </tr>
            </thead>
            <tbody>
              {forecasters.slice(0, 5).map((f) => {
                const id = hubAgentIdentity(f, agents);
                const skill = f.skill;
                return (
                  <tr key={`${f.source}|${f.client}|${f.model}|${f.agentId ?? ''}`}>
                    <td className="py-0.5 text-white/90">
                      <span className="mr-1.5 inline-block h-2 w-2 rounded-full" style={{ background: id.color }} />
                      {tagLabel(id)}
                    </td>
                    <td className="py-0.5 text-right font-mono text-krypt-muted">{f.nPaired}</td>
                    <td className="py-0.5 text-right font-mono">{f.brierAiPaired === null ? '—' : f.brierAiPaired.toFixed(3)}</td>
                    <td className={cls('py-0.5 text-right font-mono',
                      skill === null ? 'text-krypt-dim' : skill > 0 ? 'text-krypt-win' : 'text-krypt-loss')}>
                      {skill === null ? '—' : `${skill > 0 ? '+' : ''}${(skill * 100).toFixed(1)}%`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {board && board.overall.verdict === 'too-few' && forecasters.length > 0 && (
          <p className="mt-1 text-[10px] text-krypt-dim">
            {board.overall.nPaired} of {board.minScored} settled markets needed before anyone can say.
          </p>
        )}
      </Stage>
    </div>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-1 py-1.5">
      <div className="font-mono text-sm text-white">{value}</div>
      <div className="text-[10px] text-krypt-dim">{label}</div>
    </div>
  );
}
