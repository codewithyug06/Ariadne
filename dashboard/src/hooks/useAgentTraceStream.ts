// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState } from 'react';
import { api, type DriftUpdate } from '../api/client';

const RECONNECT_DELAY_MS = 2000;

interface AgentTraceState {
  updates: DriftUpdate[];
  connected: boolean;
  /**
   * Always `true` now that `DriftUpdate.agent_identity` is broadcast (see
   * ariadne/proxy/interceptor.py). Kept as a field rather than removed so
   * callers that render an "unfiltered" notice degrade gracefully if a
   * future backend rollback ever stops sending the field again.
   */
  filteredByAgent: boolean;
}

/**
 * "Live trace" for a single agent, filtered client-side from the shared
 * `/ws/alerts/live` feed by `DriftUpdate.agent_identity`.
 *
 * The stream itself is still global (there is no per-agent `/ws/agents/{id}`
 * endpoint) — every subscriber receives every session's events and discards
 * the ones that don't match `agentIdentity`. That's fine for the dashboard's
 * scale; it just means this hook is not a bandwidth optimization, only a
 * display filter.
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

    const connect = async () => {
      if (cancelled) return;
      const url = await api.liveAlertsUrl();
      if (cancelled) return;
      const socket = new WebSocket(url);
      socketRef.current = socket;

      socket.onopen = () => !cancelled && setConnected(true);

      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data as string) as DriftUpdate | { type: string };
        if ('type' in payload) {
          return; // keepalive
        }
        if (payload.agent_identity !== agentIdentity) {
          return; // another session's traffic on the shared alert feed
        }
        setUpdates((current) => [payload, ...current].slice(0, 50));
      };

      socket.onclose = () => {
        if (cancelled) return;
        setConnected(false);
        timerRef.current = window.setTimeout(() => void connect(), RECONNECT_DELAY_MS);
      };

      socket.onerror = () => socket.close();
    };

    void connect();

    return () => {
      cancelled = true;
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
      }
      socketRef.current?.close();
      setConnected(false);
    };
  }, [agentIdentity]);

  return { updates, connected, filteredByAgent: true };
}
