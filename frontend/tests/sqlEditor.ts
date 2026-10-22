import { EditorView } from "@codemirror/view";
import { screen } from "@testing-library/react";

/** Replace the SQL editor's text (CodeMirror is not a form field, so no fireEvent.change).
 * Async: the editor is its own lazily loaded chunk. */
export async function setSql(text: string): Promise<HTMLElement> {
  const content = await screen.findByLabelText("SQL query");
  const view = EditorView.findFromDOM(content);
  if (!view) throw new Error("SQL editor not mounted");
  view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } });
  return content;
}
