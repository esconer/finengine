import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { DashboardLayout } from '@/components/layout/DashboardLayout';

const websocketMocks = vi.hoisted(() => ({
  useWebSocket: vi.fn(() => ({ isConnected: false, connect: vi.fn().mockResolvedValue(undefined) })),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => '/dashboard',
}));

vi.mock('@/lib/websocket', () => ({
  useWebSocket: websocketMocks.useWebSocket,
}));

vi.mock('@/components/layout/Sidebar', () => ({
  navigation: [],
  Sidebar: () => <aside data-testid="sidebar-stub" />,
}));

vi.mock('@/components/layout/Header', () => ({
  Header: () => <header data-testid="header-stub" />,
}));

vi.mock('@/components/ui/NotificationSystem', () => ({
  NotificationContainer: () => null,
}));

vi.mock('@/lib/store', () => ({
  useUIStore: (selector: (state: any) => unknown) => selector({
    sidebarOpen: true,
    toggleSidebar: vi.fn(),
    darkMode: false,
  }),
}));

describe('DashboardLayout real-time lifecycle', () => {
  it('mounts the WebSocket-backed status indicator in the product shell', () => {
    render(
      <DashboardLayout>
        <div>page content</div>
      </DashboardLayout>
    );

    expect(screen.getByTestId('realtime-status')).toBeDefined();
    expect(websocketMocks.useWebSocket).toHaveBeenCalled();
  });
});
