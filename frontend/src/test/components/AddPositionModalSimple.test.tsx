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
});
