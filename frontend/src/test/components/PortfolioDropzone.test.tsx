import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { PortfolioDropzone } from '@/components/portfolio/PortfolioDropzone';
import apiClient, { portfolioApi } from '@/lib/api';

vi.mock('@/lib/api', () => ({
  default: { post: vi.fn().mockResolvedValue({}) },
  portfolioApi: {
    getPortfolio: vi.fn().mockResolvedValue({ total_value: 0, positions: [] }),
  },
}));

const makeFile = (name: string, content: string, sizeOverride?: number) => {
  const file = new File([content], name, { type: 'text/csv' });
  if (sizeOverride !== undefined) {
    Object.defineProperty(file, 'size', { value: sizeOverride });
  }
  return file;
};

const dropFile = (file: File) => {
  const dz = screen.getByLabelText('Upload tradebook CSV');
  fireEvent.drop(dz, { dataTransfer: { files: [file] } });
};

const open = () =>
  render(<PortfolioDropzone isOpen={true} onClose={vi.fn()} onSuccess={vi.fn()} />);

describe('PortfolioDropzone', () => {
  it('renders CSV-only title when open', () => {
    open();
    expect(screen.getByText('Import Portfolio (CSV)')).toBeDefined();
    expect(screen.queryByText(/Excel/)).toBeNull();
  });

  it('renders nothing when closed', () => {
    const { container } = render(
      <PortfolioDropzone isOpen={false} onClose={vi.fn()} onSuccess={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('exposes a keyboard-operable upload target', () => {
    open();
    const dz = screen.getByRole('button', { name: 'Upload tradebook CSV' });
    expect(dz.getAttribute('tabindex')).toBe('0');
    expect(screen.getByRole('button', { name: 'Close' })).toBeDefined();
    expect(screen.getByRole('dialog')).toBeDefined();
  });

  it('rejects non-CSV files', async () => {
    open();
    dropFile(makeFile('trade.pdf', 'binary'));
    expect(await screen.findByText('Only .csv or .txt files are supported.')).toBeDefined();
    expect(screen.queryByText(/Detected/)).toBeNull();
  });

  it('rejects files over 5 MB', async () => {
    open();
    dropFile(makeFile('big.csv', 'x', 6 * 1024 * 1024));
    expect(await screen.findByText('File is too large (max 5 MB).')).toBeDefined();
    expect(screen.queryByText(/Detected/)).toBeNull();
  });

  it('computes value-share weights and requires acknowledge before import', async () => {
    const onClose = vi.fn();
    const onSuccess = vi.fn();
    render(<PortfolioDropzone isOpen={true} onClose={onClose} onSuccess={onSuccess} />);

    dropFile(
      makeFile('p.csv', 'ticker,quantity,buy_price\nAAA.NS,10,100\nBBB.NS,5,100\n')
    );
    await screen.findByText(/Detected 2 valid positions/);

    const importBtn = screen.getByRole('button', { name: /Import 2 Positions/ });
    expect((importBtn as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByLabelText(/I understand each imported position/));
    expect((importBtn as HTMLButtonElement).disabled).toBe(false);

    // Existing book worth 900; batch adds 1500 → weights are value shares of 2400
    vi.mocked(portfolioApi.getPortfolio).mockResolvedValueOnce({
      total_value: 900,
      positions: [{ id: 1 }, { id: 2 }],
    } as any);

    fireEvent.click(importBtn);

    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(apiClient.post).mock.calls[0][1] as any;
    expect(payload.auto_normalize).toBe(true);
    expect(payload.positions[0].weight).toBeCloseTo(1000 / 2400, 5);
    expect(payload.positions[1].weight).toBeCloseTo(500 / 2400, 5);
    expect(payload.positions[0].weight + payload.positions[1].weight).toBeCloseTo(0.625, 5);
    expect(onSuccess).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});
