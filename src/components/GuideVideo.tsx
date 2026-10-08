import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { PlayCircle, X } from 'lucide-react';
import guideUrl from '../assets/ai-agents-guide.mp4';
import posterUrl from '../assets/ai-agents-guide-poster.jpg';

export const GUIDE_LENGTH = '1:35';

export function GuideVideoModal({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      onClose();
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  return createPortal(
    <div
      className="fixed inset-0 z-[70] grid place-items-center bg-black/80 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="AI agents video guide"
    >
      <div className="relative w-[1100px] max-w-[94vw]" onClick={(e) => e.stopPropagation()}>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close the guide"
          className="absolute -top-10 right-0 grid h-8 w-8 place-items-center rounded-lg text-white/80 transition-colors hover:bg-white/[0.1] hover:text-white"
        >
          <X className="h-5 w-5" />
        </button>
        <video
          src={guideUrl}
          poster={posterUrl}
          controls
          autoPlay
          playsInline
          className="aspect-video w-full rounded-2xl bg-black shadow-krypt-strong"
        />
      </div>
    </div>,
    document.body,
  );
}

export function GuideVideoCard() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-qa="guide-video-open"
        className="group flex w-full items-center gap-4 rounded-2xl border border-krypt-purple/40 bg-krypt-purple/10 p-2.5 text-left transition-colors hover:border-krypt-purple/70 hover:bg-krypt-purple/15"
      >
        <span className="relative shrink-0 overflow-hidden rounded-xl">
          <img src={posterUrl} alt="" className="h-[72px] w-[128px] object-cover" />
          <span className="absolute inset-0 grid place-items-center bg-black/30 transition-colors group-hover:bg-black/10">
            <PlayCircle className="h-8 w-8 text-white drop-shadow" />
          </span>
        </span>
        <span>
          <span className="block text-sm font-semibold text-white">Watch the {GUIDE_LENGTH} guide</span>
          <span className="block text-xs text-krypt-muted">
            Mossy shows how agents connect, why they start on paper, and the rule every buy has to pass.
          </span>
        </span>
      </button>
      {open && <GuideVideoModal onClose={() => setOpen(false)} />}
    </>
  );
}

export function GuideVideoButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className="krypt-btn-default" data-qa="guide-video-open">
        <PlayCircle className="h-4 w-4" /> Video guide
      </button>
      {open && <GuideVideoModal onClose={() => setOpen(false)} />}
    </>
  );
}
