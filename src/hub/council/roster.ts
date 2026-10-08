
export type MemberId = 'greed' | 'panic' | 'quant' | 'fomo' | 'doubt' | 'risk';
export type Speaker = MemberId | 'chair';

export const MEMBER_IDS: MemberId[] = ['doubt', 'panic', 'greed', 'fomo', 'quant', 'risk'];

export interface Features {
  subj: string;
  title: string;
  dir: 'YES' | 'NO';
  price: number | null;
  edge: number | null;
  conf: number | null;
  whale: boolean;
  whaleUsd: number | null;
  cat: string;
  open: number | null;
  cap: number | null;
}

export type BubbleShape = 'burst' | 'shaky' | 'terminal' | 'bouncy' | 'flat' | 'sign' | 'pixel';

export interface BubbleStyle {
  shape: BubbleShape;
  bg: string;
  fg: string;
  edge: string;
  font: string;
  px: number;
  upper: boolean;
}

type Lines = (f: Features) => (string | null)[];

export interface Persona {
  id: Speaker;
  name: string;
  color: string;
  style: BubbleStyle;
  votes: (f: Features) => boolean;
  pro: Lines;
  con: Lines;
  win: (pnl: string) => string[];
  loss: (pnl: string) => string[];
  payday: string[];
  sore: string[];
}

const SANS = '"Chakra Petch", system-ui, sans-serif';
const MONO = '"JetBrains Mono", Menlo, monospace';
const PIXEL = '"Press Start 2P", monospace';

