/**
 * Formatting helpers — currency, dates, percentages.
 * Pure functions only; no imports from features or lib/ modules.
 */
import { format, formatDistanceToNow, parseISO } from 'date-fns'

export function formatCurrency(amount: number, currency = 'USD'): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(amount)
}

export function formatDate(isoString: string, pattern = 'MMM d, yyyy HH:mm'): string {
  return format(parseISO(isoString), pattern)
}

export function formatRelativeTime(isoString: string): string {
  return formatDistanceToNow(parseISO(isoString), { addSuffix: true })
}

export function formatPercent(value: number, decimals = 1): string {
  return `${(value * 100).toFixed(decimals)}%`
}

export function formatQuantity(qty: number, unit: string): string {
  return `${qty.toLocaleString()} ${unit}`
}

export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}
