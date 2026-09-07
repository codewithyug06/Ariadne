// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState } from 'react';
import { api, type DriftUpdate } from '../api/client';

const RECONNECT_DELAY_MS = 2000;

interface StreamState {
  updates: DriftUpdate[];
  connected: boolean;
}

/**
 * Subscribe to a run's live drift stream.
 *
 * The server replays its buffered history on connect, so a dashboard opened
 * mid-run still renders a complete curve. Updates are de-duplicated by step
 * index because that replay overlaps whatever REST already returned.
 */
export function useRunStream(sessionId: string | null): StreamState {
  const [updates, setUpdates] = useState<DriftUpdate[]>([]);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!sessionId) {
      return;
    }
    let cancelled = false;
    setUpdates([]);

    const connect = async () => {
      if (cancelled) return;
      const url = await api.liveRunUrl(sessionId);
      if (cancelled) return;
      const socket = new WebSocket(url);
      socketRef.current = socket;

      socket.onopen = () => !cancelled && setConnected(true);

      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data as string) as DriftUpdate | { type: string };
        if ('type' in payload) {
          return; // keepalive
        }
        setUpdates((current) => {
          const next = current.filter((item) => item.step_index !== payload.step_index);
          next.push(payload);
          next.sort((a, b) => a.step_index - b.step_index);
          return next;
        });
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
  }, [sessionId]);

  return { updates, connected };
}

/** Subscribe to ESCALATE/BLOCK events across every active session. */
export function useAlertStream(): StreamState {
  const [updates, setUpdates] = useState<DriftUpdate[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let timer: number | null = null;

    const connect = async () => {
      if (cancelled) return;
      const url = await api.liveAlertsUrl();
      if (cancelled) return;
      socket = new WebSocket(url);

      socket.onopen = () => !cancelled && setConnected(true);
      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data as string) as DriftUpdate | { type: string };
        if ('type' in payload) return;
        setUpdates((current) => [payload, ...current].slice(0, 20));
      };
      socket.onclose = () => {
        if (cancelled) return;
        setConnected(false);
        timer = window.setTimeout(() => void connect(), RECONNECT_DELAY_MS);
      };
      socket.onerror = () => socket?.close();
    };

    void connect();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
      socket?.close();
    };
  }, []);

  return { updates, connected };
}
