import { Component, type ReactNode } from "react";
import { errorId, reportClientError } from "@/lib/clientErrors";
import { isChunkError, reloadOnce } from "@/lib/chunkReload";

interface ErrorBoundaryProps {
  /** What failed, in plain words ("This tab", "Identity"). */
  label: string;
  children: ReactNode;
}

interface ErrorBoundaryState {
  id: string | null;
}

/**
 * Keeps one failing panel from blanking the page: it shows an error card with an error id
 * and the rest of the page renders (QA F1; owner 2026-11-02). React only offers this as a
 * class component, the one exception to the function-component rule. The report to the
 * server carries the error's kind and a scrubbed message, never record content.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { id: null };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { id: errorId() };
  }

  componentDidCatch(error: unknown): void {
    reportClientError("panel", error, this.state.id ?? errorId());
  }

  render(): ReactNode {
    if (this.state.id) {
      return (
        <p
          role="alert"
          className="rounded-card border border-border bg-surface px-3 py-4 text-sm text-danger"
        >
          {this.props.label} could not be shown. The rest of the page still works. Try another time
          range, or report it with error id <span className="font-mono">{this.state.id}</span>.
        </p>
      );
    }
    return this.props.children;
  }
}

interface PageBoundaryProps {
  children: ReactNode;
}

/** The whole page: "Something went wrong on this page" with Reload and the error id,
 * never a blank page. A missing chunk after an update reloads once by itself. Give it a
 * `key` per route so moving to another page clears it. */
export class PageBoundary extends Component<PageBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { id: null };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { id: errorId() };
  }

  componentDidCatch(error: unknown): void {
    const chunk = isChunkError(error);
    reportClientError(chunk ? "chunk" : "render", error, this.state.id ?? errorId());
    if (chunk) reloadOnce();
  }

  render(): ReactNode {
    if (!this.state.id) return this.props.children;
    return (
      <div role="alert" className="flex flex-1 flex-col items-start gap-2 px-5 py-6">
        <h1 className="text-lg font-semibold">Something went wrong on this page</h1>
        <p className="text-sm text-text-secondary">
          Reload to try again. If it keeps happening, report error id{" "}
          <span className="font-mono text-text">{this.state.id}</span>.
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="h-8 rounded bg-accent px-4 text-sm font-semibold text-white hover:brightness-110"
        >
          Reload
        </button>
      </div>
    );
  }
}
