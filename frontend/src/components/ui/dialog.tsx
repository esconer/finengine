/**
 * Dialog component for modals and overlays
 */

import React, { useEffect } from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { twMerge } from 'tailwind-merge';

interface DialogProps {
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
    children: React.ReactNode;
}

export const Dialog: React.FC<DialogProps> = ({ open, onOpenChange, children }) => {
    return React.createElement(
        DialogPrimitive.Root,
        { open, onOpenChange },
        children
    );
};

interface DialogTriggerProps {
    asChild?: boolean;
    children: React.ReactNode;
}

export const DialogTrigger: React.FC<DialogTriggerProps> = ({ asChild, children }) => {
    return React.createElement(
        DialogPrimitive.Trigger,
        { asChild },
        children
    );
};

interface DialogCloseProps {
    asChild?: boolean;
    children: React.ReactNode;
}

export const DialogClose: React.FC<DialogCloseProps> = ({ asChild, children }) => {
    return React.createElement(
        DialogPrimitive.Close,
        { asChild },
        children
    );
};

interface DialogContentProps {
    className?: string;
    overlayClassName?: string;
    children: React.ReactNode;
    /** Set false for flows where an accidental backdrop click would lose work (05-I8). */
    closeOnOutsideClick?: boolean;
}

export const DialogContent: React.FC<DialogContentProps> = ({
    className = '',
    overlayClassName = '',
    children,
    closeOnOutsideClick = true,
}) => {
    // Lock background scroll while the dialog is open
    useEffect(() => {
        const previous = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            document.body.style.overflow = previous;
        };
    }, []);

    return React.createElement(
        DialogPrimitive.Portal,
        null,
        React.createElement(
            DialogPrimitive.Overlay,
            {
                className: twMerge(
                    "fixed inset-0 bg-black/50 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
                    overlayClassName
                ),
            }
        ),
        React.createElement(
            DialogPrimitive.Content,
            {
                className: twMerge(
                    "fixed left-[50%] top-[50%] z-50 grid w-full max-w-lg translate-x-[-50%] translate-y-[-50%] gap-4 border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-6 shadow-lg duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%] data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%] sm:rounded-lg",
                    className
                ),
                onPointerDownOutside: (event: Event) => {
                    if (!closeOnOutsideClick) {
                        event.preventDefault();
                    }
                },
            },
            children
        )
    );
};

interface DialogHeaderProps {
    className?: string;
    children: React.ReactNode;
}

export const DialogHeader: React.FC<DialogHeaderProps> = ({ className = '', children }) => {
    return React.createElement(
        'div',
        { className: twMerge('flex flex-col space-y-1.5 text-center sm:text-left', className) },
        children
    );
};

interface DialogTitleProps {
    className?: string;
    children: React.ReactNode;
}

export const DialogTitle: React.FC<DialogTitleProps> = ({ className = '', children }) => {
    return React.createElement(
        DialogPrimitive.Title,
        { className: twMerge('text-lg font-semibold leading-none tracking-tight text-gray-900 dark:text-white', className) },
        children
    );
};

interface DialogDescriptionProps {
    className?: string;
    children: React.ReactNode;
}

export const DialogDescription: React.FC<DialogDescriptionProps> = ({ className = '', children }) => {
    return React.createElement(
        DialogPrimitive.Description,
        { className: twMerge('text-sm text-gray-600 dark:text-gray-400', className) },
        children
    );
};
