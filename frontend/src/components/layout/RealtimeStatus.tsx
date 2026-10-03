'use client';

import { useEffect, useState } from 'react';
import { Activity, Circle } from 'lucide-react';
import * as store from '@/lib/store';
import { useWebSocket } from '@/lib/websocket';

/**
 * Keeps the real-time client mounted for the dashboard shell and exposes a
 * small, honest connection state instead of leaving the socket as dead code.
 *
 * THREE states, not two. The chip used to branch on the socket alone, so when
 * the user turned Live OFF it still said "connecting" — forever. Nothing was
 * connecting: `lib/websocket.ts:348-350` calls `disconnect()` when Live is
 * off. The chip was asserting a transient fault that could never resolve, and
 * it looked identical to a genuine reconnect loop.
 *
 * WHAT DISTINGUISHES THEM: `useUIStore().liveDataMode`, the boolean the user
 * sets with the Header's Live toggle (`aria-pressed={liveDataMode}` →
 * `toggleLiveDataMode`). It is the only field on screen that separates "the
 * user switched this off" from "the socket is opening", and it is sufficient —
 * `liveDataMode === false` is off, `liveDataMode === true && !connected` is
 * connecting. There is no separate `isConnecting` to read (the socket's own
 * `readyState` is not subscribed to), so this state is built from the field that
 * exists rather than from one invented to fill the gap.
 *
 * WHY "off" AND NOT "paused" / "reconnecting": Live off is a SETTING the user
 * chose, and the copy has to read that way. "Paused" and "reconnecting" are
 * fault vocabulary — they promise a recovery the app is not attempting and
 * invite the reader to go looking for a problem that does not exist. It also
 * matches the vocabulary the app already uses for this exact toggle:
 * `dashboard/page.tsx:397` renders "Live Data Off" beside a neutral dot, not a
 * warning colour. So the icon is that same neutral `Circle`, in slate rather
 * than the amber of "connecting", and the WORD carries the state — colour is
 * reinforcement here, never the only carrier.
 */
type RealtimeState = 'connected' | 'connecting' | 'off';

export function RealtimeStatus() {
  const [connected, setConnected] = useState(false);
  const uiState = typeof store.useUIStore === 'function'
    ? store.useUIStore((state: any) => state)
    : undefined;
  const liveDataMode = Boolean(uiState?.liveDataMode);
  const { isConnected, connect } = useWebSocket({
    topics: ['portfolio', 'analytics', 'market_data'],
    autoReconnect: true,
    onConnect: () => setConnected(true),
    onDisconnect: () => setConnected(false),
  });
  const statusConnected = isConnected || connected;

  // The user's setting is authoritative: a stale `isConnected` left over from
  // before the toggle must not report "connected" for a stream the user
  // switched off.
  const state: RealtimeState = !liveDataMode
    ? 'off'
    : statusConnected
      ? 'connected'
      : 'connecting';

  useEffect(() => {
    if (!liveDataMode) {
      setConnected(false);
      return;
    }
    void connect().then(() => setConnected(true)).catch(() => setConnected(false));
  }, [connect, liveDataMode]);

  return (
    <div
      data-testid="realtime-status"
      data-live-state={state}
      aria-label="Real-time connection status"
      className="fixed bottom-4 left-4 z-40 flex items-center gap-2 rounded-lg border border-gray-200 bg-white/95 px-3 py-2 text-xs text-gray-700 shadow-sm dark:border-gray-700 dark:bg-gray-900/95 dark:text-gray-200"
    >
      {state === 'connected' ? (
        <Activity className="h-3.5 w-3.5 text-emerald-500" />
      ) : state === 'connecting' ? (
        <Circle className="h-3.5 w-3.5 text-amber-500" />
      ) : (
        <Circle className="h-3.5 w-3.5 text-slate-400" />
      )}
      <span>
        {state === 'connected'
          ? 'Live updates connected'
          : state === 'connecting'
            ? 'Live updates connecting'
            : 'Live updates off'}
      </span>
    </div>
  );
}

export default RealtimeStatus;
