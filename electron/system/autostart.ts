import { app } from 'electron';

export function setStartWithWindows(enabled: boolean): void {
  if (process.platform !== 'win32') return;
  try {
    if (enabled) {
      app.setLoginItemSettings({
        openAtLogin: true,
        path: process.execPath,
        args: ['--autostart'],
      });
    } else {
      app.setLoginItemSettings({ openAtLogin: false });
    }
  } catch {
  }
}
