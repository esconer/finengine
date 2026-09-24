/**
 * Main dashboard layout component for FinEngine
 * Provides responsive layout with sidebar navigation and header
 */

'use client';

import React, { useState, useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { Sidebar, navigation } from './Sidebar';
import { Header } from './Header';
import { NotificationContainer } from '@/components/ui/NotificationSystem';
import { RealtimeStatus } from './RealtimeStatus';
import { useUIStore } from '@/lib/store';
import { cn } from '@/lib/utils';

interface DashboardLayoutProps {
  children: React.ReactNode;
  title?: string;
  subtitle?: string;
  className?: string;
}

const routeTitles: Record<string, { title: string; subtitle?: string }> = Object.fromEntries(
  navigation.map((item) => [item.href, { title: item.title ?? item.name, subtitle: item.subtitle ?? item.description }])
);

export function DashboardLayout({ 
  children, 
  title: customTitle, 
  subtitle: customSubtitle, 
  className 
}: DashboardLayoutProps) {
  const pathname = usePathname();
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const darkMode = useUIStore((s) => s.darkMode);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);

  // Re-apply persisted dark mode after zustand hydration
  useEffect(() => {
    document.documentElement.classList.toggle('dark', darkMode);
  }, [darkMode]);

  // Handle responsive behavior
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)');
    const onChange = () => {
      setIsMobile(!mq.matches);
      if (mq.matches) {
        setMobileSidebarOpen(false);
      }
    };

    onChange();
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  // Handle overlay click on mobile
  const handleOverlayClick = () => {
    setMobileSidebarOpen(false);
  };

  // Get route info
  const routeInfo = routeTitles[pathname] || { title: 'Dashboard', subtitle: undefined };
  const displayTitle = customTitle || routeInfo.title;
  const displaySubtitle = customSubtitle || routeInfo.subtitle;

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-900">
      {/* Mobile sidebar overlay */}
      {isMobile && mobileSidebarOpen && (
        <div 
          className="fixed inset-0 z-40 bg-black bg-opacity-50 lg:hidden"
          onClick={handleOverlayClick}
        />
      )}

      {/* Sidebar */}
      <div
        className={cn(
          'fixed inset-y-0 left-0 z-50 transform transition-transform duration-300 ease-in-out lg:relative lg:translate-x-0',
          mobileSidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        )}
        inert={isMobile && !mobileSidebarOpen}
      >
        <Sidebar
          isCollapsed={!isMobile && !sidebarOpen}
          onToggleCollapse={!isMobile ? toggleSidebar : undefined}
          className="h-full"
        />
      </div>

      {/* Main content area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <Header
          title={displayTitle}
          subtitle={displaySubtitle}
          onMenuClick={() => setMobileSidebarOpen(true)}
        />

        {/* Page content */}
        <main className={cn(
          'flex-1 overflow-y-auto p-4 lg:p-6',
          className
        )}>
          <div className="mx-auto max-w-7xl">
            {children}
          </div>
        </main>
      </div>

      <RealtimeStatus />
      <NotificationContainer />
    </div>
  );
}

export default DashboardLayout;