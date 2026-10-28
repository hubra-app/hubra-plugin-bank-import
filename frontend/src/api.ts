import { apiFetch, apiFetchRaw } from '@hubra/plugin-sdk'

export type PaymentStatus = 'matched' | 'unmatched' | 'mismatch' | 'duplicate_payment' | 'assigned'

export interface ImportItem {
  bankReference: string
  qrReference: string | null
  amount: string
  currency: string
  bookedOn: string
  debtorName: string | null
  status: Exclude<PaymentStatus, 'assigned'>
  invoiceId: number | null
  invoiceAmount: string | null
}

export interface ImportResult {
  dryRun: boolean
  summary: Record<
    'matched' | 'unmatched' | 'mismatch' | 'duplicate_payment' | 'already_imported',
    number
  >
  items: ImportItem[]
}

export interface BankPayment {
  id: number
  bankReference: string
  qrReference: string | null
  amount: string
  currency: string
  bookedOn: string
  debtorName: string | null
  remittance: string | null
  status: PaymentStatus
  invoiceId: number | null
  fileName: string | null
}

export async function importCamt054(file: File, dryRun: boolean): Promise<ImportResult> {
  const form = new FormData()
  form.append('file', file)
  const res = await apiFetchRaw(`/bank/camt054${dryRun ? '?dry_run=1' : ''}`, {
    method: 'POST',
    body: form,
  })
  return res.json()
}

export const listBankPayments = (status?: PaymentStatus) =>
  apiFetch<BankPayment[]>(`/bank/payments${status ? `?status=${status}` : ''}`)

export const assignBankPayment = (paymentId: number, invoiceId: number) =>
  apiFetch<BankPayment>(`/bank/payments/${paymentId}/assign`, {
    method: 'POST',
    body: JSON.stringify({ invoice_id: invoiceId }),
  })
