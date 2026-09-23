import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { AddPositionModalSimple } from '@/components/portfolio/AddPositionModalSimple';
import { portfolioApi } from '@/lib/api';

vi.mock('@/lib/api', () => ({
  portfolioApi: {
    getPortfolio: vi.fn().mockResolvedValue({ total_value: 0, positions: [] }),
  },
}));

const openModal = (onAdd = vi.fn(), onClose = vi.fn()) =>
  render(
    <AddPositionModalSimple
      isOpen={true}
      onClose={onClose}
      onAdd={onAdd}
      currency="INR"
    />
  );

const fillValidForm = async () => {
  fireEvent.change(screen.getByPlaceholderText(/MOTHERSON\.NS/i), { target: { value: 'INFY.NS' } });
  fireEvent.change(screen.getByPlaceholderText('100'), { target: { value: '10' } });
  fireEvent.change(screen.getByPlaceholderText('100.00'), { target: { value: '1500' } });
  // Wait for the portfolio fetch to resolve so weight auto-calc runs
  await screen.findByDisplayValue('100.00%');
};

describe('AddPositionModalSimple Component', () => {
  it('does not render when isOpen is false', () => {
    const { container } = render(
      <AddPositionModalSimple
        isOpen={false}
        onClose={vi.fn()}
        onAdd={vi.fn()}
        currency="INR"
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders modal with form fields when isOpen is true', () => {
    openModal();
    expect(screen.getByText('Add New Position')).toBeDefined();
    expect(screen.getByPlaceholderText(/MOTHERSON\.NS/i)).toBeDefined();
    expect(screen.getByRole('dialog')).toBeDefined();
    expect(screen.getByRole('button', { name: 'Close' })).toBeDefined();
    expect(screen.getByLabelText('Stock Ticker *')).toBeDefined();
    expect(screen.getByLabelText('Quantity *')).toBeDefined();
    expect(screen.getByLabelText('Purchase Date')).toBeDefined();
  });

  it('calls onClose when Cancel button is clicked', () => {
    const onClose = vi.fn();
    openModal(vi.fn(), onClose);
    fireEvent.click(screen.getByText('Cancel'));
    expect(onClose).toHaveBeenCalled();
  });

  it('renders purchase date input defaulting to today', () => {
    openModal();
    const dateInput = screen.getByLabelText('Purchase Date') as HTMLInputElement;
    expect(dateInput.value).toBe(new Date().toISOString().split('T')[0]);
  });

  it('rejects a future purchase date', async () => {
    const onAdd = vi.fn();
    openModal(onAdd);
    await fillValidForm();
    fireEvent.change(screen.getByLabelText('Purchase Date'), { target: { value: '2999-01-01' } });
    // Submit the form directly: the date input's native max attribute would
    // otherwise block the click before our JS validation runs.
    fireEvent.submit(document.querySelector('form')!);
    expect(await screen.findByText('Purchase date cannot be in the future')).toBeDefined();
    expect(onAdd).not.toHaveBeenCalled();
  });

  it('passes added_on through on submit', async () => {
    const onAdd = vi.fn().mockResolvedValue(undefined);
    openModal(onAdd);
    await fillValidForm();
    fireEvent.change(screen.getByLabelText('Purchase Date'), { target: { value: '2024-06-15' } });
    fireEvent.click(screen.getByRole('button', { name: /Add Position/ }));
    expect(onAdd).toHaveBeenCalledTimes(1);
    expect(onAdd.mock.calls[0][0].added_on).toBe('2024-06-15');
  });

  it('blocks submit and shows retry when portfolio total fails to load', async () => {
    vi.mocked(portfolioApi.getPortfolio).mockRejectedValueOnce(new Error('offline'));
    const onAdd = vi.fn();
    openModal(onAdd);

    expect(await screen.findByText(/Couldn't load portfolio total/)).toBeDefined();
    fireEvent.change(screen.getByPlaceholderText(/MOTHERSON\.NS/i), { target: { value: 'INFY.NS' } });
    fireEvent.change(screen.getByPlaceholderText('100'), { target: { value: '10' } });
    fireEvent.change(screen.getByPlaceholderText('100.00'), { target: { value: '1500' } });

    const submitBtn = screen.getByRole('button', { name: /Add Position/ });
    expect((submitBtn as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(submitBtn);
    expect(onAdd).not.toHaveBeenCalled();
    // Weight must never be fabricated without a successful fetch
    expect(screen.getByDisplayValue('Auto-calculated')).toBeDefined();
  });

  it('recovers after a successful retry', async () => {
    vi.mocked(portfolioApi.getPortfolio).mockRejectedValueOnce(new Error('offline'));
    openModal();
    await screen.findByText(/Couldn't load portfolio total/);
    fireEvent.click(screen.getByText('Retry'));
    await waitFor(() => expect(screen.queryByText(/Couldn't load portfolio total/)).toBeNull());
    expect(screen.getByRole('button', { name: /Add Position/ })).not.toBeDisabled();
  });
});
