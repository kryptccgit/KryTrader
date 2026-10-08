// @vitest-environment node
import { generateKeyPairSync, randomUUID } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import {
  checkKalshiKeys, checkKeyId, checkPrivateKey, decodeBase64,
} from '../shared/kalshiKeys';


const D = '-'.repeat(5);
const line = (edge: string, label: string): string => `${D}${edge} ${label}${D}`;
const PK = ['PRIVATE', 'KEY'].join(' ');

const rsa1 = generateKeyPairSync('rsa', {
  modulusLength: 2048,
  privateKeyEncoding: { type: 'pkcs1', format: 'pem' },
  publicKeyEncoding: { type: 'spki', format: 'pem' },
});
const rsa8 = generateKeyPairSync('rsa', {
  modulusLength: 2048,
  privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
  publicKeyEncoding: { type: 'pkcs1', format: 'pem' },
});
const ed = generateKeyPairSync('ed25519', {
  privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
  publicKeyEncoding: { type: 'spki', format: 'pem' },
});
const ec = generateKeyPairSync('ec', {
  namedCurve: 'prime256v1',
  privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
  publicKeyEncoding: { type: 'spki', format: 'pem' },
});
const ecSec1 = generateKeyPairSync('ec', {
  namedCurve: 'prime256v1',
  privateKeyEncoding: { type: 'sec1', format: 'pem' },
  publicKeyEncoding: { type: 'spki', format: 'pem' },
});
const encrypted8 = generateKeyPairSync('rsa', {
  modulusLength: 2048,
  privateKeyEncoding: { type: 'pkcs8', format: 'pem', cipher: 'aes-256-cbc', passphrase: 'pw' },
  publicKeyEncoding: { type: 'spki', format: 'pem' },
}).privateKey;
const encrypted1 = generateKeyPairSync('rsa', {
  modulusLength: 2048,
  privateKeyEncoding: { type: 'pkcs1', format: 'pem', cipher: 'aes-256-cbc', passphrase: 'pw' },
  publicKeyEncoding: { type: 'spki', format: 'pem' },
}).privateKey;

const ID = randomUUID();
const body = (pem: string): string => pem.split('\n').filter((l) => l && !l.startsWith(D)).join('');

describe('valid keys pass unchanged', () => {
  it.each([
    ['RSA PKCS#1', rsa1.privateKey, 'rsa-pkcs1'],
    ['RSA PKCS#8', rsa8.privateKey, 'rsa-pkcs8'],
    ['Ed25519 PKCS#8 (Kalshi default)', ed.privateKey, 'ed25519'],
  ])('%s', (_n, pem, kind) => {
    const r = checkKalshiKeys({ keyId: ID, pem });
    expect(r.ok).toBe(true);
    expect(r.issues).toEqual([]);
    expect(r.kind).toBe(kind);
    expect(r.keyId).toBe(ID);
    expect(r.pem).toBe(pem.endsWith('\n') ? pem : `${pem}\n`);
    expect(r.fixes).toEqual([]);
  });
});

