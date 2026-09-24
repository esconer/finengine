'use client';

import { useEffect, useState } from 'react';
import { Activity, Circle } from 'lucide-react';
import * as store from '@/lib/store';
import { useWebSocket } from '@/lib/websocket';

/**
 * Keeps the real-time client mounted for the dashboard shell and exposes a
 * small, honest connection state instead of leaving the socket as dead code.
 */
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
      aria-label="Real-time connection status"
      className="fixed bottom-4 left-4 z-40 flex items-center gap-2 rounded-lg border border-gray-200 bg-white/95 px-3 py-2 text-xs text-gray-700 shadow-sm dark:border-gray-700 dark:bg-gray-900/95 dark:text-gray-200"
    >
      {statusConnected ? <Activity className="h-3.5 w-3.5 text-emerald-500" /> : <Circle className="h-3.5 w-3.5 text-amber-500" />}
      <span>{statusConnected ? 'Live updates connected' : 'Live updates connecting'}</span>
    </div>
  );
}

export default RealtimeStatus;
