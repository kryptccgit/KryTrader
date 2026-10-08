import { describe, expect, it } from 'vitest';
import { encodeRpcError, parseErrorText } from '@shared/errors';
import { errorCode, isModeMismatch, userMessage } from '../src/utils/errors';


const wrap = (channel: string, msg: string): Error =>
  new Error(`Error invoking remote method '${channel}': Error: ${msg}`);

describe('parseErrorText', () => {
  it('strips the invoke wrapper and JS/Python class names', () => {
    expect(parseErrorText("Error invoking remote method 'terminal:submit': Error: ValueError: count must be at least 1"))
      .toEqual({ code: null, message: 'count must be at least 1' });
    expect(parseErrorText('RuntimeError: boom').message).toBe('boom');
    expect(parseErrorText('KalshiAPIException: nope').message).toBe('nope');
  });

  it('round-trips a code through main\'s encoder', () => {
    const raw = `Error invoking remote method 'terminal:submit': Error: ${encodeRpcError('The app is Live now.', 'mode_mismatch')}`;
    expect(parseErrorText(raw)).toEqual({ code: 'mode_mismatch', message: 'The app is Live now.' });
  });

  it('the encoder never lets a junk code in', () => {
    expect(encodeRpcError('x', 'has spaces')).toBe('x');
    expect(encodeRpcError('x', null)).toBe('x');
    expect(encodeRpcError('', 'ok_code')).toBe('[ok_code] The backend refused that.');
  });
});

describe("the backend's own mode-mismatch refusal", () => {
  it('is recognised by its words, whether thrown or returned as {ok:false}', () => {
    const msg = 'Not sent: this ticket was filled in on PAPER, but the app is now on LIVE. Check the ticket and send it again.';
    expect(isModeMismatch({ ok: false, message: msg })).toBe(true);
    expect(isModeMismatch(wrap('terminal:submit', `[RuntimeError] ${msg}`))).toBe(true);
    expect(userMessage(wrap('terminal:submit', `[ValueError] ${msg}`))).toBe(msg);
  });
});

describe('userMessage', () => {
  it('shows the backend\'s own sentence without the plumbing', () => {
    const m = userMessage(wrap('terminal:submit', 'ValueError: That market is closed.'));
    expect(m).toBe('That market is closed.');
    expect(m).not.toMatch(/invoking|ValueError|Error:/);
  });

  it('turns known codes and transport failures into plain words', () => {
    expect(userMessage(wrap('x', '[no_credentials] KeyError: production'))).toMatch(/No Kalshi key is saved/);
    expect(userMessage(wrap('x', 'RPC terminalSubmit timed out after 45000ms'))).toMatch(/took too long/);
    expect(userMessage(wrap('x', 'backend exited'))).toMatch(/Restart in the top bar/);
    expect(userMessage(wrap('x', 'unknown method: mcpAgentClosePaper'))).toMatch(/can't do that yet/);
    expect(userMessage(wrap('x', "[backend_down] The trading engine isn't running, so the app can't load markets right now.")))
      .toBe("The trading engine isn't running, so the app can't load markets right now.");
  });

  it('handles strings, plain objects and nothing', () => {
    expect(userMessage('Error: plain')).toBe('plain');
    expect(userMessage({ message: 'obj' })).toBe('obj');
    expect(userMessage(undefined, 'fallback')).toBe('fallback');
    expect(userMessage(new Error(''), 'fallback')).toBe('fallback');
  });

  it('spots a Paper/Live mismatch thrown or returned', () => {
    expect(isModeMismatch(wrap('terminal:submit', '[mode_mismatch] priced on Paper'))).toBe(true);
    expect(isModeMismatch({ ok: false, code: 'mode_mismatch', message: 'x' })).toBe(true);
    expect(isModeMismatch({ ok: false, message: 'x' })).toBe(false);
    expect(errorCode(wrap('x', 'no code here'))).toBeNull();
  });
});