describe('Key ID mistakes', () => {
  it('empty', () => {
    expect(checkKeyId('   ').issue?.code).toBe('keyid_empty');
  });

  it('not UUID-shaped', () => {
    for (const bad of ['abc123', 'my-api-key', `${ID}x`, '1234']) {
      expect(checkKeyId(bad).issue?.code, bad).toBe('keyid_not_uuid');
    }
  });

  it('extra quotes and whitespace are removed and reported', () => {
    for (const raw of [`"${ID}"`, `  '${ID}'  `, `“${ID}”`, `"${ID}",`, `\`${ID}\``, `${ID}​`]) {
      const r = checkKeyId(raw);
      expect(r.issue, raw).toBeNull();
      expect(r.value).toBe(ID);
      expect(r.fixes.length).toBeGreaterThan(0);
    }
    expect(checkKeyId(`  ${ID}\n`)).toEqual({ value: ID, fixes: [], issue: null });
    expect(checkKeyId(`﻿${ID}`)).toEqual({ value: ID, fixes: [], issue: null });
  });

  it('a label around the id, a wrapped id, and lost dashes are repaired', () => {
    expect(checkKeyId(`Key ID: ${ID}`).value).toBe(ID);
    expect(checkKeyId(`KALSHI_API_KEY=${ID}`).value).toBe(ID);
    expect(checkKeyId(`${ID.slice(0, 18)}\n${ID.slice(18)}`).value).toBe(ID);
    expect(checkKeyId(ID.replace(/-/g, '')).value).toBe(ID);
  });

  it('two different ids are refused, not guessed between', () => {
    expect(checkKeyId(`${ID} ${randomUUID()}`).issue?.code).toBe('keyid_not_uuid');
  });

  it('the private key in the Key ID box', () => {
    expect(checkKeyId(rsa1.privateKey).issue?.code).toBe('keyid_is_private_key');
  });

  it('an AI provider key in the Key ID box', () => {
    expect(checkKeyId(['sk', 'ant', 'api03', 'x'.repeat(30)].join('-')).issue?.code).toBe('keyid_is_ai_key');
  });
});

describe('private key mistakes', () => {
  it('empty', () => {
    expect(checkPrivateKey('').issue?.code).toBe('pem_empty');
  });

  it('a PUBLIC key instead of the private one (SPKI, PKCS#1, OpenSSH)', () => {
    expect(checkPrivateKey(rsa1.publicKey).issue?.code).toBe('pem_public');
    expect(checkPrivateKey(rsa8.publicKey).issue?.code).toBe('pem_public');
    expect(checkPrivateKey(ed.publicKey).issue?.code).toBe('pem_public');
    expect(checkPrivateKey(`ssh-ed25519 ${'A'.repeat(68)} me@pc`).issue?.code).toBe('pem_public');
  });

  it('a password-protected key (PKCS#8 and legacy PKCS#1)', () => {
    expect(checkPrivateKey(encrypted8).issue?.code).toBe('pem_encrypted');
    expect(checkPrivateKey(encrypted1).issue?.code).toBe('pem_encrypted');
  });

  it('missing BEGIN/END lines: body alone is repaired when it decodes to a key', () => {
    for (const [pem, kind] of [[rsa1.privateKey, 'rsa-pkcs1'], [ed.privateKey, 'ed25519'], [rsa8.privateKey, 'rsa-pkcs8']] as const) {
      const r = checkPrivateKey(body(pem));
      expect(r.issue).toBeNull();
      expect(r.kind).toBe(kind);
      expect(r.pem).toBe(pem);
      expect(r.fixes.join(' ')).toMatch(/BEGIN and END/);
    }
  });

  it('missing BEGIN only, or END only (a partial copy)', () => {
    const lines = rsa1.privateKey.trim().split('\n');
    expect(checkPrivateKey(lines.slice(1).join('\n')).issue?.code).toBe('pem_no_begin');
    expect(checkPrivateKey(lines.slice(0, -1).join('\n')).issue?.code).toBe('pem_no_end');
  });

  it('random text is not a key', () => {
    expect(checkPrivateKey('hello this is my key').issue?.code).toBe('pem_no_begin');
  });

  it('mangled line breaks: CRLF, one long line, spaces, \\n escapes', () => {
    const pem = rsa1.privateKey;
    const variants = [
      pem.replace(/\n/g, '\r\n'),
      pem.replace(/\n/g, ' '),
      pem.replace(/\n/g, '\\n'),
      pem.split('\n').map((l) => `  ${l}  `).join('\n'),
      `${line('BEGIN', `RSA ${PK}`)}${body(pem)}${line('END', `RSA ${PK}`)}`,
      pem.replace(`${D}BEGIN RSA`, '----- BEGIN RSA').replace(`KEY${D}\n`, 'KEY -----\n'),
    ];
    for (const v of variants) {
      const r = checkPrivateKey(v);
      expect(r.issue, JSON.stringify(v.slice(0, 50))).toBeNull();
      expect(r.pem).toBe(pem);
    }
    expect(checkPrivateKey(pem.replace(/\n/g, '\r\n')).fixes).toEqual([]);
    expect(checkPrivateKey(pem.replace(/\n/g, ' ')).fixes.length).toBe(1);
  });

  it('extra quotes around the key', () => {
    const r = checkPrivateKey(`"${ed.privateKey.trim()}"`);
    expect(r.issue).toBeNull();
    expect(r.pem).toBe(ed.privateKey);
    expect(r.fixes.join(' ')).toMatch(/quotes/);
  });

  it('a truncated or altered body', () => {
    const pem = rsa1.privateKey;
    const lines = pem.trim().split('\n');
    const cut = [...lines.slice(0, 6), lines[lines.length - 1]].join('\n');
    expect(checkPrivateKey(cut).issue?.code).toBe('pem_truncated');
    const altered = pem.replace(/\n([A-Za-z0-9])/, '\n$1!*');
    expect(checkPrivateKey(altered).issue?.code).toBe('pem_bad_chars');
  });

  it('a key type Kalshi does not use (EC, PKCS#8 and SEC1)', () => {
    expect(checkPrivateKey(ec.privateKey).issue?.code).toBe('pem_wrong_type');
    expect(checkPrivateKey(ecSec1.privateKey).issue?.code).toBe('pem_wrong_type');
    expect(checkPrivateKey(`${line('BEGIN', `OPENSSH ${PK}`)}\nAAAA\n${line('END', `OPENSSH ${PK}`)}`).issue?.code)
      .toBe('pem_wrong_type');
  });

  it('two private keys in one paste', () => {
    expect(checkPrivateKey(rsa1.privateKey + rsa8.privateKey).issue?.code).toBe('pem_multiple');
  });

  it('a certificate alongside the key: the key is used', () => {
    const cert = `${line('BEGIN', 'CERTIFICATE')}\nAAAA\n${line('END', 'CERTIFICATE')}\n`;
    const r = checkPrivateKey(cert + ed.privateKey);
    expect(r.issue).toBeNull();
    expect(r.pem).toBe(ed.privateKey);
  });

  it('the Key ID in the private key box', () => {
    expect(checkPrivateKey(ID).issue?.code).toBe('pem_is_keyid');
  });

  it('far too big to be a key', () => {
    expect(checkPrivateKey('A'.repeat(20_000)).issue?.code).toBe('pem_too_big');
  });
});

