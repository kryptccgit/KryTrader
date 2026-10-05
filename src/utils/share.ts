
export const X_PROFILE = '@YuhgoSlavia';
export const X_PROFILE_URL = 'https://x.com/YuhgoSlavia';

export async function shareToX(text: string): Promise<void> {
  const url = `https://x.com/intent/post?text=${encodeURIComponent(text)}`;
  try {
    await window.krypt.app.openExternal(url);
  } catch {
    try { window.open(url, '_blank'); } catch {   }
  }
}

export async function followYuhgo(): Promise<void> {
  try {
    await window.krypt.app.openExternal(X_PROFILE_URL);
  } catch {
    try { window.open(X_PROFILE_URL, '_blank'); } catch {   }
  }
}
