import { useState } from 'react'
import { Badge, Button, FileInput, Group, Paper, Select, Stack, Table, Text } from '@mantine/core'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { IconFileUpload } from '@tabler/icons-react'
import { useT } from '@hubra/plugin-sdk'
import { useAuth, useToast } from '@hubra/plugin-sdk'
import { formatCHF } from '@hubra/plugin-sdk'
import { listInvoices } from '@hubra/plugin-sdk'
import {
  assignBankPayment,
  importCamt054,
  listBankPayments,
  type BankPayment,
  type ImportResult,
  type PaymentStatus,
} from './api'

const STATUS_COLOR: Record<PaymentStatus, string> = {
  matched: 'green',
  assigned: 'green',
  unmatched: 'orange',
  mismatch: 'red',
  duplicate_payment: 'grape',
}

export function BankImportTab() {
  const { t } = useT()
  const { notify } = useToast()
  const { hasPermission } = useAuth()
  const queryClient = useQueryClient()
  const canImport = hasPermission('bank.payments.import')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportResult | null>(null)
  const [busy, setBusy] = useState(false)

  const statusLabel = (s: PaymentStatus) => t(`bank.status.${s}`, s)

  const fail = (err: unknown) =>
    notify(
      'error',
      t('common.error'),
      err instanceof Error ? err.message : t('common.unknownError'),
    )

  const run = async (dryRun: boolean) => {
    if (!file) return
    setBusy(true)
    try {
      const result = await importCamt054(file, dryRun)
      if (dryRun) {
        setPreview(result)
      } else {
        setPreview(null)
        setFile(null)
        await queryClient.invalidateQueries({ queryKey: ['bank-payments'] })
        await queryClient.invalidateQueries({ queryKey: ['invoices'] })
        notify(
          'success',
          t('bank.booked', '{{count}} invoices marked paid', {
            count: result.summary.matched,
          }),
        )
      }
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Stack gap="md">
      {canImport && (
        <Paper withBorder shadow="sm" radius="lg" p="lg">
          <Text fw={600} mb={4}>
            {t('bank.importTitle', 'Import bank file')}
          </Text>
          <Text fz="sm" c="dimmed" mb="md">
            {t(
              'bank.importHint',
              'Download the camt.054 file (credit notification) from your e-banking. QR-bill payments are matched to invoices by their reference. You see the result before anything is booked.',
            )}
          </Text>
          <Group align="flex-end" gap="sm">
            <FileInput
              style={{ flex: 1, maxWidth: 420 }}
              accept=".xml,application/xml,text/xml"
              value={file}
              onChange={(f) => {
                setFile(f)
                setPreview(null)
              }}
              placeholder={t('bank.pickFile', 'camt.054 file (.xml)')}
              leftSection={<IconFileUpload size={16} />}
              clearable
            />
            <Button
              variant="default"
              disabled={!file}
              loading={busy && !preview}
              onClick={() => run(true)}
            >
              {t('bank.check', 'Check file')}
            </Button>
          </Group>
          {preview && (
            <div style={{ marginTop: 16 }}>
              <Group gap="xs" mb="sm">
                {(['matched', 'unmatched', 'mismatch', 'duplicate_payment'] as const).map((s) => (
                  <Badge key={s} color={STATUS_COLOR[s]} variant="light">
                    {statusLabel(s)}: {preview.summary[s]}
                  </Badge>
                ))}
                {preview.summary.already_imported > 0 && (
                  <Badge color="gray" variant="light">
                    {t('bank.alreadyImported', 'Already imported')}:{' '}
                    {preview.summary.already_imported}
                  </Badge>
                )}
              </Group>
              <PaymentTable
                rows={preview.items.map((i) => ({
                  key: i.bankReference,
                  bookedOn: i.bookedOn,
                  debtorName: i.debtorName,
                  amount: i.amount,
                  status: i.status,
                  invoiceId: i.invoiceId,
                }))}
                statusLabel={statusLabel}
              />
              <Group justify="flex-end" mt="md">
                <Button
                  onClick={() => run(false)}
                  loading={busy}
                  disabled={preview.items.length === 0}
                >
                  {t('bank.book', 'Book payments')}
                </Button>
              </Group>
            </div>
          )}
        </Paper>
      )}
      <OpenPayments canAssign={canImport} onError={fail} />
    </Stack>
  )
}

function PaymentTable({
  rows,
  statusLabel,
  action,
}: {
  rows: {
    key: string | number
    bookedOn: string
    debtorName: string | null
    amount: string
    status: PaymentStatus
    invoiceId: number | null
    payment?: BankPayment
  }[]
  statusLabel: (s: PaymentStatus) => string
  action?: (payment: BankPayment) => React.ReactNode
}) {
  const { t } = useT()
  return (
    <Table.ScrollContainer minWidth={560}>
      <Table fz="sm" verticalSpacing={6}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('bank.date', 'Date')}</Table.Th>
            <Table.Th>{t('bank.from', 'From')}</Table.Th>
            <Table.Th ta="right">{t('bank.amount', 'Amount')}</Table.Th>
            <Table.Th>{t('bank.statusLabel', 'Result')}</Table.Th>
            <Table.Th>{t('bank.invoice', 'Invoice')}</Table.Th>
            {action && <Table.Th />}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((r) => (
            <Table.Tr key={r.key}>
              <Table.Td>{new Date(r.bookedOn).toLocaleDateString()}</Table.Td>
              <Table.Td>{r.debtorName ?? '—'}</Table.Td>
              <Table.Td ta="right" className="num">
                {formatCHF(Number(r.amount))}
              </Table.Td>
              <Table.Td>
                <Badge color={STATUS_COLOR[r.status]} variant="light" size="sm">
                  {statusLabel(r.status)}
                </Badge>
              </Table.Td>
              <Table.Td>{r.invoiceId ? `#${r.invoiceId}` : '—'}</Table.Td>
              {action && r.payment && <Table.Td>{action(r.payment)}</Table.Td>}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}

/** Payments that could not be booked automatically, to assign by hand. */
function OpenPayments({
  canAssign,
  onError,
}: {
  canAssign: boolean
  onError: (err: unknown) => void
}) {
  const { t } = useT()
  const queryClient = useQueryClient()
  const { data: unmatched = [] } = useQuery({
    queryKey: ['bank-payments', 'unmatched'],
    queryFn: () => listBankPayments('unmatched'),
  })
  const { data: mismatch = [] } = useQuery({
    queryKey: ['bank-payments', 'mismatch'],
    queryFn: () => listBankPayments('mismatch'),
  })
  const payments = [...mismatch, ...unmatched]
  const { data: invoices = [] } = useQuery({
    queryKey: ['invoices'],
    queryFn: listInvoices,
    enabled: canAssign && payments.length > 0,
  })
  const [choice, setChoice] = useState<Record<number, string | null>>({})
  const openInvoices = invoices
    .filter((i) => i.status !== 'Paid')
    .map((i) => ({
      value: i.id,
      label: `#${i.id} · ${i.recipientName} · ${formatCHF(i.amount)}`,
    }))

  if (payments.length === 0) return null

  const assign = async (p: BankPayment) => {
    const invoiceId = choice[p.id]
    if (!invoiceId) return
    try {
      await assignBankPayment(p.id, Number(invoiceId))
      await queryClient.invalidateQueries({ queryKey: ['bank-payments'] })
      await queryClient.invalidateQueries({ queryKey: ['invoices'] })
    } catch (err) {
      onError(err)
    }
  }

  return (
    <Paper withBorder shadow="sm" radius="lg" p="lg">
      <Text fw={600} mb={4}>
        {t('bank.toCheck', 'Payments to check')}
      </Text>
      <Text fz="sm" c="dimmed" mb="md">
        {t(
          'bank.toCheckHint',
          'These payments had no matching invoice or a different amount. Assign them to an invoice to mark it paid.',
        )}
      </Text>
      <PaymentTable
        rows={payments.map((p) => ({
          key: p.id,
          bookedOn: p.bookedOn,
          debtorName: p.debtorName ?? p.remittance,
          amount: p.amount,
          status: p.status,
          invoiceId: p.invoiceId,
          payment: p,
        }))}
        statusLabel={(s) => t(`bank.status.${s}`, s)}
        action={
          canAssign
            ? (p) => (
                <Group gap={6} wrap="nowrap">
                  <Select
                    size="xs"
                    w={220}
                    searchable
                    data={openInvoices}
                    value={choice[p.id] ?? (p.invoiceId ? String(p.invoiceId) : null)}
                    onChange={(v) => setChoice((c) => ({ ...c, [p.id]: v }))}
                    placeholder={t('bank.pickInvoice', 'Invoice')}
                  />
                  <Button size="xs" onClick={() => assign(p)}>
                    {t('bank.assign', 'Mark paid')}
                  </Button>
                </Group>
              )
            : undefined
        }
      />
    </Paper>
  )
}
