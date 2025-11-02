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
        return new Promise((resolve, reject) => {
            if (this.ws?.readyState === WebSocket.OPEN) {
                resolve();
                return;
            }

            if (this.isConnecting) {
                return;
            }

            this.isConnecting = true;
            this.shouldReconnect = true;

            try {
                const wsUrl = this.getWebSocketUrl();
                this.ws = new WebSocket(wsUrl);

                this.ws.onopen = () => {
                    console.log(`WebSocket connected: ${this._clientId}`);
                    this.isConnecting = false;
                    this.reconnectAttempts = 0;
                    this.startHeartbeat();

                    // Subscribe to topics
                    this.options.topics?.forEach(topic => {
                        this.subscribe(topic);
                    });

                    this.options.onConnect?.();
                    resolve();
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
                    this.isConnecting = false;
                    this.stopHeartbeat();
                    this.options.onDisconnect?.();

                    if (this.shouldReconnect && this.reconnectAttempts < this.maxReconnectAttempts) {
                        this.scheduleReconnect();
                    }
                };

                this.ws.onerror = (error) => {
                    console.error('WebSocket error:', error);
                    this.isConnecting = false;
                    this.options.onError?.(error);
                    reject(error);
                };

            } catch (error) {
                this.isConnecting = false;
                reject(error);
            }
        });
    }

    disconnect(): void {
        this.shouldReconnect = false;
        this.stopHeartbeat();

        if (this.ws) {
            this.ws.close(1000, 'Client disconnect');
            this.ws = null;
        }
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
  const { liveDataMode } = useUIStore();

  // Initialize WebSocket client
  if (!wsClientRef.current) {
    wsClientRef.current = new WebSocketClient(options);
  }

  const connect = useCallback(() => {
    return wsClientRef.current?.connect();
  }, []);

  const disconnect = useCallback(() => {
    wsClientRef.current?.disconnect();
  }, []);

  const subscribe = useCallback((topic: string) => {
    wsClientRef.current?.subscribe(topic);
  }, []);

  const unsubscribe = useCallback((topic: string) => {
    wsClientRef.current?.unsubscribe(topic);
  }, []);

  const send = useCallback((message: any) => {
    wsClientRef.current?.send(message);
  }, []);

  // Auto-connect when liveDataMode is enabled
  useEffect(() => {
    if (liveDataMode) {
      connect();
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
    isConnected: wsClientRef.current?.isConnected ?? false,
    readyState: wsClientRef.current?.readyState ?? WebSocket.CLOSED,
    clientId: (wsClientRef.current as any)?.clientId || ''
  };
}

// Hook for real-time analytics updates
export function useRealTimeAnalytics() {
    const [analyticsData, setAnalyticsData] = useState<any>({});
    const [marketData, setMarketData] = useState<any>({});
    const [portfolioData, setPortfolioData] = useState<any>({});
    const [lastUpdate, setLastUpdate] = useState<string | null>(null);

    const handleMessage = useCallback((message: WebSocketMessage) => {
        switch (message.type) {
            case 'analytics_update':
                setAnalyticsData((prev: any) => ({ ...prev, ...message.data }));
                break;
            case 'market_data_update':
                setMarketData(message.data);
                break;
            case 'portfolio_update':
                setPortfolioData(message.data);
                break;
            case 'broadcast':
                // Handle general broadcasts
                console.log('Broadcast message:', message);
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
            unsubscribe('analytics');
            unsubscribe('market_data');
            unsubscribe('portfolio');
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