/**
 * RealtimeStatus — the chip had two states for three situations, so turning
 * Live off asserted "connecting" forever.
 *
 * `statusConnected ? 'Live updates connected' : 'Live updates connecting'`
 * branches on the socket alone. When the user flips the Live toggle OFF, the
 * socket is not connecting — it is deliberately disconnected
 * (`lib/websocket.ts:348-350` calls `disconnect()` when `liveDataMode` is
 * false) — so the chip claims a transient fault that will never resolve, and
 * keeps claiming it for as long as the user leaves Live off.
 *
 * What the store can distinguish: `useUIStore().liveDataMode` is a real boolean
 * the user sets (Header's toggle, `aria-pressed={liveDataMode}` →
 * `toggleLiveDataMode`, `lib/store.ts:411`). It is the ONLY field that tells
 * live-off from connecting, and it is sufficient: `liveDataMode === false`
 * means "off", `liveDataMode === true && !isConnected` means "connecting".
 * There is no separate `isConnecting` flag to read — the socket's own state is
 * `readyState`, which the chip does not subscribe to — so the third state is
 * built from `liveDataMode`, not invented.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({
  liveDataMode: true,
  isConnected: false,
  connect: vi.fn(),
}));

vi.mock('@/lib/store', () => ({
  useUIStore: Object.assign(
    (selector?: (state: { liveDataMode: boolean }) => unknown) =>
      selector ? selector({ liveDataMode: mocks.liveDataMode }) : { liveDataMode: mocks.liveDataMode },
    { getState: () => ({ liveDataMode: mocks.liveDataMode }) }
  ),
}));

vi.mock('@/lib/websocket', () => ({
  useWebSocket: () => ({
    isConnected: mocks.isConnected,
    connect: mocks.connect,
  }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.liveDataMode = true;
  mocks.isConnected = false;
  mocks.connect.mockResolvedValue(undefined);
});

const chip = () => screen.getByTestId('realtime-status');

describe('RealtimeStatus — off is a third state, not a permanent "connecting"', () => {
  it('reads "connected" once the socket is open', async () => {
    mocks.isConnected = true;
    const { RealtimeStatus } = await import('@/components/layout/RealtimeStatus');
    render(<RealtimeStatus />);

    await waitFor(() => {
      expect(chip().textContent).toContain('Live updates connected');
    });
    expect(chip().getAttribute('data-live-state')).toBe('connected');
  });

  it('reads "connecting" while Live is on and the socket is still opening', async () => {
    // `connect()` has not resolved yet — the honest shape of a socket mid-handshake.
    // A resolved promise here would set the component's own `connected` flag and
    // make this case indistinguishable from the connected one.
    mocks.isConnected = false;
    mocks.connect.mockReturnValue(new Promise<void>(() => {}));
    const { RealtimeStatus } = await import('@/components/layout/RealtimeStatus');
    render(<RealtimeStatus />);

    await waitFor(() => {
      expect(chip().getAttribute('data-live-state')).toBe('connecting');
    });
    expect(chip().textContent).toContain('Live updates connecting');
  });

  it('reads "off" — not "connecting" — when the user has Live switched off', async () => {
    // The defect. Live is off, so the socket was disconnected on purpose and
    // nothing is in flight: the chip asserted a transient fault forever.
    mocks.liveDataMode = false;
    mocks.isConnected = false;
    const { RealtimeStatus } = await import('@/components/layout/RealtimeStatus');
    render(<RealtimeStatus />);

    await waitFor(() => {
      expect(chip().getAttribute('data-live-state')).toBe('off');
    });
    expect(chip().textContent).toContain('Live updates off');
    expect(chip().textContent).not.toContain('connecting');
    // Fault vocabulary is exactly what this state must not borrow: "off" is a
    // setting the user chose, not a fault the app is recovering from.
    expect(chip().textContent).not.toMatch(/paused|reconnect/i);
    // And no connect attempt is made while Live is off.
    expect(mocks.connect).not.toHaveBeenCalled();
  });

  it('does not report "off" for a stale connected flag after Live is switched off', async () => {
    // `isConnected || connected` can still hold a true from before the toggle.
    // The user setting is authoritative: Live off means off, whatever the
    // socket's last observed state was.
    mocks.liveDataMode = false;
    mocks.isConnected = true;
    const { RealtimeStatus } = await import('@/components/layout/RealtimeStatus');
    render(<RealtimeStatus />);

    await waitFor(() => {
      expect(chip().getAttribute('data-live-state')).toBe('off');
    });
    expect(chip().textContent).not.toContain('connected');
  });
});