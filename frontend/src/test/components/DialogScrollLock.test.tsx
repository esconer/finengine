/**
 * The shared dialog wrapper ran its scroll-lock effect on MOUNT:
 *
 *     useEffect(() => { document.body.style.overflow = 'hidden'; ... }, [])
 *
 * Most dialogs are conditionally rendered, so for them mount IS the open
 * transition and the lock was correct by accident. `portfolio/manage` renders
 * its delete confirm permanently and flips `open`, so the effect fired once on
 * page load and pinned `document.body` to `overflow: hidden` for the lifetime
 * of the page — the confirm closed and the page still could not scroll.
 *
 * These assertions pin the lock to the open state, and pin it to the state at
 * the site that exposed it. They also hold the `aria-describedby` contract from
 * both sides: absent when a dialog has no description, present and resolving to
 * the description element when it does.
 *
 * Note on the second half: Radix 1.1 already omits `aria-describedby` when no
 * `DialogDescription` is mounted (`react-dialog@1.1.23` `dist/index.mjs`,
 * `DialogContentImpl`: `context.descriptionPresent ? context.descriptionId :
 * void 0`, where `descriptionPresent` is `descriptionCount > 0`). The absent-case
 * test is therefore a regression guard on Radix's own behaviour, not on a prop
 * this wrapper passes.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React, { useState } from 'react';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';

const mocks = vi.hoisted(() => ({
  getPerformanceHistory: vi.fn(),
  getForecastRisk: vi.fn(),
  getPortfolio: vi.fn(),
  rebalancePortfolio: vi.fn(),
  uploadPortfolioCsv: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  analyticsApi: {
    getPerformanceHistory: mocks.getPerformanceHistory,
    getForecastRisk: mocks.getForecastRisk,
  },
  portfolioApi: {
    getPortfolio: mocks.getPortfolio,
    rebalancePortfolio: mocks.rebalancePortfolio,
    uploadPortfolioCsv: mocks.uploadPortfolioCsv,
  },
}));

const positions = [
  { ticker: 'AAA.NS', weight: 0.6, quantity: 10, last_price: 100, market_value: 600, sector: 'Bank' },
  { ticker: 'BBB.NS', weight: 0.4, quantity: 5, last_price: 200, market_value: 400, sector: 'Auto' },
];

vi.mock('@/lib/store', () => {
  const useUIStore = Object.assign(
    () => ({ lastUpdated: null, updateLastUpdated: vi.fn() }),
    { getState: () => ({ lastUpdated: null, updateLastUpdated: vi.fn() }) },
  );
  return {
    usePortfolioStore: () => ({
      positions,
      fetchPortfolio: mocks.getPortfolio,
      isLoading: false,
      error: null,
      totalValue: 1000,
      currency: 'INR',
      setCurrency: vi.fn(),
      setPortfolioSnapshot: vi.fn(),
      setPositionCount: vi.fn(),
    }),
    useUIStore,
  };
});

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(''),
  usePathname: () => '/portfolio/manage',
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

/**
 * The shape that broke: `DialogContent` stays mounted and `open` toggles, so
 * mount is not the open transition.
 */
const PermanentlyRenderedDialog = ({ onOpen }: { onOpen?: (open: boolean) => void }) => {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>open it</button>
      <Dialog open={open} onOpenChange={(next) => { setOpen(next); onOpen?.(next); }}>
        <DialogContent closeOnOutsideClick={false}>
          <DialogTitle>Confirm Delete</DialogTitle>
          <p>Are you sure?</p>
        </DialogContent>
      </Dialog>
    </>
  );
};

const openPermanentlyRendered = async (): Promise<{ close: () => Promise<void> }> => {
  render(<PermanentlyRenderedDialog />);
  fireEvent.click(screen.getByRole('button', { name: 'open it' }));
  await screen.findByRole('dialog');
  return {
    close: async () => {
      fireEvent.keyDown(document, { key: 'Escape' });
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    },
  };
};

beforeEach(() => {
  vi.clearAllMocks();
  // jsdom shares one document across tests in a file; a leaked `overflow` would
  // make the closed-state assertion pass for the wrong reason.
  document.body.style.overflow = '';
  mocks.getPortfolio.mockResolvedValue({
    positions,
    total_value: 1000,
    total_positions: 2,
    total_weight: 1,
    sectors: [{ sector: 'Bank', value: 0.6 }],
    currency: 'INR',
  });
});

