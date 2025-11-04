/**
 * Notification system for alerts and updates
 */

import React, { useEffect } from 'react';
import { X, CheckCircle, AlertCircle, AlertTriangle, Info } from 'lucide-react';
import { useNotifications, useEnhancedRealTimeAnalytics, useExportProgress } from '@/hooks/useRealTime';

interface NotificationProps {
    id: string;
    type: 'success' | 'error' | 'warning' | 'info';
    title: string;
    message: string;
    onClose: (id: string) => void;
    autoHide?: boolean;
    duration?: number;
}

const NotificationItem: React.FC<NotificationProps> = ({
    id,
    type,
    title,
    message,
    onClose,
    autoHide = true,
    duration = 5000
}) => {
    useEffect(() => {
        if (autoHide) {
            const timer = setTimeout(() => {
                onClose(id);
            }, duration);
            return () => clearTimeout(timer);
        }
    }, [id, autoHide, duration, onClose]);

    const icons = {
        success: CheckCircle,
        error: AlertCircle,
        warning: AlertTriangle,
        info: Info
    };

    const colors = {
        success: 'bg-green-50 border-green-200 text-green-800',
        error: 'bg-red-50 border-red-200 text-red-800',
        warning: 'bg-yellow-50 border-yellow-200 text-yellow-800',
        info: 'bg-blue-50 border-blue-200 text-blue-800'
    };

    const iconColors = {
        success: 'text-green-500',
        error: 'text-red-500',
        warning: 'text-yellow-500',
        info: 'text-blue-500'
    };

    const Icon = icons[type];

    return (
        <div className={`rounded-lg border p-4 shadow-lg transition-all duration-300 ease-in-out ${colors[type]} animate-in slide-in-from-top-full`}>
            <div className="flex items-start">
                <div className="flex-shrink-0">
                    <Icon className={`h-5 w-5 ${iconColors[type]}`} />
                </div>
                <div className="ml-3 flex-1">
                    <h3 className="text-sm font-medium">{title}</h3>
                    <p className="mt-1 text-sm opacity-90">{message}</p>
                </div>
                <div className="ml-4 flex-shrink-0">
                    <button
                        onClick={() => onClose(id)}
                        className={`inline-flex rounded-md ${iconColors[type]} hover:opacity-75 focus:outline-none focus:ring-2 focus:ring-offset-2`}
                    >
                        <X className="h-4 w-4" />
                    </button>
                </div>
            </div>
        </div>
    );
};

export const NotificationContainer: React.FC = () => {
    const { notifications, removeNotification } = useNotifications();

    return (
        <div className="fixed top-4 right-4 z-50 w-96 space-y-2 pointer-events-none">
            {notifications.map((notification) => (
                <div key={notification.id} className="pointer-events-auto">
                    <NotificationItem
                        {...notification}
                        onClose={removeNotification}
                    />
                </div>
            ))}
        </div>
    );
};

export const ExportProgressIndicator: React.FC = () => {
    const { exports, getActiveExports } = useExportProgress();
    const activeExports = getActiveExports();

    if (activeExports.length === 0) return null;

    return (
        <div className="fixed bottom-4 right-4 z-50 w-80">
            {activeExports.map((exportJob) => (
                <div key={exportJob.id} className="bg-white rounded-lg shadow-lg border p-4 mb-2">
                    <div className="flex items-center justify-between mb-2">
                        <h4 className="text-sm font-medium text-gray-900 truncate">
                            {exportJob.filename}
                        </h4>
                        <span className="text-xs text-gray-500">
                            {exportJob.progress}%
                        </span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-2">
                        <div
                            className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                            style={{ width: `${exportJob.progress}%` }}
                        />
                    </div>
                    <p className="text-xs text-gray-600 mt-1">
                        {exportJob.status === 'pending' && 'Preparing export...'}
                        {exportJob.status === 'processing' && 'Generating file...'}
                    </p>
                </div>
            ))}
        </div>
    );
};

export const ConnectionStatus: React.FC = () => {
    const { isConnected } = useEnhancedRealTimeAnalytics();
    const { showConnectionAlert } = useNotifications();

    useEffect(() => {
        showConnectionAlert(isConnected);
    }, [isConnected, showConnectionAlert]);

    if (!isConnected) {
        return (
            <div className="fixed bottom-4 left-4 z-50">
                <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
                    <div className="flex items-center">
                        <div className="animate-pulse w-2 h-2 bg-yellow-400 rounded-full mr-2" />
                        <span className="text-sm text-yellow-800">
                            Real-time updates disconnected
                        </span>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="fixed bottom-4 left-4 z-50">
            <div className="bg-green-50 border border-green-200 rounded-lg p-3">
                <div className="flex items-center">
                    <div className="w-2 h-2 bg-green-400 rounded-full mr-2 animate-pulse" />
                    <span className="text-sm text-green-800">
                        Real-time updates connected
                    </span>
                </div>
            </div>
        </div>
    );
};

export const LiveUpdateIndicator: React.FC<{ lastUpdate?: string | null }> = ({ lastUpdate }) => {
    const { dataFreshness, dataAge } = useEnhancedRealTimeAnalytics();

    if (!lastUpdate) return null;

    const getStatusColor = () => {
        switch (dataFreshness) {
            case 'fresh': return 'text-green-600';
            case 'stale': return 'text-yellow-600';
            case 'outdated': return 'text-red-600';
            default: return 'text-gray-600';
        }
    };

    const getStatusText = () => {
        switch (dataFreshness) {
            case 'fresh': return 'Live';
            case 'stale': return 'Stale';
            case 'outdated': return 'Outdated';
            default: return 'Unknown';
        }
    };

    const formatTime = (dateString: string) => {
        return new Date(dateString).toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit'
        });
    };

    return (
        <div className="flex items-center space-x-2 text-xs">
            <div className={`w-2 h-2 rounded-full ${dataFreshness === 'fresh' ? 'bg-green-500 animate-pulse' : dataFreshness === 'stale' ? 'bg-yellow-500' : 'bg-red-500'}`} />
            <span className={getStatusColor()}>
                {getStatusText()}
            </span>
            <span className="text-gray-500">
                {formatTime(lastUpdate)}
            </span>
            {dataAge > 0 && (
                <span className="text-gray-400">
                    ({dataAge.toFixed(1)}m ago)
                </span>
            )}
        </div>
    );
};

export const RefreshButton: React.FC<{
    onRefresh: () => void;
    isRefreshing: boolean;
    lastRefresh?: Date | null;
    disabled?: boolean;
}> = ({ onRefresh, isRefreshing, lastRefresh, disabled = false }) => {
    const formatLastRefresh = (date: Date | null) => {
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
        <button
            onClick={onRefresh}
            disabled={disabled || isRefreshing}
            className="inline-flex items-center px-3 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
        >
            <svg
                className={`-ml-1 mr-2 h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`}
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
            >
                <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
            </svg>
            {isRefreshing ? 'Refreshing...' : 'Refresh'}
            {lastRefresh && (
                <span className="ml-2 text-xs text-gray-500">
                    {formatLastRefresh(lastRefresh)}
                </span>
            )}
        </button>
    );
};

// Export progress hook