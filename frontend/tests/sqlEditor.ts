import { EditorView } from "@codemirror/view";
import { screen } from "@testing-library/react";

/** Replace the SQL editor's text (CodeMirror is not a form field, so no fireEvent.change). */
export function setSql(text: string): HTMLElement {
  const content = screen.getByLabelText("SQL query");
  const view = EditorView.findFromDOM(content);
  if (!view) throw new Error("SQL editor not mounted");
  view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } });
  return content;
}
