import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { EditorState } from "@codemirror/state";
import { EditorView, keymap, lineNumbers } from "@codemirror/view";
import { useEffect, useRef } from "react";
import { cspNonce, editorTheme } from "@/features/search/SqlEditor";

interface YamlEditorProps {
  value: string;
  onChange: (value: string) => void;
  label: string;
}

/** Plain-text editor for template YAML: monospace, line numbers, undo, Tab indents. */
export function YamlEditor({ value, onChange, label }: YamlEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const changed = useRef(onChange);
  changed.current = onChange;

  useEffect(() => {
    if (!host.current) return;
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          EditorView.cspNonce.of(cspNonce()),
          lineNumbers(),
          history(),
          keymap.of([indentWithTab, ...defaultKeymap, ...historyKeymap]),
          editorTheme,
          EditorView.theme({ ".cm-scroller": { minHeight: "420px", maxHeight: "70vh" } }),
          EditorState.tabSize.of(2),
          EditorView.contentAttributes.of({ "aria-label": label, "aria-multiline": "true" }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) changed.current(update.state.doc.toString());
          }),
        ],
      }),
    });
    view.current = editor;
    return () => {
      editor.destroy();
      view.current = null;
    };
    // Built once; the value is synced by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const editor = view.current;
    if (editor && editor.state.doc.toString() !== value) {
      editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value } });
    }
  }, [value]);

  return <div ref={host} className="min-w-0" />;
}
