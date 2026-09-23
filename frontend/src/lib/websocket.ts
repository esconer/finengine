/**
 * WebSocket client for real-time updates
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import { useUIStore } from './store';

interface WebSocketMessage {
    type: string;
    timestamp: string;
    data?: any;
    topic?: string;
}

interface WebSocketOptions {
    onMessage?: (message: WebSocketMessage) => void;
    onConnect?: () => void;
    onDisconnect?: () => void;
    onError?: (error: Event) => void;
    topics?: string[];
    autoReconnect?: boolean;
    reconnectInterval?: number;
}

export class WebSocketClient {
    private ws: WebSocket | null = null;
    private reconnectAttempts = 0;
    private maxReconnectAttempts = 5;
    private reconnectInterval = 1000;
    private heartbeatInterval: NodeJS.Timeout | null = null;
    private heartbeatTimeout: NodeJS.Timeout | null = null;
    private isConnecting = false;
    private shouldReconnect = true;
    private options: WebSocketOptions;
    private connectPromise: Promise<void> | null = null;
    private settleConnect: ((error?: Error) => void) | null = null;
  
    constructor(options: WebSocketOptions = {}) {
      this._clientId = this.generateClientId();
      this.options = {
        autoReconnect: true,
        reconnectInterval: 1000,
        topics: [],
        ...options
      };
    }
  
    private _clientId: string;

    private generateClientId(): string {
        return `client_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    }

    private getWebSocketUrl(): string {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

        // Extract host from API URL for WebSocket
        const urlHost = new URL(apiUrl).host;
        return `${protocol}//${urlHost}/api/v1/ws/ws/${this._clientId}`;
    }

    connect(): Promise<void> {
        if (this.ws?.readyState === WebSocket.OPEN) {
            return Promise.resolve();
        }

        // While a connection attempt is in flight, hand back the SAME promise
        // so every awaiter settles — never hang (B3).
        if (this.connectPromise) {
            return this.connectPromise;
        }

        this.isConnecting = true;
        this.shouldReconnect = true;
        // Fresh clientId per connection attempt — backend rejects duplicate
        // live ids with close code 1008 (B4).
        this._clientId = this.generateClientId();

        this.connectPromise = new Promise((resolve, reject) => {
            this.settleConnect = (error?: Error) => {
                this.connectPromise = null;
                this.settleConnect = null;
                this.isConnecting = false;
                if (error) reject(error);
                else resolve();
            };

            try {
                const wsUrl = this.getWebSocketUrl();
                this.ws = new WebSocket(wsUrl);

                this.ws.onopen = () => {
                    console.log(`WebSocket connected: ${this._clientId}`);
                    this.reconnectAttempts = 0;
                    this.startHeartbeat();

                    // Subscribe to topics
                    this.options.topics?.forEach(topic => {
                        this.subscribe(topic);
                    });

                    this.options.onConnect?.();
                    this.settleConnect?.();
                };

                this.ws.onmessage = (event) => {
                    try {
                        const message: WebSocketMessage = JSON.parse(event.data);
                        this.handleMessage(message);
                    } catch (error) {
                        console.error('Failed to parse WebSocket message:', error);
                    }
                };

                this.ws.onclose = (event) => {
                    console.log(`WebSocket disconnected: ${this._clientId}`, event.code, event.reason);
                    this.stopHeartbeat();
                    this.options.onDisconnect?.();

                    // Branch on close code (B17): 1008 = id-conflict policy close
                    // → reset backoff so the next attempt (with a fresh id) starts clean.
                    if (event.code === 1008) {
                        this.reconnectAttempts = 0;
                    }

                    // 1000 with shouldReconnect=false is a deliberate disconnect → no reconnect.
                    this.settleConnect?.(
                        event.code === 1008
                            ? new Error('Connection rejected: client id conflict (1008)')
                            : new Error(`Connection closed before open (${event.code})`)
                    );

                    if (this.shouldReconnect && this.reconnectAttempts < this.maxReconnectAttempts) {
                        this.scheduleReconnect();
                    }
                };

                this.ws.onerror = (error) => {
                    console.error('WebSocket error:', error);
                    this.options.onError?.(error);
                    // onclose follows onerror and schedules any reconnect
                    this.settleConnect?.(error instanceof Error ? error : new Error('WebSocket error'));
                };

            } catch (error) {
                this.settleConnect?.(error instanceof Error ? error : new Error(String(error)));
            }
        });

        return this.connectPromise;
    }

    disconnect(): void {
        this.shouldReconnect = false;
        this.stopHeartbeat();

        if (this.ws) {
            // Detach handlers BEFORE close so orphan sockets can't mutate
            // client state across generations (B18).
            this.ws.onopen = null;
            this.ws.onmessage = null;
            this.ws.onclose = null;
            this.ws.onerror = null;
            this.ws.close(1000, 'Client disconnect');
            this.ws = null;
        }

        // Settle any in-flight connect() so awaiters never hang (B3)
        this.settleConnect?.(new Error('Disconnected'));
    }

    private scheduleReconnect(): void {
        if (!this.shouldReconnect || this.reconnectAttempts >= this.maxReconnectAttempts) {
            return;
        }

        const delay = this.options.reconnectInterval! * Math.pow(2, this.reconnectAttempts);

        setTimeout(() => {
            if (this.shouldReconnect) {
                this.reconnectAttempts++;
                console.log(`WebSocket reconnect attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts}`);
                this.connect().catch(() => {
                    // Reconnect will be scheduled again if still needed
                });
            }
        }, delay);
    }

    private startHeartbeat(): void {
        this.heartbeatInterval = setInterval(() => {
            this.send({ type: 'ping' });
        }, 30000); // Send ping every 30 seconds

        this.heartbeatTimeout = setTimeout(() => {
            if (this.ws?.readyState === WebSocket.OPEN) {
                console.log('WebSocket heartbeat timeout, disconnecting');
                this.ws.close();
            }
        }, 60000); // Expect pong within 60 seconds
    }

    private stopHeartbeat(): void {
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
            this.heartbeatInterval = null;
        }

        if (this.heartbeatTimeout) {
            clearTimeout(this.heartbeatTimeout);
            this.heartbeatTimeout = null;
        }
    }

    private handleMessage(message: WebSocketMessage): void {
        // Handle heartbeat response
        if (message.type === 'pong') {
            if (this.heartbeatTimeout) {
                clearTimeout(this.heartbeatTimeout);
                this.heartbeatTimeout = setTimeout(() => {
                    if (this.ws?.readyState === WebSocket.OPEN) {
                        console.log('WebSocket heartbeat timeout, disconnecting');
                        this.ws.close();
                    }
                }, 60000);
            }
            return;
        }

        // Update last updated time for UI
        const { updateLastUpdated } = useUIStore.getState();
        updateLastUpdated();

        // Call custom message handler
        this.options.onMessage?.(message);
    }

    send(message: any): void {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
        } else {
            console.warn('WebSocket is not connected, cannot send message');
        }
    }

    subscribe(topic: string): void {
        this.send({
            type: 'subscribe',
            topic
        });
    }

    unsubscribe(topic: string): void {
        this.send({
            type: 'unsubscribe',
            topic
        });
    }

    updateOptions(options: WebSocketOptions): void {
        this.options = { ...this.options, ...options };
    }

    get readyState(): number {
        return this.ws?.readyState ?? WebSocket.CLOSED;
    }

    get isConnected(): boolean {
        return this.ws?.readyState === WebSocket.OPEN;
    }

    get clientId(): string {
        return this._clientId;
    }
}

// React hook for WebSocket
export function useWebSocket(options: WebSocketOptions = {}) {
  const wsClientRef = useRef<WebSocketClient | null>(null);
  const optionsRef = useRef<WebSocketOptions>(options);
  const { liveDataMode } = useUIStore();
  const [isConnected, setIsConnected] = useState(false);
  const [readyState, setReadyState] = useState<number>(WebSocket.CLOSED);
  const [clientId, setClientId] = useState<string>('');

  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

  const getClient = useCallback(() => {
    if (!wsClientRef.current) {
      wsClientRef.current = new WebSocketClient({
        ...optionsRef.current,
        onConnect: () => {
          setIsConnected(true);
          setReadyState(WebSocket.OPEN);
          optionsRef.current.onConnect?.();
        },
        onDisconnect: () => {
          setIsConnected(false);
          setReadyState(WebSocket.CLOSED);
          optionsRef.current.onDisconnect?.();
        },
        onMessage: (msg) => {
          optionsRef.current.onMessage?.(msg);
        },
        onError: (err) => {
          optionsRef.current.onError?.(err);
        }
      });
      if (wsClientRef.current.clientId) {
        setClientId(wsClientRef.current.clientId);
      }
    }
    return wsClientRef.current;
  }, []);

  const connect = useCallback(() => {
    return getClient().connect();
  }, [getClient]);

  const disconnect = useCallback(() => {
    wsClientRef.current?.disconnect();
  }, []);

  const subscribe = useCallback((topic: string) => {
    getClient().subscribe(topic);
  }, [getClient]);

  const unsubscribe = useCallback((topic: string) => {
    wsClientRef.current?.unsubscribe(topic);
  }, []);

  const send = useCallback((message: any) => {
    getClient().send(message);
  }, [getClient]);

  // Auto-connect when liveDataMode is enabled
  useEffect(() => {
    if (liveDataMode) {
      // Rejection is handled by onclose backoff — swallow to avoid
      // unhandled rejection from the floating promise (B3).
      connect().catch(() => {});
    } else {
      disconnect();
    }

    return () => {
      disconnect();
    };
  }, [liveDataMode, connect, disconnect]);

  return {
    connect,
    disconnect,
    subscribe,
    unsubscribe,
    send,
    isConnected,
    readyState,
    clientId
  };
}

// Hook for real-time analytics updates
export function useRealTimeAnalytics() {
    const [analyticsData, setAnalyticsData] = useState<any>(null);
    const [marketData, setMarketData] = useState<any>(null);
    const [portfolioData, setPortfolioData] = useState<any>(null);
    const [lastUpdate, setLastUpdate] = useState<string | null>(null);

    const handleMessage = useCallback((message: WebSocketMessage) => {
        switch (message.type) {
            case 'analytics_update':
                setAnalyticsData((prev: any) => ({ ...(prev || {}), ...message.data }));
                break;
            case 'market_data_update':
                setMarketData(message.data);
                break;
            case 'portfolio_update':
                setPortfolioData(message.data);
                break;
            case 'broadcast':
                break;
        }

        setLastUpdate(message.timestamp);
    }, []);

    const { subscribe, unsubscribe, isConnected } = useWebSocket({
        onMessage: handleMessage,
        topics: ['analytics', 'market_data', 'portfolio']
    });

    // Subscribe to topics when connected
    useEffect(() => {
        if (isConnected) {
            subscribe('analytics');
            subscribe('market_data');
            subscribe('portfolio');
        }

        return () => {
            if (isConnected) {
                unsubscribe('analytics');
                unsubscribe('market_data');
                unsubscribe('portfolio');
            }
        };
    }, [isConnected, subscribe, unsubscribe]);

    return {
        analyticsData,
        marketData,
        portfolioData,
        lastUpdate,
        isConnected,
        subscribe,
        unsubscribe
    };
}