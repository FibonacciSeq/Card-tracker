import { Component, type ErrorInfo, type ReactNode } from "react";
import { logger } from "../lib/logger";
import { useLocale } from "../state/locale";

type Props = { children: ReactNode };
type State = { failed: boolean };

function ErrorFallback() {
  const { t } = useLocale();
  return (
    <main className="page">
      <h1>{t("Something went wrong")}</h1>
      <p className="muted">
        {t(
          "The page could not be rendered. Reload the page, or sign in again if the problem continues.",
        )}
      </p>
      <button type="button" className="btn" onClick={() => window.location.reload()}>
        {t("Reload")}
      </button>
    </main>
  );
}

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
      return <ErrorFallback />;
    }
    return this.props.children;
  }
}
