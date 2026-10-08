import type { WalkSpace } from '../walk';


export type RoomId = 'research' | 'forge' | 'backtest' | 'desk' | 'vault' | 'optimizer' | 'bridge';

export interface RoomDef {
  id: RoomId;
  name: string;
  icon: string;
  accent: string;
  floor: string;
  x0: number; x1: number; z0: number; z1: number;
  cx: number; cz: number;
  sign: [number, number, number];
}

export const WALL_H = 2.4;
export const RIM_H = 0.32;
export const PART_H = 0.62;
export const DOOR_W = 1.5;

const C0 = -6.4, C1 = 0, C2 = 6.4;
const HW = 3.2;
const BACK_Z0 = -6.6, BACK_Z1 = -1.0;
const FRONT_Z0 = 1.0, FRONT_Z1 = 6.6;
export const SHIP = { x0: -9.6, x1: 9.6, z0: BACK_Z0, z1: FRONT_Z1, noseX: 14.2, bridgeX1: 12.6, bridgeZ: 2.7 };

function room(
  id: RoomId, name: string, icon: string, accent: string, floor: string,
  cx: number, row: 'back' | 'front',
): RoomDef {
  const back = row === 'back';
  const z0 = back ? BACK_Z0 : FRONT_Z0;
  const z1 = back ? BACK_Z1 : FRONT_Z1;
  return {
    id, name, icon, accent, floor,
    x0: cx - HW, x1: cx + HW, z0, z1, cx, cz: (z0 + z1) / 2,
    sign: back ? [cx + 0.9, WALL_H + 2.0, BACK_Z0 - 0.4] : [cx, -0.2, FRONT_Z1 + 0.9],
  };
}

export const ROOMS: RoomDef[] = [
  room('optimizer', 'OPTIMIZER', '⚙️', '#38BDF8', '#3b4256', C0, 'back'),
  room('research', 'RESEARCH LAB', '🔬', '#A855F7', '#463d6e', C1, 'back'),
  room('desk', 'TRADING DESK', '📡', '#EC4899', '#5a3550', C2, 'back'),
  room('backtest', 'BACKTEST CHAMBER', '🧪', '#2DD4BF', '#2f4a52', C0, 'front'),
  room('forge', 'STRATEGY FORGE', '🔨', '#F59E0B', '#56402f', C1, 'front'),
  room('vault', 'WIN/LOSS VAULT', '💰', '#22C55E', '#2f4d3a', C2, 'front'),
  {
    id: 'bridge', name: 'BRIDGE', icon: '🚀', accent: '#A855F7', floor: '#3a3360',
    x0: SHIP.x1, x1: SHIP.bridgeX1, z0: -SHIP.bridgeZ, z1: SHIP.bridgeZ, cx: 11.3, cz: 0,
    sign: [12.6, -0.2, 3.6],
  },
];

export const ROOM: Record<RoomId, RoomDef> = Object.fromEntries(ROOMS.map((r) => [r.id, r])) as Record<RoomId, RoomDef>;

export function roomAt(x: number, z: number): RoomId | null {
  for (const r of ROOMS) {
    if (x >= r.x0 && x <= r.x1 && z >= r.z0 && z <= r.z1) return r.id;
  }
  if (x > SHIP.bridgeX1 && x < SHIP.noseX && Math.abs(z) < SHIP.bridgeZ * (1 - (x - SHIP.bridgeX1) / (SHIP.noseX - SHIP.bridgeX1))) return 'bridge';
  return null;
}


export const PROP = {
  dish: [-2.3, -5.75] as const,
  labScreen: [0.6, -6.6] as const,
  labConsoleA: [-1.5, -4.0] as const,
  labConsoleB: [1.4, -4.0] as const,
  printer: [2.55, -2.1] as const,
  furnace: [-2.2, 2.05] as const,
  anvil: [0.75, 4.0] as const,
  inbox: [1.25, 1.75] as const,
  outbox: [2.6, 2.4] as const,
  holo: [-6.2, 3.9] as const,
  tapeDeck: [-8.75, 2.0] as const,
  bin: [-3.95, 2.0] as const,
  tube: [8.5, -6.6] as const,
  hatch: [4.3, -6.6] as const,
  termA: [5.6, -3.7] as const,
  termB: [7.5, -3.7] as const,
  rack: [3.75, -2.0] as const,
  ordersBoard: [6.5, -6.6] as const,
  vaultDoor: [6.9, 1.45] as const,
  pile: [6.9, 3.75] as const,
  beacon: [9.05, 1.6] as const,
  riskConsole: [4.3, 5.2] as const,
  turbineA: [-8.55, -5.3] as const,
  turbineB: [-6.55, -5.55] as const,
  reactor: [-4.35, -5.0] as const,
  optPanel: [-5.0, -2.2] as const,
  chair: [11.4, 0] as const,
  helm: [12.75, 0] as const,
};