function k(v: number): string {
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(v >= 1e4 ? 0 : 1)}K`;
  return `$${v.toFixed(0)}`;
}

const p = (f: Features) => (f.price === null ? null : `${f.price}¢`);
const nearCap = (f: Features) => f.open !== null && f.cap !== null && f.cap > 0 && f.open / f.cap >= 0.85;

export const PERSONAS: Record<Speaker, Persona> = {
  greed: {
    id: 'greed', name: 'GREED', color: '#F5B800',
    style: { shape: 'burst', bg: '#FFD54A', fg: '#4A2E00', edge: '#B45309', font: `800 {px}px ${SANS}`, px: 18, upper: true },
    votes: (f) => f.price === null || f.price <= 92,
    pro: (f) => [
      'ALL IN.',
      p(f) && `${p(f)}?? THAT'S A STEAL`,
      `BUY ${f.dir}. BUY ALL OF IT.`,
      f.whaleUsd !== null ? `${k(f.whaleUsd)} WHALE? WE RIDE WITH HIM` : null,
      'MORE CONTRACTS. MORE.',
    ],
    con: (f) => [p(f) && `even I won't pay ${p(f)}`],
    win: (pnl) => [`TOLD YOU. +${pnl}`, `+${pnl}! MORE OF THAT`, 'TOLD YOU. TOLD ALL OF YOU.'],
    loss: () => ['the market is WRONG', '...we go again.'],
    payday: ["I'M RICH!!! 💰", 'DRINKS ON ME 💰💰'],
    sore: ['BOOOOO.', 'cowards. all of you.'],
  },
  panic: {
    id: 'panic', name: 'PANIC', color: '#9CCBFF',
    style: { shape: 'shaky', bg: '#E6F2FF', fg: '#1E3A8A', edge: '#60A5FA', font: `italic 600 {px}px ${SANS}`, px: 15, upper: false },
    votes: (f) => f.price !== null && f.conf !== null && f.price >= 85 && f.conf >= 80,
    pro: (f) => ['fine but if it dips I\'m LEAVING', p(f) && `${p(f)} is... safe? IS IT SAFE??`],
    con: (f) => [
      'what if it goes to ZERO??',
      p(f) && `${p(f)} is SO much money`,
      f.cat ? `${f.cat.toLowerCase()} markets are a TRAP` : null,
      'can we just... not??',
      'my chair is shaking 😰',
    ],
    win: () => ['ok... ok that was fine', 'phew. PHEW.'],
    loss: () => ['I SAID SO!! I SAID SO!!', 'WE\'RE DOOMED'],
    payday: ['is this... good?? 😰', 'too much money!! hide it!!'],
    sore: ['nooooo', 'I\'m writing my will'],
  },
  quant: {
    id: 'quant', name: 'THE QUANT', color: '#7FC8A9',
    style: { shape: 'terminal', bg: '#0F2A1F', fg: '#B5FFD9', edge: '#7FFFC4', font: `500 {px}px ${MONO}`, px: 14, upper: false },
    votes: (f) => f.edge !== null && f.edge >= 10,
    pro: (f) => [
      f.edge !== null ? `edge ${f.edge.toFixed(1)} pts. take it.` : null,
      f.conf !== null ? `conf ${f.conf.toFixed(0)}%. acceptable.` : null,
      f.edge !== null && f.conf !== null ? `${f.edge.toFixed(1)} pts on ${f.conf.toFixed(0)}% conf. fine.` : null,
    ],
    con: (f) => [
      f.edge !== null ? `edge is ${f.edge.toFixed(1)} pts. marginal.` : 'no edge data. pass.',
      f.conf !== null ? `conf ${f.conf.toFixed(0)}%. coin flip.` : null,
      'sample size: insufficient.',
    ],
    win: () => ['variance, in our favor.', 'as modeled.'],
    loss: () => ['within expectations.', 'variance. log it.'],
    payday: ['statistically... nice.', 'outlier. noted. 📈'],
    sore: ['noted. disagree.', 'logging dissent.'],
  },
  fomo: {
    id: 'fomo', name: 'FOMO', color: '#FF4FA3',
    style: { shape: 'bouncy', bg: '#FF4FA3', fg: '#FFFFFF', edge: '#FFC2E0', font: `700 {px}px ${SANS}`, px: 16, upper: true },
    votes: (f) => f.whale || (f.conf ?? 0) >= 60 || (f.price ?? 0) >= 55,
    pro: (f) => [
      "EVERYONE'S BUYING THIS RN",
      f.whaleUsd !== null ? `🐋 ${k(f.whaleUsd)} CAN'T BE WRONG!!` : null,
      `${f.subj} TO THE MOON 🚀`,
      "WE'RE GONNA MISS IT",
    ],
    con: () => ["nobody's even talking about this 😴", 'boring. NEXT.'],
    win: () => ["LET'S GOOO 🚀🚀", 'WE EATING 🍽️'],
    loss: () => ['...it was trending though', 'the vibes were RIGHT'],
    payday: ["WE'RE SO BACK 🚀🚀🚀", 'POST IT. POST IT NOW'],
    sore: ['ugh FINE', 'we missed it. again.'],
  },
  doubt: {
    id: 'doubt', name: 'DOUBT', color: '#9A9AA6',
    style: { shape: 'flat', bg: '#D4D4D8', fg: '#3F3F46', edge: '#71717A', font: `500 {px}px ${SANS}`, px: 14, upper: false },
    votes: (f) => f.edge !== null && f.conf !== null && f.edge >= 14 && f.conf >= 75,
    pro: () => ['fine. this once.', 'numbers check out. ugh.'],
    con: (f) => [
      'seen this movie before.',
      p(f) && `${p(f)}. sure.`,
      f.whale ? 'whales lie.' : null,
      'mm. no.',
    ],
    win: () => ['lucky.', 'won\'t last.'],
    loss: () => ['called it.', 'mm-hm.'],
    payday: ['it won\'t last.', 'enjoy it while it\'s here.'],
    sore: ['whatever.', 'mm.'],
  },
  risk: {
    id: 'risk', name: 'RISK', color: '#E5383B',
    style: { shape: 'sign', bg: '#FFFFFF', fg: '#B91C1C', edge: '#E5383B', font: `800 {px}px ${SANS}`, px: 15, upper: true },
    votes: (f) => !nearCap(f) && (f.price === null || f.price <= 80),
    pro: (f) => ['within limits. go.', f.open !== null && f.cap !== null ? `${f.open}/${f.cap} open. allowed.` : 'max size only.'],
    con: (f) => [
      'position cap. sit down, Greed.',
      f.open !== null && f.cap !== null ? `${f.open}/${f.cap} open. NO.` : null,
      p(f) && `${p(f)} risks too much for too little`,
      'TWEEEET! ORDER!',
    ],
    win: () => ['risk managed. ✔', 'clean.'],
    loss: () => ['lost the stake. no more.', 'capped. moving on.'],
    payday: ["...ok that's allowed 🎉", 'TWEEET! (happily)'],
    sore: ['TWEEEEET. noted.', 'objection logged.'],
  },
  chair: {
    id: 'chair', name: 'CHAIR MOSSY', color: '#7CFC6A',
    style: { shape: 'pixel', bg: '#160C2B', fg: '#B6FF9E', edge: '#7CFC6A', font: `400 {px}px ${PIXEL}`, px: 11, upper: true },
    votes: () => true,
    pro: (f) => [`next item: ${f.subj}`, `the council will hear: ${f.subj}`],
    con: () => ['ORDER! ORDER!'],
    win: () => ['the council was right'],
    loss: () => ['the council... regrets'],
    payday: ['PAYDAY! COUNCIL DISMISSED!'],
    sore: ['OVERRULED!'],
  },
};

export function line(xs: (string | null | false)[], fallback = '…'): string {
  const ok = xs.filter((x): x is string => typeof x === 'string' && x.length > 0);
  return ok.length ? ok[Math.floor(Math.random() * ok.length)] : fallback;
}