describe('dialog scroll lock follows the open state, not mount', () => {
  it('does not lock document.body while a permanently-rendered dialog is closed', async () => {
    render(<PermanentlyRenderedDialog />);

    // The dialog has never been opened, so the page behind it is live.
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.body.style.overflow).not.toBe('hidden');
  });

  it('locks while open and releases on close', async () => {
    const { close } = await openPermanentlyRendered();
    expect(document.body.style.overflow).toBe('hidden');

    await close();
    await waitFor(() => expect(document.body.style.overflow).not.toBe('hidden'));
  });

  it('restores the value the lock replaced, not the value the lock wrote', async () => {
    // A host page may already own the body's overflow (an in-progress page
    // transition, a sticky header). The lock has to put that back, not the
    // `hidden` it wrote over it.
    document.body.style.overflow = 'scroll';

    const { close } = await openPermanentlyRendered();
    expect(document.body.style.overflow).toBe('hidden');

    await close();
    await waitFor(() => expect(document.body.style.overflow).toBe('scroll'));
  });

  it('re-captures on reopen instead of replaying the first lock', async () => {
    // The saved value is cleared when the lock is released. If it were left
    // behind, a second open/close cycle would "restore" the value captured on
    // the FIRST cycle and stomp on whatever the host set in between.
    render(<PermanentlyRenderedDialog />);
    const opener = screen.getByRole('button', { name: 'open it' });

    fireEvent.click(opener);
    await screen.findByRole('dialog');
    expect(document.body.style.overflow).toBe('hidden');
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(document.body.style.overflow).toBe(''));

    // The host takes the body over between cycles.
    document.body.style.overflow = 'auto';

    fireEvent.click(opener);
    await screen.findByRole('dialog');
    expect(document.body.style.overflow).toBe('hidden');
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(document.body.style.overflow).toBe('auto'));
  });

  it('portfolio/manage: the page stays scrollable with the delete confirm closed', async () => {
    const { default: Page } = await import('@/app/portfolio/manage/page');
    render(<Page />);

    // Wait for the real page to have mounted and fetched; the confirm is
    // rendered permanently and closed at this point.
    const opener = await screen.findByRole('button', { name: 'Delete AAA.NS' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.body.style.overflow).not.toBe('hidden');

    fireEvent.click(opener);
    await screen.findByRole('dialog');
    expect(document.body.style.overflow).toBe('hidden');

    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(document.body.style.overflow).not.toBe('hidden'));
  });
});

describe('aria-describedby matches the description that is actually rendered', () => {
  it('is absent when the dialog renders no DialogDescription', async () => {
    render(<PermanentlyRenderedDialog />);
    fireEvent.click(screen.getByRole('button', { name: 'open it' }));
    const dialog = await screen.findByRole('dialog');

    expect(dialog).not.toHaveAttribute('aria-describedby');
  });

  it('portfolio/manage: the delete confirm points at no description', async () => {
    const { default: Page } = await import('@/app/portfolio/manage/page');
    render(<Page />);

    fireEvent.click(await screen.findByRole('button', { name: 'Delete AAA.NS' }));
    const dialog = await screen.findByRole('dialog');

    expect(dialog).not.toHaveAttribute('aria-describedby');
  });

  it('still points at the description when a DialogDescription IS rendered', async () => {
    // The counterpart to the assertion above, and the reason the wrapper must
    // NOT hardcode `aria-describedby={undefined}`: three dialogs in this app
    // (AddPositionModalSimple, EditPositionModal, PortfolioDropzone) render a
    // real description, and the wrapper's props are spread over Radix's
    // computed value. A blanket `undefined` would strip a correct association.
    const { AddPositionModalSimple } = await import('@/components/portfolio/AddPositionModalSimple');
    render(
      <AddPositionModalSimple
        isOpen={true}
        onClose={vi.fn()}
        onAdd={vi.fn()}
        currency="INR"
      />
    );

    const dialog = await screen.findByRole('dialog');
    const describedBy = dialog.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();

    const description = document.getElementById(describedBy as string);
    expect(description).not.toBeNull();
    expect(description?.textContent).toContain('Add a stock position to your portfolio');
  });
});