export interface NavNode { id: string; x: number; z: number; face?: number }

const F_PZ = 0;
const F_PX = Math.PI / 2;
const F_NZ = Math.PI;
const F_NX = -Math.PI / 2;

const nodes: NavNode[] = [];
const edges: [string, string][] = [];
function n(id: string, x: number, z: number, face?: number) { nodes.push({ id, x, z, face }); }
function e(a: string, b: string) { edges.push([a, b]); }

const spine = [-8.6, -6.4, -3.2, 0, 3.2, 6.4, 8.8, 10.3];
spine.forEach((x, i) => {
  n(`c${i}`, x, 0);
  if (i > 0) e(`c${i - 1}`, `c${i}`);
});
const spineAt = (x: number) => `c${spine.indexOf(x)}`;

for (const r of ROOMS) {
  if (r.id === 'bridge') continue;
  const back = r.cz < 0;
  n(`${r.id}.door`, r.cx, back ? -1.0 : 1.0);
  n(`${r.id}.mid`, r.cx, back ? -2.6 : 2.6);
  e(spineAt(r.cx), `${r.id}.door`);
  e(`${r.id}.door`, `${r.id}.mid`);
}

function st(id: string, room: RoomId, x: number, z: number, face: number, via = `${room}.mid`) {
  n(id, x, z, face);
  e(via, id);
}

st('research.scanA', 'research', -1.5, -4.75, F_PZ);
st('research.scanB', 'research', 1.4, -4.75, F_PZ);
st('research.printer', 'research', 1.85, -2.1, F_PX);
st('research.wall', 'research', 0.6, -5.7, F_NZ);
st('forge.inbox', 'forge', 0.6, 1.9, F_PX, 'forge.door');
st('forge.anvil', 'forge', 0.0, 4.0, F_PX);
st('forge.furnace', 'forge', -1.5, 2.7, F_NX);
st('forge.outbox', 'forge', 1.95, 2.75, F_PX);
st('forge.idle', 'forge', -0.9, 5.0, F_PX);
st('backtest.table', 'backtest', -7.55, 3.6, F_PX);
st('backtest.tableB', 'backtest', -6.2, 2.6, F_PZ);
st('backtest.tape', 'backtest', -8.1, 2.55, F_NZ);
st('backtest.bin', 'backtest', -4.6, 2.1, F_PX);
st('desk.termA', 'desk', 5.6, -4.45, F_PZ);
st('desk.termB', 'desk', 7.5, -4.45, F_PZ);
st('desk.tube', 'desk', 8.5, -5.55, F_NZ);
st('desk.airlock', 'desk', 4.3, -5.45, F_NZ);
st('desk.rack', 'desk', 4.45, -2.05, F_NX, 'desk.door');
st('vault.pile', 'vault', 5.75, 3.75, F_PX);
st('vault.pileB', 'vault', 7.0, 5.1, F_NZ);
st('vault.risk', 'vault', 4.3, 4.45, F_PZ);
st('vault.idle', 'vault', 8.4, 4.6, F_NX);
st('optimizer.panel', 'optimizer', -5.8, -2.2, F_PX);
st('optimizer.turbine', 'optimizer', -7.6, -4.15, F_NZ);
st('optimizer.reactor', 'optimizer', -4.4, -3.9, F_NZ);
n('bridge.mid', 11.0, -1.2);
e('c7', 'bridge.mid');
st('bridge.report', 'bridge', 10.6, -0.95, F_PX, 'bridge.mid');
st('bridge.helm', 'bridge', 12.1, 1.05, F_PX, 'c7');

