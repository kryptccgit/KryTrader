import { describe, expect, it } from 'vitest';
import { PERSONAS, PERSONA_BY_ID, agentPersona, type Topic } from '../src/hub/engine/npcs';
import { GOODBYE, Talk } from '../src/hub/engine/dialogue';


const CREW = ['Ada', 'Rui', 'Bo', 'Kit', 'Quinn', 'Nova', 'Tess', 'Max', 'Goldie', 'Penny', 'Rex', 'Gus', 'Ivy'];

function allLines(): string[] {
  const out: string[] = [];
  const walk = (ts: Topic[]) => ts.forEach((t) => { out.push(t.ask, ...t.say); if (t.next) walk(t.next); });
  for (const p of PERSONAS) {
    out.push(p.name, p.title, ...p.greet, ...p.bye, ...p.barks);
    walk(p.topics);
  }
  return out;
}

describe('the crew', () => {
  it('everyone aboard has a character, and the captain too', () => {
    for (const n of [...CREW, 'captain']) expect(PERSONA_BY_ID.get(n), n).toBeTruthy();
  });

  it('every one is their own person', () => {
    expect(new Set(PERSONAS.map((p) => p.name)).size).toBe(PERSONAS.length);
    expect(new Set(PERSONAS.map((p) => p.title)).size).toBe(PERSONAS.length);
    for (const p of PERSONAS) {
      expect(p.greet.length, p.id).toBeGreaterThan(0);
      expect(p.bye.length, p.id).toBeGreaterThan(0);
      expect(p.topics.length, p.id).toBeGreaterThanOrEqual(2);
    }
  });

  it('nobody says a number', () => {
    const bad = allLines().filter((l) => /\d/.test(l));
    expect(bad).toEqual([]);
  });

  it("an agent doesn't pretend to chat", () => {
    const p = agentPersona('Claude Code');
    expect(p.topics[0].say[0]).toContain('tool calls');
  });
});

describe('a conversation', () => {
  const first = () => 0;

  it('greets, then offers the topics and a goodbye last', () => {
    const t = new Talk(PERSONA_BY_ID.get('Bo')!, first);
    expect(t.mode).toBe('say');
    expect(t.line).toBe(PERSONA_BY_ID.get('Bo')!.greet[0]);
    t.advance();
    expect(t.typing).toBe(false);
    t.advance();
    expect(t.mode).toBe('choose');
    const opts = t.options.map((o) => o.text);
    expect(opts[opts.length - 1]).toBe(GOODBYE);
    expect(opts.slice(0, -1)).toEqual(PERSONA_BY_ID.get('Bo')!.topics.map((x) => x.ask));
  });

  it('an answer plays beat by beat, then opens its follow-ups', () => {
    const bo = PERSONA_BY_ID.get('Bo')!;
    const gerald = bo.topics.findIndex((x) => x.next?.length);
    const t = new Talk(bo, first);
    t.advance(); t.advance();
    t.choose(gerald);
    for (const line of bo.topics[gerald].say) {
      expect(t.line).toBe(line);
      t.advance(); t.advance();
    }
    expect(t.mode).toBe('choose');
    expect(t.options[0].text).toBe(bo.topics[gerald].next![0].ask);
  });

  it('goodbye says goodbye, then ends', () => {
    const t = new Talk(PERSONA_BY_ID.get('Penny')!, first);
    t.advance(); t.advance();
    t.choose(t.options.length - 1);
    expect(t.line).toBe(PERSONA_BY_ID.get('Penny')!.bye[0]);
    expect(t.closed).toBe(false);
    t.advance(); t.advance();
    expect(t.closed).toBe(true);
  });

  it('asked topics are marked, and the keys move the choice', () => {
    const t = new Talk(PERSONA_BY_ID.get('Rex')!, first);
    t.advance(); t.advance();
    t.choose(0);
    while (t.mode === 'say') t.advance();
    expect(t.options[0].asked).toBe(true);
    t.move(-1);
    expect(t.sel).toBe(t.options.length - 1);
  });
});
