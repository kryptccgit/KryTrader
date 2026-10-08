import { app, safeStorage } from 'electron';
import { createDecipheriv, createCipheriv, randomBytes, randomInt } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { REFERRAL_POOL_ENC } from './referral-pool.gen';


const POOL_KEY_HEX =
  'c1b7e69a4d20f3585b8e17d2a94c6e0f7d31a8c25e94b06fd8427c1a90e5b3f6';

const FALLBACK_URL =
  'https://kalshi.com/sign-up/?referral=b1483a75-2984-48c0-87d4-42a1d4714e78';

const VALID_RE = /^https:\/\/kalshi\.com\/(r\/[\w-]+|sign-up\/?\?referral=[\w-]+)$/i;

const chosenFile = (): string => join(app.getPath('userData'), 'referral.dat');

let memo: string | null = null;

function aesDecrypt(blobB64: string): string {
  const raw = Buffer.from(blobB64, 'base64');
  const d = createDecipheriv(
    'aes-256-gcm', Buffer.from(POOL_KEY_HEX, 'hex'), raw.subarray(0, 12),
  );
  d.setAuthTag(raw.subarray(12, 28));
  return Buffer.concat([d.update(raw.subarray(28)), d.final()]).toString('utf-8');
}

function aesEncrypt(plain: string): string {
  const iv = randomBytes(12);
  const c = createCipheriv('aes-256-gcm', Buffer.from(POOL_KEY_HEX, 'hex'), iv);
  const ct = Buffer.concat([c.update(plain, 'utf-8'), c.final()]);
  return Buffer.concat([iv, c.getAuthTag(), ct]).toString('base64');
}

function readChosen(): string | null {
  const f = chosenFile();
  if (!existsSync(f)) return null;
  let rec: { enc?: string; data?: string; aes?: string };
  try {
    rec = JSON.parse(readFileSync(f, 'utf-8'));
  } catch {
    return null;
  }
  for (const attempt of [
    () => (rec.enc === 'os' && rec.data
      ? safeStorage.decryptString(Buffer.from(rec.data as string, 'base64')) : null),
    () => (rec.enc === 'aes' && rec.data ? aesDecrypt(rec.data as string) : null),
    () => (rec.aes ? aesDecrypt(rec.aes as string) : null),
  ]) {
    try {
      const url = attempt();
      if (url && VALID_RE.test(url)) return url;
    } catch {   }
  }
  return null;
}

function writeChosen(url: string): void {
  const f = chosenFile();
  try { mkdirSync(app.getPath('userData'), { recursive: true }); } catch {   }
  const os = safeStorage.isEncryptionAvailable();
  const rec = {
    enc: os ? 'os' : 'aes',
    data: os
      ? safeStorage.encryptString(url).toString('base64')
      : aesEncrypt(url),
    aes: aesEncrypt(url),
  };
  const tmp = `${f}.tmp`;
  writeFileSync(tmp, JSON.stringify(rec), 'utf-8');
  renameSync(tmp, f);
}

function pickFromPool(): string {
  const pool = (JSON.parse(aesDecrypt(REFERRAL_POOL_ENC)) as string[])
    .filter((u) => VALID_RE.test(u));
  if (pool.length === 0) return FALLBACK_URL;
  return pool[pool.length === 1 ? 0 : randomInt(pool.length)];
}

export function getReferralUrl(): string {
  if (memo) return memo;
  try {
    const existing = readChosen();
    if (existing) {
      memo = existing;
      return memo;
    }
    const picked = pickFromPool();
    memo = picked;
    try {
      writeChosen(picked);
    } catch {   }
    return memo;
  } catch {
    return FALLBACK_URL;
  }
}