describe('both fields', () => {
  it('Key ID and private key swapped between the boxes', () => {
    const r = checkKalshiKeys({ keyId: rsa1.privateKey, pem: ID });
    expect(r.ok).toBe(false);
    expect(r.issues.map((i) => i.code)).toEqual(['swapped']);
    expect(r.keyId).toBe('');
    expect(r.pem).toBe('');
  });

  it('reports each field\'s own issue and sends nothing for a bad field', () => {
    const r = checkKalshiKeys({ keyId: 'nope', pem: rsa1.publicKey });
    expect(r.ok).toBe(false);
    expect(r.issues.map((i) => [i.field, i.code])).toEqual([
      ['keyId', 'keyid_not_uuid'], ['privateKey', 'pem_public'],
    ]);
    expect(r.keyId).toBe('');
    expect(r.pem).toBe('');
  });

  it('never throws on hostile input', () => {
    for (const v of [null, undefined, 42, {}, [], '\u0000', `${D}BEGIN${D}`]) {
      expect(() => checkKalshiKeys({ keyId: v, pem: v })).not.toThrow();
      expect(checkKalshiKeys({ keyId: v, pem: v }).ok).toBe(false);
    }
  });
});

describe('decodeBase64', () => {
  it('matches Buffer on real data and refuses junk', () => {
    const b = body(rsa8.privateKey);
    expect(Buffer.from(decodeBase64(b)!).equals(Buffer.from(b, 'base64'))).toBe(true);
    expect(decodeBase64('abc')).toBeNull();
    expect(decodeBase64('ab!d')).toBeNull();
  });
});
