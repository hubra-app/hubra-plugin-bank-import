import { formatCHF } from '@hubra/plugin-sdk'
import type { Direction, PaymentStatus } from './api'

export const STATUS_COLOR: Record<PaymentStatus, string> = {
  matched: 'green',
  assigned: 'green',
  booked: 'teal',
  suggested: 'blue',
  unmatched: 'orange',
  mismatch: 'red',
  duplicate_payment: 'grape',
  ignored: 'gray',
  batch: 'gray',
}

export function signedAmount(direction: Direction, amount: string) {
  const value = formatCHF(Number(amount))
  return direction === 'debit' ? `− ${value}` : value
}
