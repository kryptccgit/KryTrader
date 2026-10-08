
export const KALSHI_REFERRAL_URL =
  'https://kalshi.com/sign-up/?referral=b1483a75-2984-48c0-87d4-42a1d4714e78';

let referralCache: string | null = null;

export async function getKalshiReferralUrl(): Promise<string> {
  if (referralCache) return referralCache;
  try {
    const url = await window.krypt.app.getReferralUrl();
    if (url) referralCache = url;
  } catch {
  }
  return referralCache ?? KALSHI_REFERRAL_URL;
}

export async function openKalshiReferral(): Promise<void> {
  await window.krypt.app.openExternal(await getKalshiReferralUrl());
}

export const KALSHI_API_KEYS_URL = 'https://kalshi.com/account/profile';

export const GUIDE_VIDEO_URL = 'https://www.youtube.com/watch?v=TI1jwNCAOkw';

export const KRYPT_HOME = 'https://krypt.cc';
export const KRYPT_TOOLS = 'https://krypt.cc/tools';
export const KRYPT_TRADER_PAGE = 'https://krypt.cc/tools/trader';
export const KRYPT_DISCORD = 'https://discord.gg/muzFKR657F';

export const REFERRAL_BLURB = 'Get $25 free after your first deposit using our referral.';
