import { useState } from 'react';
import { Copy, Globe } from 'lucide-react';
import type { McpStatus } from '@shared/market';
import type { TraderConfig } from '@shared/types';
import { Card, Switch } from './common';
import { useToast } from '../state/ToastProvider';
import { userMessage } from '../utils/errors';

export function HttpApiCard({
  config, status, patch,
}: {
  config: TraderConfig | null;
  status: McpStatus | null;
  patch: (p: Record<string, unknown>) => Promise<void>;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const port = status?.port ?? config?.mcpPort ?? 47821;
  const serverOn = !!config?.mcpEnabled;
  const apiOn = serverOn && !!config?.mcpHttpEnabled;
  const base = `http://127.0.0.1:${port}/api/v1`;

  const copy = async (): Promise<void> => {
    setBusy(true);
    try {
      await window.krypt.terminal.mcpCopyHttpSnippet({ agentId: 'default' });
      toast.success('curl and Python examples copied. They contain your agent token — treat it like a password.');
    } catch (e) {
      toast.error(userMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="mt-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium text-white">
            <Globe className="h-4 w-4 text-krypt-muted" /> HTTP API
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-krypt-muted">
            For scripts, n8n, LangChain or your own bot. Same port and token as MCP, and every
            call runs through the same rails: trade mode, a forecast before every buy, caps,
            approvals and the daily loss stop. Callers show up in activity as{' '}
            <span className="font-mono text-white/80">http:&lt;user-agent&gt;</span>.
          </p>
        </div>
        <button
          onClick={() => void copy()}
          disabled={!apiOn || busy}
          className="krypt-btn-default shrink-0"
          title={apiOn ? 'Copy curl + Python examples' : 'Turn on the HTTP API first'}
        >
          <Copy className="h-4 w-4" /> Copy curl + Python
        </button>
      </div>
      <div className="mt-3">
        <Switch
          checked={apiOn}
          onChange={(v) => void patch({ mcpHttpEnabled: v })}
          label="Enable the HTTP API"
          description="Off by default, separately from MCP. Loopback only; the token is required on every request."
          disabled={!serverOn}
        />
      </div>
      <div className="mt-3 space-y-1 rounded-lg border border-krypt-border bg-krypt-surface2 p-3 font-mono text-[11px] text-krypt-muted">
        <div><span className="text-krypt-win">GET </span> {base}/tools</div>
        <div><span className="text-krypt-warn">POST</span> {base}/tools/<span className="text-white/80">{'{name}'}</span> <span className="font-sans text-krypt-dim">— JSON arguments in the body</span></div>
        <div><span className="text-krypt-win">GET </span> {base}/openapi.json <span className="font-sans text-krypt-dim">— import into LangChain / n8n</span></div>
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-krypt-dim">
        A refusal comes back as JSON with the same reason an MCP client reads (422; 404 for a tool
        that is unknown or switched off; 401 without the token). Every HTTP caller shares the one
        agent token, so they share one agent book: any of them may sell or cancel what an agent
        opened, and none of them can touch yours.
      </p>
    </Card>
  );
}
