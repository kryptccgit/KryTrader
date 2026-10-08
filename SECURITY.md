# Security Policy

## Supported versions

Only the **latest release** receives security fixes. If you're on an older
version, update first and check whether the issue still reproduces.

## Reporting a vulnerability

Please report vulnerabilities **privately** via GitHub's
**"Report a vulnerability"** button on this repository's **Security** tab
(GitHub Security Advisories). **Do not open a public issue** for security
problems — the app places real orders with real money, and public disclosure
before a fix puts users at risk.

We'll acknowledge reports as quickly as we can and coordinate disclosure with
you once a fix ships.

## Scope

In scope:

- the desktop app (Electron main/renderer, IPC surface);
- the Python backend (order placement, credential storage/encryption);
- the user-script sandbox (escapes, or ways a sandboxed script can reach
  credentials, the filesystem, or the network);
- **remote control** (Discord/Telegram) — anything that lets a party other than
  the paired account read your positions or move money: pairing or identity
  spoofing, acting on a group/guild message rather than a direct one, bypassing
  the trade confirmation, or replaying a confirmation code;
- **credential leakage into logs** — a secret that reaches `backend.log` past
  the scrubber, since users are asked to share logs when reporting bugs;
- **server-side request forgery** — any path where a caller-supplied value
  decides which host the backend contacts.

Out of scope: issues that require "trusted" script mode (it intentionally runs
un-sandboxed Python — see the [Disclaimer](DISCLAIMER.md)), and vulnerabilities
in Kalshi's own platform (report those to Kalshi).
