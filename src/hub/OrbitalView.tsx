import { HubStage } from './HubStage';
import { OrbitalEngine } from './orbital/OrbitalEngine';

function create(canvas: HTMLCanvasElement, w: number, h: number) {
  return new OrbitalEngine(canvas, w, h);
}

export default function OrbitalView() {
  return (
    <HubStage
      create={create}
      hint="drag to rotate · scroll to zoom · click a planet to follow it"
      loading="Aligning the orrery…"
      tourLabel="Cinematic"
      tourTitle="Camera rides each comet in, then cuts to the nova"
      frameBg="#02040c"
    />
  );
}
