import { describe, expect, it } from 'vitest';
import * as THREE from 'three';
import { BODY_R, Walker, atExit, collide, exitDistance, step, visibleFrom, type WalkSpace } from '../src/hub/walk';
import { ROOMS, SHIP_WALK } from '../src/hub/engine/layout';
import { COUNCIL_WALK, TABLE_R, seatOf } from '../src/hub/council/room';


function walk(space: WalkSpace, from: [number, number], to: [number, number]): [number, number] {
  let [x, z] = collide(from[0], from[1], space);
  const n = 200;
  for (let i = 0; i < n; i++) {
    [x, z] = step(x, z, (to[0] - from[0]) / n, (to[1] - from[1]) / n, space);
  }
  return [x, z];
}

function isFree(space: WalkSpace, x: number, z: number): boolean {
  const [cx, cz] = collide(x, z, space);
  return Math.hypot(cx - x, cz - z) < 1e-6;
}

describe('collide', () => {
  const box: WalkSpace = {
    wallT: 0.2, walls: [[-5, 0, 5, 0]], props: [[0, 3, 1]],
    start: { x: 0, z: 1, yaw: 0 }, eye: 1.6, speed: 2,
  };

  it('pushes a body off a wall to its own side', () => {
    const [, z] = collide(0, 0.1, box);
    expect(z).toBeCloseTo(BODY_R + 0.1, 5);
    const [, z2] = collide(0, -0.1, box);
    expect(z2).toBeCloseTo(-(BODY_R + 0.1), 5);
  });

  it('pushes a body out of a prop', () => {
    const [x, z] = collide(0, 3.2, box);
    expect(Math.hypot(x, z - 3)).toBeCloseTo(1 + BODY_R, 5);
  });

  it('a fast step cannot tunnel through a thin wall', () => {
    const [, z] = step(0, 1, 0, -10, box);
    expect(z).toBeGreaterThan(0);
  });
});

describe('the ship on foot', () => {
  it('starts in open corridor', () => {
    expect(isFree(SHIP_WALK, SHIP_WALK.start.x, SHIP_WALK.start.z)).toBe(true);
  });

  it('walks the corridor from the stern to the bridge', () => {
    const [x] = walk(SHIP_WALK, [-8.4, 0], [11, 0]);
    expect(x).toBeGreaterThan(10.5);
  });

  it('cannot cut through a partition between corridor and room', () => {
    const [, z] = walk(SHIP_WALK, [-3.2, 0], [-3.2, -3]);
    expect(z).toBeGreaterThan(-1);
  });

  it('enters every room through its doorway', () => {
    for (const r of ROOMS) {
      if (r.id === 'bridge') continue;
      const inside: [number, number] = [r.cx, r.cz < 0 ? -2.0 : 2.0];
      const got = walk(SHIP_WALK, [r.cx, 0], inside);
      expect(Math.abs(got[1]), r.id).toBeGreaterThan(1.5);
    }
  });

  it('cannot walk off the ship', () => {
    const [x] = walk(SHIP_WALK, [-8.4, 0], [-20, 0]);
    expect(x).toBeGreaterThan(-9.7);
  });
});

describe('the council on foot', () => {
  it('starts in open floor, facing the table', () => {
    const s = COUNCIL_WALK.start;
    expect(isFree(COUNCIL_WALK, s.x, s.z)).toBe(true);
    expect(s.z).toBeGreaterThan(0);
  });

  it('the table and the seats are solid', () => {
    const [x, z] = walk(COUNCIL_WALK, [0, 7], [0, 0]);
    expect(Math.hypot(x, z)).toBeGreaterThanOrEqual(TABLE_R);
    for (let i = 0; i < 6; i++) {
      const [sx, sz] = seatOf(i);
      expect(isFree(COUNCIL_WALK, sx, sz)).toBe(false);
    }
  });

  it('stays inside the bunker', () => {
    const [, z] = walk(COUNCIL_WALK, [6, 7], [6, 30]);
    expect(z).toBeLessThan(8.6);
  });
});

describe('the doors out', () => {
  it('the ship: back down the corridor and through the stern door', () => {
    const s = SHIP_WALK.start;
    expect(atExit(s.x, s.z, SHIP_WALK)).toBe(false);
    const [x, z] = walk(SHIP_WALK, [s.x, s.z], [-14, 0]);
    expect(atExit(x, z, SHIP_WALK)).toBe(true);
  });

  it('the ship: the stern wall away from the door is just a wall', () => {
    const [x, z] = walk(SHIP_WALK, [-7.6, 4], [-14, 4]);
    expect(atExit(x, z, SHIP_WALK)).toBe(false);
    expect(exitDistance(x, z, SHIP_WALK)).toBeGreaterThan(1);
  });

  it('the council: the vault door is the way out, the rest of the wall is not', () => {
    const s = COUNCIL_WALK.start;
    expect(atExit(s.x, s.z, COUNCIL_WALK)).toBe(false);
    const [x, z] = walk(COUNCIL_WALK, [-6.35, 3], [-6.35, -9]);
    expect(atExit(x, z, COUNCIL_WALK)).toBe(true);
    const [xo, zo] = walk(COUNCIL_WALK, [-7.6, 3], [-7.6, -9]);
    expect(atExit(xo, zo, COUNCIL_WALK)).toBe(true);
    expect(atExit(-6.35, -5.0, COUNCIL_WALK)).toBe(false);
    const [x2, z2] = walk(COUNCIL_WALK, [5, 3], [5, -9]);
    expect(atExit(x2, z2, COUNCIL_WALK)).toBe(false);
  });

  it('standing still by a door never throws you out', () => {
    const w = new Walker(SHIP_WALK);
    w.x = -9.3; w.z = 0;
    w.update(0.2);
    expect(w.exited).toBe(false);
  });
});

describe('Walker', () => {
  it('walks forward the way it faces', () => {
    const w = new Walker(SHIP_WALK);
    const x0 = w.x;
    w.update(0.5);
    expect(w.x).toBeCloseTo(x0, 6);
    const cam = new THREE.PerspectiveCamera();
    w.apply(cam);
    const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(cam.quaternion);
    expect(fwd.x).toBeGreaterThan(0.99);
    expect(cam.position.y).toBeCloseTo(SHIP_WALK.eye, 2);
  });
});

describe('labels in first person', () => {
  it('a label behind the lens is not drawn (it would land mirrored)', () => {
    const cam = new THREE.PerspectiveCamera();
    cam.position.set(0, 1.6, 0);
    cam.rotation.set(0, 0, 0);
    cam.updateMatrixWorld();
    expect(visibleFrom(cam, new THREE.Vector3(0, 1.6, -3), 10)).toBe(true);
    expect(visibleFrom(cam, new THREE.Vector3(0, 1.6, 3), 10)).toBe(false);
    expect(visibleFrom(cam, new THREE.Vector3(0, 1.6, -30), 10)).toBe(false);
  });
});
