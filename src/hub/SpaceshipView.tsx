import { HubStage } from './HubStage';
import { HubEngine } from './engine/HubEngine';

function create(canvas: HTMLCanvasElement, w: number, h: number) {
  return new HubEngine(canvas, w, h);
}

export default function SpaceshipView() {
  return (
    <HubStage
      create={create}
      hint="drag to pan · scroll to zoom · click a room to follow it"
      loading="Boarding the ship…"
      tourLabel="Tour"
      tourTitle="Camera tours the busiest rooms"
      frameBg="#05030c"
      wantsAutopilot
    />
  );
}
