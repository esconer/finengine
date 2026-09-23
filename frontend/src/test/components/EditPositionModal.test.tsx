import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { EditPositionModal } from '@/components/portfolio/EditPositionModal';
import { PortfolioPosition } from '@/types';

const position: PortfolioPosition = {
  id: 1,
  ticker: 'INFY.NS',
  weight: 0.1,
  quantity: 10,
  buy_price: 100,
  region: 'IN',
  primary_source: 'test',
  last_validated_source: 'test',
  last_price: 110,
  market_value: 1100,
  sector: 'IT',
  industry: 'Software',
  custom_name: 'Infosys',
  added_on: '2024-01-15T00:00:00',
  updated_on: '2024-06-01T00:00:00',
  total_cost: 1000,
  unrealized_gain_loss: 100,
  unrealized_gain_loss_pct: 10,
  current_value: 1100,
};

describe('EditPositionModal', () => {
  it('does not render when closed', () => {
    const { container } = render(
      <EditPositionModal isOpen={false} position={position} onClose={vi.fn()} onUpdate={vi.fn()} currency="INR" />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders an accessible dialog with labelled fields', async () => {
    render(
      <EditPositionModal isOpen position={position} onClose={vi.fn()} onUpdate={vi.fn()} currency="INR" />
    );
    expect(await screen.findByRole('dialog')).toBeDefined();
    expect(screen.getByLabelText('Portfolio Weight')).toBeDefined();
    expect(screen.getByLabelText('Quantity')).toBeDefined();
    expect(screen.getByLabelText('Average Buy Price (INR)')).toBeDefined();
    expect(screen.getByLabelText('Custom Name')).toBeDefined();
    expect(screen.getByLabelText('Purchase Date')).toBeDefined();
    expect(screen.getByRole('button', { name: 'Close' })).toBeDefined();
  });

  it('closes after a successful update', async () => {
    const onClose = vi.fn();
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(
      <EditPositionModal isOpen position={position} onClose={onClose} onUpdate={onUpdate} currency="INR" />
    );
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: /Update Position/ }));
    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(1, { quantity: 20 }));
    expect(onClose).toHaveBeenCalled();
  });

  it('stays open and shows an error when update fails', async () => {
    const onClose = vi.fn();
    const onUpdate = vi.fn().mockRejectedValue(new Error('boom'));
    render(
      <EditPositionModal isOpen position={position} onClose={onClose} onUpdate={onUpdate} currency="INR" />
    );
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: /Update Position/ }));
    expect(await screen.findByText('Failed to update position. Please try again.')).toBeDefined();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('closes on Escape', async () => {
    const onClose = vi.fn();
    render(
      <EditPositionModal isOpen position={position} onClose={onClose} onUpdate={vi.fn()} currency="INR" />
    );
    await screen.findByRole('dialog');
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('does not close on outside pointerdown', async () => {
    const onClose = vi.fn();
    render(
      <EditPositionModal isOpen position={position} onClose={onClose} onUpdate={vi.fn()} currency="INR" />
    );
    await screen.findByRole('dialog');
    fireEvent.pointerDown(document.body);
    expect(onClose).not.toHaveBeenCalled();
  });
});
