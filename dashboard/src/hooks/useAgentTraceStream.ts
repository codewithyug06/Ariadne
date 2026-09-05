// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState } from 'react';
import { api, type DriftUpdate } from '../api/client';

const RECONNECT_DELAY_MS = 2000;

interface AgentTraceState {
  updates: DriftUpdate[];
  connected: boolean;
  /**
   * `false` means the stream below is the raw, unfiltered global alert feed
   * (see the comment on `useAgentTraceStream` for why).
   */
  filteredByAgent: boolean;
}

/**
 * "Live trace" for a single agent, cloned from `useAlertStream()` in
 * useRunStream.ts.
 *
 * IMPORTANT — no backend support for per-agent filtering exists today.
 * `DriftUpdate` (ariadne/drift/schemas.py) carries `session_id`, not
 * `agent_identity`/`calling_agent_id`, and `/ws/alerts/live` broadcasts
 * every session's events with no agent filter. Building a client-side
 * filter against a field that isn't broadcast would either show nothing
 * (if we invented a field name that never matches) or silently mislabel
 * every session's traffic as this agent's (if we didn't filter at all)
 * — both are worse than being honest about the gap in a security product.
 *
 * So this hook reuses the same global `/ws/alerts/live` connection as
 * `useAlertStream()` and reports `filteredByAgent: false` so callers can
 * render an explicit "unfiltered" notice instead of silently mislabeling
 * data. Wiring true per-agent filtering needs a backend change (either
 * broadcasting `agent_identity` on `DriftUpdate`, or a
 * `/ws/agents/{id}/live` endpoint) — out of scope for this frontend-only
 * pass.
 */
export function useAgentTraceStream(agentIdentity: string | null): AgentTraceState {
  const [updates, setUpdates] = useState<DriftUpdate[]>([]);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!agentIdentity) {
      return;
    }
    let cancelled = false;
    setUpdates([]);

    const connect = () => {
      if (cancelled) return;
      const socket = new WebSocket(api.liveAlertsUrl());
      socketRef.current = socket;

      socket.onopen = () => !cancelled && setConnected(true);

      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data as string) as DriftUpdate | { type: string };
        if ('type' in payload) {
          return; // keepalive
        }
        setUpdates((current) => [payload, ...current].slice(0, 50));
      };

      socket.onclose = () => {
        if (cancelled) return;
        setConnected(false);
        timerRef.current = window.setTimeout(connect, RECONNECT_DELAY_MS);
      };

      socket.onerror = () => socket.close();
    };

    connect();

    return () => {
      cancelled = true;
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
      }
      socketRef.current?.close();
      setConnected(false);
    };
  }, [agentIdentity]);

  return { updates, connected, filteredByAgent: false };
}
