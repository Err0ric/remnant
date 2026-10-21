import { autocompletion, closeBrackets, closeCompletion } from "@codemirror/autocomplete";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { StandardSQL, sql, type SQLConfig } from "@codemirror/lang-sql";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { Compartment, EditorState, Prec } from "@codemirror/state";
import { EditorView, keymap, placeholder } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { useEffect, useRef } from "react";

interface SqlEditorProps {
  value: string;
  onChange: (value: string) => void;
  /** Gets the editor text as it is now, so a run never sends an older copy. */
  onRun: (value: string) => void;
  /** Column names of the events table, for autocomplete. */
  columns: string[];
  label: string;
}

/** Nonce the server puts in index.html for this page load (CSP style-src). */
export function cspNonce(): string {
  return document.querySelector('meta[name="csp-nonce"]')?.getAttribute("content") ?? "";
}

// Colors come from design tokens, so the editor follows the light and dark themes.
export const editorTheme = EditorView.theme({
  "&": {
    backgroundColor: "var(--inset)",
    color: "var(--text)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius)",
    fontSize: "13px",
  },
  "&.cm-focused": { outline: "none", borderColor: "var(--accent-text)" },
  ".cm-scroller": {
    fontFamily: '"Source Code Pro", ui-monospace, "SF Mono", Menlo, Consolas, monospace',
    lineHeight: "20px",
    minHeight: "92px",
  },
  ".cm-content": { padding: "10px 0", caretColor: "var(--text)" },
  ".cm-line": { padding: "0 12px" },
  ".cm-cursor": { borderLeftColor: "var(--text)" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground": {
    backgroundColor: "var(--accent-subtle)",
  },
  ".cm-placeholder": { color: "var(--text-muted)" },
  ".cm-tooltip": {
    backgroundColor: "var(--surface)",
    border: "1px solid var(--border-strong)",
    color: "var(--text)",
  },
  ".cm-tooltip-autocomplete > ul > li[aria-selected]": {
    backgroundColor: "var(--accent-subtle)",
    color: "var(--text)",
  },
});

/** `events` is the only table; columns complete without typing `events.`. */
function sqlConfig(columns: string[]): SQLConfig {
  return {
    dialect: StandardSQL,
    schema: { events: columns },
    defaultTable: "events",
    upperCaseKeywords: true,
  };
}

const highlight = HighlightStyle.define([
  { tag: tags.keyword, color: "var(--accent-text)", fontWeight: "600" },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--ok)" },
  { tag: [tags.number, tags.bool, tags.null], color: "var(--warn)" },
  { tag: tags.comment, color: "var(--text-muted)", fontStyle: "italic" },
  { tag: [tags.operator, tags.punctuation], color: "var(--text-secondary)" },
]);

export function SqlEditor({ value, onChange, onRun, columns, label }: SqlEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const schema = useRef(new Compartment());
  // Latest callbacks without rebuilding the editor on every render.
  const handlers = useRef({ onChange, onRun });
  handlers.current = { onChange, onRun };

  useEffect(() => {
    if (!host.current) return;
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          EditorView.cspNonce.of(cspNonce()),
          Prec.highest(
            keymap.of([
              {
                key: "Mod-Enter",
                run: (target) => {
                  closeCompletion(target);
                  handlers.current.onRun(target.state.doc.toString());
                  return true;
                },
              },
            ]),
          ),
          history(),
          closeBrackets(),
          autocompletion({ activateOnTyping: true }),
          // Suggestions belong to typing; leaving the editor (for example to click Run)
          // closes them so they do not cover the page.
          EditorView.domEventHandlers({
            blur: (_event, target) => {
              closeCompletion(target);
            },
          }),
          keymap.of([...defaultKeymap, ...historyKeymap]),
          schema.current.of(sql(sqlConfig([]))),
          syntaxHighlighting(highlight),
          editorTheme,
          EditorView.lineWrapping,
          placeholder("SELECT ... FROM events"),
          EditorView.contentAttributes.of({ "aria-label": label, "aria-multiline": "true" }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) handlers.current.onChange(update.state.doc.toString());
          }),
        ],
      }),
    });
    view.current = editor;
    return () => {
      editor.destroy();
      view.current = null;
    };
    // Built once; value and columns are synced by the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the editor in step when the value is replaced from outside (for example a reset).
  useEffect(() => {
    const editor = view.current;
    if (editor && editor.state.doc.toString() !== value) {
      editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value } });
    }
  }, [value]);

  useEffect(() => {
    view.current?.dispatch({
      effects: schema.current.reconfigure(sql(sqlConfig(columns))),
    });
  }, [columns]);

  return <div ref={host} />;
}
