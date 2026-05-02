import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
  info: ErrorInfo | null;
}

/** Top-level error boundary so a single render throw doesn't blank the UI. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.setState({ error, info });
    // eslint-disable-next-line no-console
    console.error("[hostile-mesh] uncaught render error:", error, info);
  }

  override render() {
    if (this.state.error) {
      return (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 9999,
            background: "#0a0a0a",
            color: "#fafafa",
            padding: 32,
            fontFamily: '"JetBrains Mono", monospace',
            overflow: "auto",
          }}
        >
          <div
            style={{
              maxWidth: 960,
              margin: "0 auto",
              border: "1px solid #ef4444",
              padding: 24,
              borderRadius: 16,
            }}
          >
            <div
              style={{
                fontSize: 11,
                letterSpacing: "0.3em",
                color: "#ef4444",
                marginBottom: 12,
              }}
            >
              UI · UNCAUGHT ERROR
            </div>
            <div style={{ fontSize: 18, marginBottom: 8 }}>
              {this.state.error.name}: {this.state.error.message}
            </div>
            {this.state.error.stack && (
              <pre
                style={{
                  fontSize: 11,
                  color: "#a1a1aa",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  background: "#0a0a0a",
                  padding: 12,
                  borderRadius: 6,
                  marginTop: 12,
                  maxHeight: "40vh",
                  overflow: "auto",
                }}
              >
                {this.state.error.stack}
              </pre>
            )}
            <button
              onClick={() => this.setState({ error: null, info: null })}
              style={{
                marginTop: 18,
                padding: "10px 18px",
                background: "transparent",
                border: "1px solid #ef4444",
                color: "#ef4444",
                letterSpacing: "0.18em",
                cursor: "pointer",
              }}
            >
              RESET
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
