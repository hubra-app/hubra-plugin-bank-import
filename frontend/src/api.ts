import { apiFetch, apiFetchRaw } from '@hubra/plugin-sdk'

export type PaymentStatus =
  | 'matched'
  | 'assigned'
  | 'suggested'
  | 'booked'
  | 'unmatched'
  | 'mismatch'
  | 'duplicate_payment'
  | 'ignored'
  | 'batch'

export type Direction = 'credit' | 'debit'

export type SummaryKey =
  | 'matched'
  | 'suggested'
  | 'booked'
  | 'unmatched'
  | 'mismatch'
  | 'duplicate_payment'
  | 'batch'
  | 'already_imported'

export interface ImportItem {
  bankReference: string
  direction: Direction
  reference: string | null
  amount: string
  currency: string
  bookedOn: string
  counterpartyName: string | null
  remittance: string | null
  status: PaymentStatus
  invoiceId: number | null
  suggestedInvoiceId: number | null
  invoiceAmount: string | null
  ruleId: number | null
  ruleName: string | null
}

export interface BalanceCheck {
  accountIban: string | null
  opening: string
  closing: string
  movement: string
  ok: boolean
}

export interface ImportResult {
  dryRun: boolean
  format: string
  summary: Record<SummaryKey, number>
  balances: BalanceCheck[]
  items: ImportItem[]
}

export interface BankPayment {
  id: number
  bankReference: string
  direction: Direction
  reference: string | null
  amount: string
  currency: string
  bookedOn: string
  counterpartyName: string | null
  counterpartyIban: string | null
  remittance: string | null
  status: PaymentStatus
  invoiceId: number | null
  suggestedInvoiceId: number | null
  transactionId: number | null
  fileName: string | null
}

export type CsvField =
  | 'date'
  | 'value_date'
  | 'amount'
  | 'credit'
  | 'debit'
  | 'currency'
  | 'text'
  | 'counterparty'
  | 'iban'
  | 'reference'
  | 'bank_reference'

export type CsvMapping = Partial<Record<CsvField, string[]>>

export interface CsvColumns {
  columns: string[]
  sample: string[][]
  fields: CsvField[]
  mapping: CsvMapping
}

export interface BankRule {
  id: number
  name: string
  direction: Direction | 'any'
  matchField: 'counterparty' | 'text' | 'iban' | 'any'
  pattern: string
  categoryId: number
  categoryName: string | null
  description: string | null
  active: boolean
}

export async function importBankFile(
  file: File,
  dryRun: boolean,
  mapping?: CsvMapping,
): Promise<ImportResult> {
  const form = new FormData()
  form.append('file', file)
  if (mapping) form.append('mapping', JSON.stringify(mapping))
  const res = await apiFetchRaw(`/bank/import${dryRun ? '?dry_run=1' : ''}`, {
    method: 'POST',
    body: form,
  })
  return res.json()
}

export async function readCsvColumns(file: File): Promise<CsvColumns> {
  const form = new FormData()
  form.append('file', file)
  const res = await apiFetchRaw('/bank/csv/columns', { method: 'POST', body: form })
  return res.json()
}

export const listOpenPayments = () => apiFetch<BankPayment[]>('/bank/payments?status=open')

const post = (paymentId: number, action: string, body?: object) =>
  apiFetch<BankPayment>(`/bank/payments/${paymentId}/${action}`, {
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  })

export const assignBankPayment = (paymentId: number, invoiceId: number) =>
  post(paymentId, 'assign', { invoice_id: invoiceId })

export const confirmBankPayment = (paymentId: number) => post(paymentId, 'confirm')

export const bookBankPayment = (paymentId: number, categoryId: number) =>
  post(paymentId, 'book', { category_id: categoryId })

export const ignoreBankPayment = (paymentId: number) => post(paymentId, 'ignore')

export const listBankRules = () => apiFetch<BankRule[]>('/bank/rules')

export const createBankRule = (rule: Omit<BankRule, 'id' | 'categoryName'>) =>
  apiFetch<BankRule>('/bank/rules', { method: 'POST', body: JSON.stringify(rule) })

export const updateBankRule = (id: number, patch: Partial<BankRule>) =>
  apiFetch<BankRule>(`/bank/rules/${id}`, { method: 'PATCH', body: JSON.stringify(patch) })

export const deleteBankRule = (id: number) =>
  apiFetch<void>(`/bank/rules/${id}`, { method: 'DELETE' })
