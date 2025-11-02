/**
 * Dialog component for modals and overlays
 */

import React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';

interface DialogProps {
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
    children: React.ReactNode;
}

export const Dialog: React.FC<DialogProps> = ({ open, onOpenChange, children }) => {
    return (
        <DialogPrimitive.Root open= { open } onOpenChange = { onOpenChange } >
            { children }
            </DialogPrimitive.Root>
  );
};

interface DialogTriggerProps {
    asChild?: boolean;
    children: React.ReactNode;
}

export const DialogTrigger: React.FC<DialogTriggerProps> = ({ asChild, children }) => {
    return <DialogPrimitive.Trigger asChild={ asChild }> { children } </DialogPrimitive.Trigger>;
};

interface DialogContentProps {
    className?: string;
    children: React.ReactNode;
}

export const DialogContent: React.FC<DialogContentProps> = ({ className = '', children }) => {
    return (
        <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className= "fixed inset-0 bg-black/50 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
        className={ `fixed left-[50%] top-[50%] z-50 grid w-full max-w-lg translate-x-[-50%] translate-y-[-50%] gap-4 border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-6 shadow-lg duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%] data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%] sm:rounded-lg ${className}` }
      >
        { children }
        </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
  );
};

interface DialogHeaderProps {
    className?: string;
    children: React.ReactNode;
}

export const DialogHeader: React.FC<DialogHeaderProps> = ({ className = '', children }) => {
    return <div className={ `flex flex-col space-y-1.5 text-center sm:text-left ${className}` }> { children } </div>;
};

interface DialogTitleProps {
    className?: string;
    children: React.ReactNode;
}

export const DialogTitle: React.FC<DialogTitleProps> = ({ className = '', children }) => {
    return (
        <DialogPrimitive.Title
      className= {`text-lg font-semibold leading-none tracking-tight text-gray-900 dark:text-white ${className}`
}
    >
    { children }
    </DialogPrimitive.Title>
  );
};

interface DialogDescriptionProps {
    className?: string;
    children: React.ReactNode;
}

export const DialogDescription: React.FC<DialogDescriptionProps> = ({ className = '', children }) => {
    return (
        <DialogPrimitive.Description
      className= {`text-sm text-gray-600 dark:text-gray-400 ${className}`
}
    >
    { children }
    </DialogPrimitive.Description>
  );
};