import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { AddPositionModalSimple } from '@/components/portfolio/AddPositionModalSimple';

vi.mock('@/lib/api', () => ({
  portfolioApi: {
    getSummary: vi.fn().mockResolvedValue({ total_value: 0, positions: [] }),
  },
}));

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
    render(
      <AddPositionModalSimple
        isOpen={true}
        onClose={vi.fn()}
        onAdd={vi.fn()}
        currency="INR"
      />
    );
    expect(screen.getByText('Add New Position')).toBeDefined();
    expect(screen.getByPlaceholderText(/MOTHERSON\.NS/i)).toBeDefined();
  });

  it('calls onClose when Cancel button is clicked', () => {
    const onClose = vi.fn();
    render(
      <AddPositionModalSimple
        isOpen={true}
        onClose={onClose}
        onAdd={vi.fn()}
        currency="INR"
      />
    );
    fireEvent.click(screen.getByText('Cancel'));
    expect(onClose).toHaveBeenCalled();
  });

  it('renders purchase date input defaulting to today', () => {
    const { container } = render(
      <AddPositionModalSimple
        isOpen={true}
        onClose={vi.fn()}
        onAdd={vi.fn()}
        currency="INR"
      />
    );
    const dateInput = container.querySelector('input[type="date"]') as HTMLInputElement;
    expect(dateInput).toBeDefined();
    expect(dateInput.value).toBe(new Date().toISOString().split('T')[0]);
  });

  it('rejects a future purchase date', async () => {
    const onAdd = vi.fn();
    const { container } = render(
      <AddPositionModalSimple
        isOpen={true}
        onClose={vi.fn()}
        onAdd={onAdd}
        currency="INR"
      />
    );
    fireEvent.change(screen.getByPlaceholderText(/MOTHERSON\.NS/i), { target: { value: 'INFY.NS' } });
    fireEvent.change(screen.getByPlaceholderText('100'), { target: { value: '10' } });
    fireEvent.change(screen.getByPlaceholderText('100.00'), { target: { value: '1500' } });
    const dateInput = container.querySelector('input[type="date"]') as HTMLInputElement;
    fireEvent.change(dateInput, { target: { value: '2999-01-01' } });
    fireEvent.submit(container.querySelector('form')!);
    expect(await screen.findByText('Purchase date cannot be in the future')).toBeDefined();
    expect(onAdd).not.toHaveBeenCalled();
  });

  it('passes added_on through on submit', async () => {
    const onAdd = vi.fn().mockResolvedValue(undefined);
    const { container } = render(
      <AddPositionModalSimple
        isOpen={true}
        onClose={vi.fn()}
        onAdd={onAdd}
        currency="INR"
      />
    );
    fireEvent.change(screen.getByPlaceholderText(/MOTHERSON\.NS/i), { target: { value: 'INFY.NS' } });
    fireEvent.change(screen.getByPlaceholderText('100'), { target: { value: '10' } });
    fireEvent.change(screen.getByPlaceholderText('100.00'), { target: { value: '1500' } });
    const dateInput = container.querySelector('input[type="date"]') as HTMLInputElement;
    fireEvent.change(dateInput, { target: { value: '2024-06-15' } });
    fireEvent.click(screen.getByText('Add Position'));
    expect(onAdd).toHaveBeenCalledTimes(1);
    expect(onAdd.mock.calls[0][0].added_on).toBe('2024-06-15');
  });
});
