import { Component, type ErrorInfo, type ReactNode } from "react";
import { logger } from "../lib/logger";

type Props = { children: ReactNode };
type State = { failed: boolean };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, _info: ErrorInfo): void {
    // Only the error type/status is logged; component props/state may contain
    // customer details.
    logger.error("Admin render failed", error);
  }

  render() {
    if (this.state.failed) {
      return (
        <main className="page">
          <h1>Something went wrong</h1>
          <p className="muted">
            The page could not be rendered. Reload the page, or sign in again if the problem continues.
          </p>
          <button type="button" className="btn" onClick={() => window.location.reload()}>
            Reload
          </button>
        </main>
      );
    }
    return this.props.children;
  }
}
