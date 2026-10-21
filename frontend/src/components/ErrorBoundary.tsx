import { Component, type ReactNode } from "react";

interface ErrorBoundaryProps {
  /** What failed, in plain words ("This tab"). */
  label: string;
  children: ReactNode;
}

interface ErrorBoundaryState {
  failed: boolean;
}

/**
 * Keeps one bad record from blanking the whole app: a part of a page that throws while
 * rendering shows a short note instead (QA F1). React only offers this as a class
 * component, the one exception to the function-component rule. Nothing is logged: the
 * error may quote record content.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { failed: true };
  }

  render(): ReactNode {
    if (this.state.failed) {
      return (
        <p
          role="alert"
          className="rounded border border-border bg-surface px-3 py-4 text-sm text-danger"
        >
          {this.props.label} could not be shown. Some stored data is not in the expected shape; the
          rest of the app still works. Try another time range, or report it with the time range you
          chose.
        </p>
      );
    }
    return this.props.children;
  }
}
