// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  label: string;
}

interface State {
  error: Error | null;
}

/**
 * Keeps one failing panel from blanking the whole console.
 *
 * The provenance graph renders arbitrary run data; a malformed run should cost
 * the operator that panel, not their view of the incident.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`[ariadne] ${this.props.label} failed to render`, error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="error">
          <strong>{this.props.label} could not be rendered.</strong>
          <div style={{ marginTop: 6, fontSize: 12 }}>{this.state.error.message}</div>
          <button style={{ marginTop: 10 }} onClick={() => this.setState({ error: null })}>
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
