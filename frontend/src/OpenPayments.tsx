import { useState } from 'react'
import { Badge, Button, Group, Menu, Paper, Select, Table, Text } from '@mantine/core'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { IconDots } from '@tabler/icons-react'
import { useT } from '@hubra/plugin-sdk'
import { formatCHF } from '@hubra/plugin-sdk'
import { listInvoices, listTxCategories } from '@hubra/plugin-sdk'
import {
  assignBankPayment,
  bookBankPayment,
  confirmBankPayment,
  ignoreBankPayment,
  listOpenPayments,
  type BankPayment,
} from './api'
import { STATUS_COLOR, signedAmount } from './status'

/** Lines that were not booked automatically: confirm, assign, book or ignore. */
export function OpenPayments({
  canEdit,
  onError,
}: {
  canEdit: boolean
  onError: (err: unknown) => void
}) {
  const { t } = useT()
  const queryClient = useQueryClient()
  const { data: payments = [] } = useQuery({
    queryKey: ['bank-payments', 'open'],
    queryFn: listOpenPayments,
  })
  const { data: invoices = [] } = useQuery({
    queryKey: ['invoices'],
    queryFn: listInvoices,
    enabled: canEdit && payments.length > 0,
  })
  const { data: categories = [] } = useQuery({
    queryKey: ['tx-categories'],
    queryFn: listTxCategories,
    enabled: canEdit && payments.length > 0,
  })
  const [invoiceChoice, setInvoiceChoice] = useState<Record<number, string | null>>({})
  const [categoryChoice, setCategoryChoice] = useState<Record<number, string | null>>({})
  const openInvoices = invoices
    .filter((i) => i.status !== 'Paid')
    .map((i) => ({
      value: String(i.id),
      label: `#${i.id} · ${i.recipientName} · ${formatCHF(i.amount)}`,
    }))
  const invoiceLabel = (id: number) =>
    openInvoices.find((o) => o.value === String(id))?.label ?? `#${id}`
  const categoryOptions = categories.map((c) => ({ value: String(c.id), label: c.name }))

  if (payments.length === 0) return null

  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn()
      await queryClient.invalidateQueries({ queryKey: ['bank-payments'] })
      await queryClient.invalidateQueries({ queryKey: ['invoices'] })
    } catch (err) {
      onError(err)
    }
  }

  const ignoreButton = (p: BankPayment) => (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <Button size="xs" variant="subtle" px={6} aria-label={t('common.more', 'More')}>
          <IconDots size={14} />
        </Button>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Item onClick={() => act(() => ignoreBankPayment(p.id))}>
          {t('bank.ignore', 'Leave out of the books')}
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  )

  const actions = (p: BankPayment) => {
    if (p.status === 'suggested' && p.suggestedInvoiceId) {
      return (
        <Group gap={6} wrap="nowrap">
          <Text fz="xs">{invoiceLabel(p.suggestedInvoiceId)}</Text>
          <Button size="xs" onClick={() => act(() => confirmBankPayment(p.id))}>
            {t('bank.confirm', 'Confirm')}
          </Button>
          {ignoreButton(p)}
        </Group>
      )
    }
    const choice = categoryChoice[p.id]
    // A second payment points at the invoice it already paid: no default.
    const invoiceId = p.status === 'duplicate_payment' ? null : p.invoiceId
    return (
      <Group gap={6} wrap="nowrap">
        {p.direction === 'credit' && (
          <>
            <Select
              size="xs"
              w={200}
              searchable
              clearable
              data={openInvoices}
              value={invoiceChoice[p.id] ?? (invoiceId ? String(invoiceId) : null)}
              onChange={(v) => setInvoiceChoice((c) => ({ ...c, [p.id]: v }))}
              placeholder={t('bank.pickInvoice', 'Invoice')}
            />
            <Button
              size="xs"
              disabled={!invoiceChoice[p.id] && !invoiceId}
              onClick={() =>
                act(() => assignBankPayment(p.id, Number(invoiceChoice[p.id] ?? invoiceId)))
              }
            >
              {t('bank.assign', 'Mark paid')}
            </Button>
          </>
        )}
        <Select
          size="xs"
          w={160}
          searchable
          clearable
          data={categoryOptions}
          value={choice ?? null}
          onChange={(v) => setCategoryChoice((c) => ({ ...c, [p.id]: v }))}
          placeholder={t('bank.pickCategory', 'Category')}
        />
        <Button
          size="xs"
          variant="default"
          disabled={!choice}
          onClick={() => act(() => bookBankPayment(p.id, Number(choice)))}
        >
          {t('bank.bookOne', 'Book')}
        </Button>
        {ignoreButton(p)}
      </Group>
    )
  }

  return (
    <Paper withBorder shadow="sm" radius="lg" p="lg">
      <Text fw={600} mb={4}>
        {t('bank.toCheck', 'Bookings to check')}
      </Text>
      <Text fz="sm" c="dimmed" mb="md">
        {t(
          'bank.toCheckHint',
          'Confirm a suggested invoice, assign a payment to an invoice, or book the line into a category. A rule books similar lines automatically next time.',
        )}
      </Text>
      <Table.ScrollContainer minWidth={760}>
        <Table fz="sm" verticalSpacing={6}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('bank.date', 'Date')}</Table.Th>
              <Table.Th>{t('bank.counterparty', 'Who')}</Table.Th>
              <Table.Th>{t('bank.text', 'Text')}</Table.Th>
              <Table.Th ta="right">{t('bank.amount', 'Amount')}</Table.Th>
              <Table.Th>{t('bank.statusLabel', 'Result')}</Table.Th>
              {canEdit && <Table.Th />}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {payments.map((p) => (
              <Table.Tr key={p.id}>
                <Table.Td>{new Date(p.bookedOn).toLocaleDateString()}</Table.Td>
                <Table.Td>{p.counterpartyName ?? '—'}</Table.Td>
                <Table.Td maw={240} style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {p.remittance ?? ''}
                </Table.Td>
                <Table.Td
                  ta="right"
                  className="num"
                  c={p.direction === 'debit' ? 'red' : undefined}
                >
                  {signedAmount(p.direction, p.amount)}
                </Table.Td>
                <Table.Td>
                  <Badge color={STATUS_COLOR[p.status]} variant="light" size="sm">
                    {t(`bank.status.${p.status}`, p.status)}
                  </Badge>
                </Table.Td>
                {canEdit && <Table.Td>{actions(p)}</Table.Td>}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Paper>
  )
}
