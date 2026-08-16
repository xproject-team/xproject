/**
 * Regression coverage for the DISPATCH-scan-failure surfacing fix.
 *
 * Before this fix: a 409 from the backend (e.g. AllocationNotFoundError,
 * "No allocation found... Configure stock before dispatching") was
 * discarded in favor of Axios's generic "Request failed with status code
 * 409", and the resulting history row was labelled "Scan recorded" —
 * actively misleading about a scan that had just failed.
 */
import { describe, expect, it } from 'vitest'

import { extractScanErrorMessage } from './scanErrorMessage'
import { rowLabel, type ScanHistoryRowData } from './ScanHistoryRow'

describe('extractScanErrorMessage', () => {
  it('surfaces the backend detail.message from a structured 4xx response', () => {
    const err = {
      response: {
        data: {
          detail: {
            error: 'allocation_not_found',
            message:
              'No allocation found for event abc + product def. Configure stock before dispatching.',
          },
        },
      },
    }
    expect(extractScanErrorMessage(err)).toBe(
      'No allocation found for event abc + product def. Configure stock before dispatching.',
    )
  })

  it('surfaces a plain string detail if that is the shape returned', () => {
    const err = { response: { data: { detail: 'Something went wrong.' } } }
    expect(extractScanErrorMessage(err)).toBe('Something went wrong.')
  })

  it('falls back to err.message when there is no response body (e.g. genuine network failure)', () => {
    expect(extractScanErrorMessage(new Error('Network Error'))).toBe('Network Error')
  })

  it('falls back to a generic message for a totally unrecognized error shape', () => {
    expect(extractScanErrorMessage('not an error object')).toBe(
      'Scan submission failed. Try again.',
    )
  })
})

describe('rowLabel', () => {
  it('never labels a failed scan "Scan recorded"', () => {
    const row: ScanHistoryRowData = {
      kind: 'failed',
      clientEventId: 'c1',
      productName: null,
      barcodeRaw: null,
      errorMessage: 'No allocation found for event abc + product def.',
      createdAt: Date.now(),
    }
    expect(rowLabel(row)).toBe('Scan failed')
    expect(rowLabel(row)).not.toBe('Scan recorded')
  })

  it('still prefers a known product/barcode name on a failed row', () => {
    const row: ScanHistoryRowData = {
      kind: 'failed',
      clientEventId: 'c1',
      productName: 'Beefeater Gin 1L',
      barcodeRaw: '123456',
      errorMessage: 'boom',
      createdAt: Date.now(),
    }
    expect(rowLabel(row)).toBe('Beefeater Gin 1L')
  })

  it('leaves the queued fallback label unchanged ("Scan recorded" is correct there)', () => {
    const row: ScanHistoryRowData = {
      kind: 'queued',
      clientEventId: 'c1',
      productName: null,
      barcodeRaw: null,
      createdAt: Date.now(),
    }
    expect(rowLabel(row)).toBe('Scan recorded')
  })
})
