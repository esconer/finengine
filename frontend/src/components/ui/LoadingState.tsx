/**
 * Loading state components for enhanced UI
 */

import React from 'react';
import { Loader2 } from 'lucide-react';

interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg' | 'xl';
  className?: string;
  color?: 'blue' | 'green' | 'yellow' | 'red' | 'gray';
}

export const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({
  size = 'md',
  className = '',
  color = 'blue'
}) => {
  const sizeClasses = {
    sm: 'w-4 h-4',
    md: 'w-6 h-6',
    lg: 'w-8 h-8',
    xl: 'w-12 h-12'
  };

  const colorClasses = {
    blue: 'text-blue-600',
    green: 'text-green-600',
    yellow: 'text-yellow-600',
    red: 'text-red-600',
    gray: 'text-gray-600'
  };

  return (
    <Loader2 className={`animate-spin ${sizeClasses[size]} ${colorClasses[color]} ${className}`} />
  );
};

interface LoadingStateProps {
  message?: string;
  isLoading?: boolean;
  children?: React.ReactNode;
  className?: string;
}

export const LoadingState: React.FC<LoadingStateProps> = ({
  message = 'Loading...',
  isLoading = true,
  children,
  className = ''
}) => {
  if (!isLoading) {
    return <>{children}</>;
  }

  return (
    <div className={`flex flex-col items-center justify-center space-y-3 p-8 ${className}`}>
      <LoadingSpinner size="lg" />
      <p className="text-gray-600 text-sm">{message}</p>
    </div>
  );
};

interface DataTableLoadingProps {
  rows?: number;
  columns?: number;
  className?: string;
}

export const DataTableLoading: React.FC<DataTableLoadingProps> = ({
  rows = 5,
  columns = 4,
  className = ''
}) => {
  return (
    <div className={`space-y-3 ${className}`}>
      {/* Header */}
      <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}>
        {Array.from({ length: columns }).map((_, i) => (
          <div key={i} className="h-6 bg-gray-200 rounded animate-pulse" />
        ))}
      </div>

      {/* Rows */}
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div
          key={rowIndex}
          className="grid gap-4"
          style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}
        >
          {Array.from({ length: columns }).map((_, colIndex) => (
            <div
              key={colIndex}
              className="h-4 bg-gray-100 rounded animate-pulse"
              style={{ animationDelay: `${(rowIndex * columns + colIndex) * 50}ms` }}
            />
          ))}
        </div>
      ))}
    </div>
  );
};

interface ChartLoadingProps {
  height?: string;
  className?: string;
}

export const ChartLoading: React.FC<ChartLoadingProps> = ({
  height = 'h-64',
  className = ''
}) => {
  return (
    <div className={`${height} ${className} bg-gray-50 rounded-lg flex items-center justify-center`}>
      <div className="text-center">
        <LoadingSpinner size="lg" />
        <p className="text-gray-500 text-sm mt-2">Loading chart data...</p>
      </div>
    </div>
  );
};

interface MetricCardLoadingProps {
  count?: number;
  className?: string;
}

export const MetricCardLoading: React.FC<MetricCardLoadingProps> = ({
  count = 4,
  className = ''
}) => {
  return (
    <div className={`grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 ${className}`}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="bg-white p-6 rounded-lg border shadow-sm">
          <div className="animate-pulse">
            <div className="h-4 bg-gray-200 rounded w-3/4 mb-2" />
            <div className="h-8 bg-gray-200 rounded w-1/2 mb-1" />
            <div className="h-3 bg-gray-100 rounded w-1/4" />
          </div>
        </div>
      ))}
    </div>
  );
};

interface DashboardLoadingProps {
  className?: string;
}

export const DashboardLoading: React.FC<DashboardLoadingProps> = ({ className = '' }) => {
  return (
    <div className={`space-y-6 p-6 ${className}`}>
      {/* Header */}
      <div className="animate-pulse">
        <div className="h-8 bg-gray-200 rounded w-1/3 mb-2" />
        <div className="h-4 bg-gray-100 rounded w-1/2" />
      </div>

      {/* Metric Cards */}
      <MetricCardLoading />

      {/* Chart Area */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartLoading height="h-80" />
        <ChartLoading height="h-80" />
      </div>

      {/* Data Table */}
      <div className="bg-white p-6 rounded-lg border shadow-sm">
        <div className="animate-pulse">
          <div className="h-6 bg-gray-200 rounded w-1/4 mb-4" />
          <DataTableLoading rows={6} columns={5} />
        </div>
      </div>
    </div>
  );
};

interface RefreshIndicatorProps {
  isRefreshing: boolean;
  lastRefresh?: Date | null;
  autoRefreshEnabled?: boolean;
  className?: string;
}

export const RefreshIndicator: React.FC<RefreshIndicatorProps> = ({
  isRefreshing,
  lastRefresh,
  autoRefreshEnabled = false,
  className = ''
}) => {
  const formatLastRefresh = (date: Date | null | undefined) => {
    if (!date) return 'Never';
    
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    
    return date.toLocaleDateString();
  };

  return (
    <div className={`flex items-center space-x-2 text-xs ${className}`}>
      {isRefreshing && <LoadingSpinner size="sm" />}
      <span className={isRefreshing ? 'text-blue-600' : 'text-gray-500'}>
        {isRefreshing ? 'Refreshing...' : `Last updated: ${formatLastRefresh(lastRefresh)}`}
      </span>
      {autoRefreshEnabled && (
        <span className="inline-flex items-center px-2 py-1 rounded-full text-xs bg-green-100 text-green-800">
          Auto
        </span>
      )}
    </div>
  );
};

interface ErrorBoundaryState {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends React.Component<
  React.PropsWithChildren<{}>,
  ErrorBoundaryState
> {
  constructor(props: React.PropsWithChildren<{}>) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('Error caught by boundary:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center p-8 space-y-4">
          <div className="w-12 h-12 text-red-500">
            <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.732 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-gray-900">Something went wrong</h3>
          <p className="text-gray-600 text-center max-w-md">
            An error occurred while loading this component. Please try refreshing the page.
          </p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
          >
            Reload Page
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}