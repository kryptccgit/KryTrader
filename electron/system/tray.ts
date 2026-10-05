import { app, Menu, Tray, nativeImage } from 'electron';
import { join } from 'node:path';
import { existsSync } from 'node:fs';

let tray: Tray | null = null;

interface TrayHandlers {
  openWindow: () => void;
  toggleTrading: () => void;
  isTrading: () => boolean;
  quit: () => void;
}

function iconPath(): string {
  const file = process.platform === 'win32' ? 'krypt.ico' : 'krypt.png';
  const candidates = [
    app.isPackaged
      ? join(process.resourcesPath, 'app.asar.unpacked', 'resources', file)
      : join(process.cwd(), 'resources', file),
    app.isPackaged ? join(process.resourcesPath, file) : join(process.cwd(), 'resources', file),
    join(__dirname, '..', 'resources', file),
    join(__dirname, '..', 'resources', 'krypt.png'),
    join(process.cwd(), 'resources', 'krypt.png'),
  ];
  for (const c of candidates) {
    if (existsSync(c)) return c;
  }
  return candidates[candidates.length - 1];
}

function trayImage(): Electron.NativeImage {
  const img = nativeImage.createFromPath(iconPath());
  if (img.isEmpty()) return img;
  if (process.platform === 'win32') return img;
  const size = process.platform === 'darwin' ? 18 : 22;
  const scaled = img.resize({ width: size, height: size, quality: 'best' });
  if (process.platform === 'darwin') scaled.setTemplateImage(true);
  return scaled;
}

export function installTray(handlers: TrayHandlers): Tray {
  if (tray && !tray.isDestroyed()) return tray;
  const img = trayImage();
  tray = new Tray(img.isEmpty() ? nativeImage.createEmpty() : img);
  if (img.isEmpty() && process.platform === 'darwin') tray.setTitle('KT');
  tray.setToolTip('Krypt Trader');
  tray.on('click', () => handlers.openWindow());
  tray.on('double-click', () => handlers.openWindow());
  rebuild(handlers);
  return tray;
}

export function rebuild(handlers: TrayHandlers): void {
  if (!tray) return;
  const trading = handlers.isTrading();
  const menu = Menu.buildFromTemplate([
    { label: 'Open Krypt Trader', click: () => handlers.openWindow() },
    { type: 'separator' },
    {
      label: trading ? 'Pause Trading' : 'Resume Trading',
      click: () => handlers.toggleTrading(),
    },
    { type: 'separator' },
    { label: 'Quit', click: () => handlers.quit() },
  ]);
  tray.setContextMenu(menu);
}

export function destroyTray(): void {
  if (tray && !tray.isDestroyed()) tray.destroy();
  tray = null;
}
