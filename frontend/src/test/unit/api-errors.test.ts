import { describe, it, expect } from 'vitest';
import { AppError, buildApiErrorMessage } from '@/lib/api';

describe('buildApiErrorMessage (04-B1/04-B2)', () => {
  it('reads string detail for 503 vendor outages', () => {
    expect(buildApiErrorMessage(503, { detail: 'yfinance: upstream timeout' })).toBe(
      'yfinance: upstream timeout'
    );
  });

  it('joins FastAPI 422 array detail with field names', () => {
    expect(
      buildApiErrorMessage(422, {
        detail: [{ loc: ['body', 'weight'], msg: 'Input should be <= 1' }],
      })
    ).toBe('weight: Input should be <= 1');
  });

  it('formats array detail on non-422 statuses too', () => {
    expect(
      buildApiErrorMessage(400, {
        detail: [{ loc: ['query', 'ticker'], msg: 'Not found' }],
      })
    ).toBe('ticker: Not found');
  });

  it('falls back to message, then error, then HTTP status', () => {
    expect(buildApiErrorMessage(500, { message: 'boom' })).toBe('boom');
    expect(buildApiErrorMessage(500, { error: 'kaboom' })).toBe('kaboom');
    expect(buildApiErrorMessage(500, {})).toBe('HTTP 500');
    expect(buildApiErrorMessage(503, null)).toBe('HTTP 503');
  });

  it('keeps friendly 422/409 defaults when body is empty', () => {
    expect(buildApiErrorMessage(422, {})).toBe('Validation failed. Please check your input data.');
    expect(buildApiErrorMessage(409, {})).toBe('This ticker already exists in your portfolio');
  });
});

describe('AppError (04-B2)', () => {
  it('carries status and detail beyond a bare Error', () => {
    const err = new AppError('service unavailable', { status: 503, detail: 'yfinance down' });
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe('AppError');
    expect(err.message).toBe('service unavailable');
    expect(err.status).toBe(503);
    expect(err.detail).toBe('yfinance down');
  });

  it('works without status (network errors)', () => {
    const err = new AppError('Network Error');
    expect(err.status).toBeUndefined();
    expect(err.detail).toBeUndefined();
  });
});
