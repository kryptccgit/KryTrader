import { useEffect, useRef } from 'react';
import { EditorView, keymap } from '@codemirror/view';
import { EditorState } from '@codemirror/state';
import { indentWithTab } from '@codemirror/commands';
import { basicSetup } from 'codemirror';
import { python } from '@codemirror/lang-python';

const kryptTheme = EditorView.theme(
  {
    '&': {
      backgroundColor: 'transparent',
      color: '#e5e7eb',
      fontSize: '12.5px',
      height: '100%',
    },
    '.cm-content': {
      fontFamily: "'JetBrains Mono', ui-monospace, monospace",
      caretColor: '#a78bfa',
    },
    '.cm-cursor, .cm-dropCursor': { borderLeftColor: '#a78bfa' },
    '&.cm-focused': { outline: 'none' },
    '.cm-gutters': {
      backgroundColor: 'transparent',
      color: 'rgba(148,163,184,0.45)',
      border: 'none',
    },
    '.cm-activeLine': { backgroundColor: 'rgba(255,255,255,0.03)' },
    '.cm-activeLineGutter': { backgroundColor: 'rgba(255,255,255,0.04)' },
    '.cm-selectionBackground, &.cm-focused .cm-selectionBackground': {
      backgroundColor: 'rgba(139,92,246,0.25) !important',
    },
    '.cm-matchingBracket': { backgroundColor: 'rgba(139,92,246,0.3)' },
  },
  { dark: true },
);

export function ScriptEditor({
  value, onChange, readOnly = false,
}: {
  value: string;
  onChange: (code: string) => void;
  readOnly?: boolean;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    if (!hostRef.current) return;
    const view = new EditorView({
      parent: hostRef.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          basicSetup,
          python(),
          kryptTheme,
          keymap.of([indentWithTab]),
          EditorState.readOnly.of(readOnly),
          EditorView.updateListener.of((u) => {
            if (u.docChanged) onChangeRef.current(u.state.doc.toString());
          }),
        ],
      }),
    });
    viewRef.current = view;
    return () => {
      view.destroy();
      viewRef.current = null;
    };
  }, [readOnly]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const cur = view.state.doc.toString();
    if (cur !== value) {
      view.dispatch({ changes: { from: 0, to: cur.length, insert: value } });
    }
  }, [value]);

  return (
    <div
      ref={hostRef}
      className="h-full min-h-[280px] overflow-auto rounded-lg border border-krypt-border bg-krypt-void/50 [&_.cm-editor]:h-full"
    />
  );
}
