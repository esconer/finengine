/**
 * Dashboard layout - wraps all dashboard pages with the main layout components
 * This layout provides the sidebar navigation and header for all dashboard routes
 */

import type { Metadata } from 'next';
import { DashboardLayout } from '@/components/layout/DashboardLayout';

export const metadata: Metadata = {
  title: {
    template: '%s | Daisy Risk Engine',
    default: 'Daisy Risk Engine - Portfolio Risk Management',
  },
  description: 'Advanced portfolio risk management and analytics platform',
};

export default function RootDashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <DashboardLayout>
      {children}
    </DashboardLayout>
  );
}