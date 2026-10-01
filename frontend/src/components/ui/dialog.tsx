/**
 * Dialog component for modals and overlays
 */

import React, { useEffect, useRef } from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { twMerge } from 'tailwind-merge';

interface DialogProps {
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
    children: React.ReactNode;
}

/**
 * `DialogContent` may be rendered permanently with `open` flipping (the shape
 * `portfolio/manage`'s delete confirm uses), so it cannot infer the open
 * transition from its own lifecycle. `Dialog` publishes the flag instead.
 */
const OpenContext = React.createContext(false);

export const Dialog: React.FC<DialogProps> = ({ open, onOpenChange, children }) => {
    return React.createElement(
        OpenContext.Provider,
        { value: open ?? false },
        React.createElement(
            DialogPrimitive.Root,
            { open, onOpenChange },
            children
        )
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
    /**
     * Take over where focus lands after teardown. Supply a handler to opt out of
     * the built-in opener restore entirely; call `event.preventDefault()` in it
     * to also suppress Radix's own `DialogTrigger`-ref restore.
     */
    onCloseAutoFocus?: (event: Event) => void;
}

export const DialogContent: React.FC<DialogContentProps> = ({
    className = '',
    overlayClassName = '',
    children,
    closeOnOutsideClick = true,
    onCloseAutoFocus,
}) => {
    /**
     * The same trap the opener capture below falls into, and for the same
     * reason: a permanently rendered content never remounts, so mounting is not
     * the open transition. Reading the flag from `OpenContext` rather than
     * from this component's own lifecycle is what makes the lock keyable.
     */
    const open = React.useContext(OpenContext);

    /**
     * Lock background scroll while the dialog is OPEN.
     *
     * The saved value lives in a ref rather than a closure local, because the
     * restore runs from the cleanup but has to see the value the EFFECT body
     * captured.
     *
     * The `if (!open) return` guard is what keeps the lock from capturing its
     * own write. React always runs a cleanup before re-running an effect, and
     * this body only executes on the closed -> open edge — where the previous
     * cleanup has already put the body back the way it was. So by the time the
     * capture runs, the only `hidden` it could see is one this component is not
     * responsible for. Capturing unconditionally, or keying the effect so that
     * it re-runs while still locked, is what would read `hidden` back and
     * "restore" it, leaving the page permanently scrolled shut.
     */
    const previousOverflowRef = useRef<string | null>(null);
    useEffect(() => {
        if (!open) return;
        previousOverflowRef.current = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            document.body.style.overflow = previousOverflowRef.current ?? '';
            // Nothing may replay this value as a "restore" later; the next lock
            // has to capture for itself.
            previousOverflowRef.current = null;
        };
    }, [open]);

    /**
     * Radix restores focus to its own `DialogTrigger` ref and unconditionally
     * preventDefaults `FocusScope`'s fallback (`react-dialog/dist/index.mjs`,
     * `onCloseAutoFocus`). That trigger ref is `null` whenever the dialog is
     * driven by external `open` state instead of a `DialogTrigger`, so closing
     * one drops focus on `<body>` and the next Tab restarts from the top of the
     * document. Record the opener on mount and hand it back on close.
     *
     * Mount IS the open transition for the conditional-render shape; for a
     * permanently rendered content whose `open` flips, the transition arrives as
     * a prop change. Either way this effect runs on the commit that opens the
     * dialog, which is also the pass in which `FocusScope`'s container ref is
     * still null — its autofocus is a later pass, so focus has not yet moved
     * into the dialog.
     *
     * The ref is deliberately not cleared on close: passive cleanups of a
     * deleted subtree run parent-first, so clearing here would blank it before
     * `FocusScope` reaches `onCloseAutoFocus`.
     */
    const openerRef = useRef<HTMLElement | null>(null);
    useEffect(() => {
        if (!open) return;
        openerRef.current = document.activeElement as HTMLElement | null;
    }, [open]);

    const restoreFocusToOpener = (event: Event) => {
        // Radix would otherwise focus its trigger ref, which this dialog does
        // not have.
        event.preventDefault();
        const opener = openerRef.current;
        // Deferred: this handler already runs inside `FocusScope`'s unmount
        // task, and restoring synchronously is undone by the scope unwinding
        // afterwards. The opener may also have left the document in the
        // meantime — the row that opened the dialog is gone after a successful
        // delete — so re-check before touching it.
        setTimeout(() => {
            if (opener?.isConnected) opener.focus();
        }, 0);
    };

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
                // Radix enforces modality by marking siblings `aria-hidden`
                // rather than by emitting the attribute. Both mechanisms are
                // correct, but this project's audits and older AT read the
                // attribute, so state it explicitly.
                'aria-modal': 'true',
                className: twMerge(
                    "fixed left-[50%] top-[50%] z-50 grid w-full max-w-lg translate-x-[-50%] translate-y-[-50%] gap-4 border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-6 shadow-lg duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%] data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%] sm:rounded-lg",
                    className
                ),
                onCloseAutoFocus: onCloseAutoFocus ?? restoreFocusToOpener,
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
