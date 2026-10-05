
import type { Client as RpcClient, Presence } from 'discord-rpc';

const CLIENT_ID = '1495323918234423406';

let client: RpcClient | null = null;
let started = false;
let connected = false;

export async function startDiscordRpc(): Promise<void> {
  if (started) return;
  started = true;
  try {
    const { Client } = await import('discord-rpc');
    client = new Client({ transport: 'ipc' });
    client.on('ready', () => {
      connected = true;
      const activity: Presence = {
        details: 'Auto-trading on Kalshi',
        state: 'krypt.cc/tools/trader',
        startTimestamp: Date.now(),
        largeImageKey: 'krypt',
        largeImageText: 'Krypt Trader',
        instance: false,
        buttons: [
          { label: 'Free Tools', url: 'https://krypt.cc/tools' },
          { label: 'Krypt.cc', url: 'https://discord.gg/muzFKR657F' },
        ],
      };
      try {
        client?.setActivity(activity);
      } catch {
      }
    });
    await client.login({ clientId: CLIENT_ID }).catch(() => {
    });
  } catch {
  }
}

export function stopDiscordRpc(): void {
  if (!client) return;
  try {
    client.clearActivity();
  } catch {
  }
  try {
    client.destroy();
  } catch {
  }
  client = null;
  connected = false;
  started = false;
}

export function isDiscordConnected(): boolean {
  return connected;
}