export const AGENT_DOCKS = ['bridge.dock0', 'bridge.dock1', 'bridge.dock2', 'bridge.dock3', 'bridge.dock4'] as const;
st('bridge.dock0', 'bridge', 10.15, 1.75, F_PX, 'c7');
st('bridge.dock1', 'bridge', 10.95, 2.15, F_PX, 'c7');
st('bridge.dock2', 'bridge', 10.15, -1.95, F_PX, 'bridge.mid');
st('bridge.dock3', 'bridge', 11.85, -1.75, F_PX, 'bridge.mid');
st('bridge.dock4', 'bridge', 11.75, 1.9, F_PX, 'c7');
st('research.agentA', 'research', -0.2, -3.75, F_NZ);
st('research.agentB', 'research', -2.1, -2.7, F_PX);
st('backtest.agentA', 'backtest', -4.95, 3.9, F_NX);
st('backtest.agentB', 'backtest', -5.0, 5.15, F_NX);
st('forge.agentA', 'forge', 1.75, 4.6, F_NX);
st('forge.agentB', 'forge', -1.95, 4.25, F_PX);
st('desk.agentA', 'desk', 6.55, -4.6, F_NZ);
st('desk.agentB', 'desk', 8.6, -3.0, F_NX);
st('vault.agentA', 'vault', 5.2, 5.5, F_NX);
st('vault.agentB', 'vault', 4.05, 3.3, F_PZ);
st('bridge.agentA', 'bridge', 10.75, 1.05, F_PX, 'c7');
st('bridge.agentB', 'bridge', 11.85, -0.95, F_PX, 'bridge.mid');

export const NAV_NODES = nodes;
export const NAV_EDGES = edges;
export const FACE = { PZ: F_PZ, PX: F_PX, NZ: F_NZ, NX: F_NX };

export const KALSHI_POS = [3.2, 1.6, -17.5] as const;



const DOORS = [C0, C1, C2];
function partition(z: number): [number, number, number, number][] {
  const out: [number, number, number, number][] = [];
  let x = SHIP.x0;
  for (const d of DOORS) {
    out.push([x, z, d - DOOR_W / 2, z]);
    x = d + DOOR_W / 2;
  }
  out.push([x, z, SHIP.x1, z]);
  return out;
}

export const SHIP_GLASS_WALLS: [number, number, number, number][] = [
  [SHIP.x0 - 0.1, SHIP.z1 + 0.1, SHIP.x1 + 0.1, SHIP.z1 + 0.1],
  [SHIP.x1 + 0.1, SHIP.z0, SHIP.x1 + 0.1, -SHIP.bridgeZ],
  [SHIP.x1 + 0.1, SHIP.bridgeZ, SHIP.x1 + 0.1, SHIP.z1],
  ...partition(-1),
  ...partition(1),
  [-HW, SHIP.z0, -HW, -1], [-HW, 1, -HW, SHIP.z1],
  [HW, SHIP.z0, HW, -1], [HW, 1, HW, SHIP.z1],
  [SHIP.x1, -SHIP.bridgeZ - 0.05, SHIP.bridgeX1, -SHIP.bridgeZ - 0.05],
  [SHIP.bridgeX1, -SHIP.bridgeZ, SHIP.noseX - 0.1, 0],
  [SHIP.noseX - 0.1, 0, SHIP.bridgeX1, SHIP.bridgeZ],
  [SHIP.bridgeX1, SHIP.bridgeZ, SHIP.x1, SHIP.bridgeZ],
];

export const SHIP_DOORS: [number, number][] = DOORS.flatMap((x) => [[x, -1], [x, 1]] as [number, number][]);

export const SHIP_EXIT = [SHIP.x0 - 0.1, -0.62, SHIP.x0 - 0.1, 0.62] as const;

export const SHIP_WALK: WalkSpace = {
  wallT: 0.2,
  walls: [
    [SHIP.x0 - 0.1, SHIP.z0 - 0.1, SHIP.x1 + 0.1, SHIP.z0 - 0.1],
    [SHIP.x0 - 0.1, SHIP.z0 - 0.1, SHIP.x0 - 0.1, SHIP.z1 + 0.1],
    ...SHIP_GLASS_WALLS,
  ],
  props: [
    [...PROP.dish, 0.6], [...PROP.labConsoleA, 0.45], [...PROP.labConsoleB, 0.45], [...PROP.printer, 0.35],
    [...PROP.furnace, 0.6], [...PROP.anvil, 0.35], [...PROP.inbox, 0.25], [...PROP.outbox, 0.25],
    [...PROP.holo, 0.95], [...PROP.tapeDeck, 0.4], [...PROP.bin, 0.3],
    [...PROP.tube, 0.55], [...PROP.termA, 0.4], [...PROP.termB, 0.4], [...PROP.rack, 0.35],
    [...PROP.vaultDoor, 0.5], [...PROP.pile, 0.75], [...PROP.beacon, 0.25], [...PROP.riskConsole, 0.35],
    [...PROP.turbineA, 0.8], [...PROP.turbineB, 0.8], [...PROP.reactor, 0.55], [...PROP.optPanel, 0.35],
    [...PROP.chair, 0.45], [...PROP.helm, 0.35],
  ],
  start: { x: -7.6, z: 0, yaw: -Math.PI / 2 },
  exits: [SHIP_EXIT],
  eye: 1.55,
  speed: 2.4,
};
