import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { WebSocketClient } from '@/lib/websocket';

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: FakeWebSocket[] = [];
  url: string;
  readyState = 0;
  onopen: ((ev?: unknown) => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: ((ev: { code: number; reason: string }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  sent: string[] = [];
  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = FakeWebSocket.CLOSED;
  }
}

function openLatest(): FakeWebSocket {
  const inst = FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
  inst.readyState = FakeWebSocket.OPEN;
  inst.onopen?.();
  return inst;
}

describe('WebSocketClient lifecycle (04-B3/B4/B17/B18)', () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('returns the same in-flight promise while connecting — never hangs (B3)', async () => {
    const client = new WebSocketClient();
    const p1 = client.connect();
    const p2 = client.connect();
    expect(p2).toBe(p1);
    openLatest();
    await expect(p1).resolves.toBeUndefined();
    client.disconnect();
  });

  it('regenerates clientId per connection attempt and puts it in the URL (B4)', async () => {
    const client = new WebSocketClient();
    const ctorId = client.clientId;

    const p1 = client.connect();
    const attempt1Id = client.clientId;
    expect(attempt1Id).not.toBe(ctorId);
    openLatest();
    await p1;
    client.disconnect();

    const p2 = client.connect();
    const attempt2Id = client.clientId;
    expect(attempt2Id).not.toBe(attempt1Id);
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(FakeWebSocket.instances[1].url).toContain(attempt2Id);
    openLatest();
    await p2;
    client.disconnect();
  });

  it('on close 1008 resets backoff and reconnects with a fresh id (B4/B17)', async () => {
    const client = new WebSocketClient({ reconnectInterval: 10 });
    const p1 = client.connect();
    const first = openLatest();
    await p1;
    const id1 = client.clientId;

    first.readyState = FakeWebSocket.CLOSED;
    first.onclose?.({ code: 1008, reason: 'duplicate id' });

    // attempts were reset to 0 → retry fires after the base interval, not a burned budget
    vi.advanceTimersByTime(10);
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(client.clientId).not.toBe(id1);
    expect(FakeWebSocket.instances[1].url).toContain(client.clientId);
    client.disconnect();
  });

  it('does not reconnect after deliberate disconnect (close 1000 path, B17)', async () => {
    const client = new WebSocketClient({ reconnectInterval: 10 });
    const p1 = client.connect();
    const first = openLatest();
    await p1;

    client.disconnect(); // shouldReconnect=false, handlers detached
    // even if an orphan close arrived with 1000, no new socket may appear
    first.onclose?.({ code: 1000, reason: 'normal' });
    vi.advanceTimersByTime(1000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('detaches all handlers before close on disconnect (B18)', async () => {
    const client = new WebSocketClient();
    const p = client.connect();
    const pending = expect(p).rejects.toThrow('Disconnected');
    const inst = FakeWebSocket.instances[0];
    client.disconnect();
    expect(inst.onopen).toBeNull();
    expect(inst.onmessage).toBeNull();
    expect(inst.onclose).toBeNull();
    expect(inst.onerror).toBeNull();
    await pending;
  });
});
