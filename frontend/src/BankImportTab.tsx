import { useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  FileInput,
  Group,
  MultiSelect,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
} from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { IconFileUpload } from '@tabler/icons-react'
import { useT } from '@hubra/plugin-sdk'
import { useAuth, useToast } from '@hubra/plugin-sdk'
import { formatCHF } from '@hubra/plugin-sdk'
import {
  importBankFile,
  readCsvColumns,
  type CsvColumns,
  type CsvField,
  type CsvMapping,
  type ImportResult,
  type PaymentStatus,
  type SummaryKey,
} from './api'
import { OpenPayments } from './OpenPayments'
import { STATUS_COLOR, signedAmount } from './status'
import { BankRules } from './BankRules'

const SUMMARY: SummaryKey[] = [
  'matched',
  'suggested',
  'booked',
  'unmatched',
  'mismatch',
  'duplicate_payment',
  'batch',
]

export function BankImportTab() {
  const { t } = useT()
  const { notify } = useToast()
  const { hasPermission } = useAuth()
  const queryClient = useQueryClient()
  const canImport = hasPermission('bank.payments.import')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportResult | null>(null)
  const [csv, setCsv] = useState<CsvColumns | null>(null)
  const [mapping, setMapping] = useState<CsvMapping | undefined>()
  const [busy, setBusy] = useState(false)

  const fail = (err: unknown) =>
    notify(
      'error',
      t('common.error'),
      err instanceof Error ? err.message : t('common.unknownError'),
    )

  const reset = (f: File | null) => {
    setFile(f)
    setPreview(null)
    setCsv(null)
    setMapping(undefined)
  }

  const run = async (dryRun: boolean, withMapping = mapping) => {
    if (!file) return
    setBusy(true)
    try {
      const result = await importBankFile(file, dryRun, withMapping)
      setCsv(null)
      if (dryRun) {
        setPreview(result)
      } else {
        reset(null)
        await queryClient.invalidateQueries({ queryKey: ['bank-payments'] })
        await queryClient.invalidateQueries({ queryKey: ['invoices'] })
        notify(
          'success',
          t('bank.imported', '{{matched}} invoices marked paid, {{booked}} bookings added', {
            matched: result.summary.matched,
            booked: result.summary.booked,
          }),
        )
      }
    } catch (err) {
      if ((err as { code?: string }).code === 'CSV_MAPPING_REQUIRED') {
        try {
          const columns = await readCsvColumns(file)
          setCsv(columns)
          setMapping(columns.mapping)
        } catch (inner) {
          fail(inner)
        }
      } else {
        fail(err)
      }
    } finally {
      setBusy(false)
    }
  }

  const statusLabel = (s: PaymentStatus) => t(`bank.status.${s}`, s)

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
              'Download the account statement from your e-banking: camt.053 (best), camt.054, MT940 or CSV. QR-bill payments are matched to invoices, other bookings follow your rules. You see the result before anything is booked.',
            )}
          </Text>
          <Group align="flex-end" gap="sm">
            <FileInput
              style={{ flex: 1, maxWidth: 420 }}
              accept=".xml,.csv,.txt,.sta,.mt940,.940,application/xml,text/xml,text/csv"
              value={file}
              onChange={reset}
              placeholder={t('bank.pickFile', 'Bank file (.xml, .csv, .sta)')}
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
          {csv && (
            <CsvMappingForm
              columns={csv}
              mapping={mapping ?? {}}
              onChange={setMapping}
              onApply={() => run(true, mapping)}
              busy={busy}
            />
          )}
          {preview && (
            <div style={{ marginTop: 16 }}>
              <Group gap="xs" mb="sm">
                <Badge color="dark" variant="outline">
                  {preview.format}
                </Badge>
                {SUMMARY.filter((s) => preview.summary[s] > 0).map((s) => (
                  <Badge key={s} color={STATUS_COLOR[s as PaymentStatus]} variant="light">
                    {statusLabel(s as PaymentStatus)}: {preview.summary[s]}
                  </Badge>
                ))}
                {preview.summary.already_imported > 0 && (
                  <Badge color="gray" variant="light">
                    {t('bank.alreadyImported', 'Already imported')}:{' '}
                    {preview.summary.already_imported}
                  </Badge>
                )}
              </Group>
              {preview.balances.map((b, i) => (
                <Alert
                  key={i}
                  color={b.ok ? 'green' : 'red'}
                  variant="light"
                  mb="sm"
                  title={
                    b.ok
                      ? t('bank.balanceOk', 'Balance checks out')
                      : t('bank.balanceOff', 'Balance does not add up')
                  }
                >
                  {b.accountIban ?? ''} {formatCHF(Number(b.opening))} →{' '}
                  {formatCHF(Number(b.closing))}
                  {!b.ok &&
                    ` · ${t('bank.balanceOffHint', 'Some bookings may be missing from the file.')}`}
                </Alert>
              ))}
              <Table.ScrollContainer minWidth={640}>
                <Table fz="sm" verticalSpacing={6}>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>{t('bank.date', 'Date')}</Table.Th>
                      <Table.Th>{t('bank.counterparty', 'Who')}</Table.Th>
                      <Table.Th>{t('bank.text', 'Text')}</Table.Th>
                      <Table.Th ta="right">{t('bank.amount', 'Amount')}</Table.Th>
                      <Table.Th>{t('bank.statusLabel', 'Result')}</Table.Th>
                      <Table.Th>{t('bank.target', 'Booked as')}</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {preview.items.map((i) => (
                      <Table.Tr key={i.bankReference}>
                        <Table.Td>{new Date(i.bookedOn).toLocaleDateString()}</Table.Td>
                        <Table.Td>{i.counterpartyName ?? '—'}</Table.Td>
                        <Table.Td
                          maw={260}
                          style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}
                        >
                          {i.remittance ?? ''}
                        </Table.Td>
                        <Table.Td
                          ta="right"
                          className="num"
                          c={i.direction === 'debit' ? 'red' : undefined}
                        >
                          {signedAmount(i.direction, i.amount)}
                        </Table.Td>
                        <Table.Td>
                          <Badge color={STATUS_COLOR[i.status]} variant="light" size="sm">
                            {statusLabel(i.status)}
                          </Badge>
                        </Table.Td>
                        <Table.Td>
                          {i.invoiceId
                            ? `#${i.invoiceId}`
                            : i.suggestedInvoiceId
                              ? `#${i.suggestedInvoiceId}?`
                              : (i.ruleName ?? '—')}
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
              <Group justify="flex-end" mt="md">
                <Button
                  onClick={() => run(false)}
                  loading={busy}
                  disabled={preview.items.length === 0}
                >
                  {t('bank.book', 'Import bookings')}
                </Button>
              </Group>
            </div>
          )}
        </Paper>
      )}
      <OpenPayments canEdit={canImport} onError={fail} />
      <BankRules canEdit={canImport} onError={fail} />
    </Stack>
  )
}

const MAPPED_FIELDS: CsvField[] = [
  'date',
  'amount',
  'credit',
  'debit',
  'counterparty',
  'text',
  'reference',
  'iban',
  'currency',
  'value_date',
  'bank_reference',
]

/** Shown when the CSV's columns were not recognised. */
function CsvMappingForm({
  columns,
  mapping,
  onChange,
  onApply,
  busy,
}: {
  columns: CsvColumns
  mapping: CsvMapping
  onChange: (m: CsvMapping) => void
  onApply: () => void
  busy: boolean
}) {
  const { t } = useT()
  const options = columns.columns.filter(Boolean)
  const set = (field: CsvField, value: string[]) =>
    onChange({ ...mapping, [field]: value.length ? value : undefined })
  const ready = Boolean(
    mapping.date?.length &&
    (mapping.amount?.length || mapping.credit?.length || mapping.debit?.length),
  )
  return (
    <Alert
      color="blue"
      variant="light"
      mt="md"
      title={t('bank.mapTitle', 'Which column is which?')}
    >
      <Text fz="sm" mb="sm">
        {t(
          'bank.mapHint',
          'Hubra did not recognise the columns of this file. Pick them once; files from this bank with the same columns are read the same way from now on.',
        )}
      </Text>
      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
        {MAPPED_FIELDS.map((field) =>
          field === 'text' ? (
            <MultiSelect
              key={field}
              size="xs"
              label={t(`bank.field.${field}`, field)}
              data={options}
              value={mapping[field] ?? []}
              onChange={(v) => set(field, v)}
              clearable
            />
          ) : (
            <Select
              key={field}
              size="xs"
              label={t(`bank.field.${field}`, field)}
              data={options}
              value={mapping[field]?.[0] ?? null}
              onChange={(v) => set(field, v ? [v] : [])}
              clearable
            />
          ),
        )}
      </SimpleGrid>
      {columns.sample.length > 0 && (
        <Table.ScrollContainer minWidth={480} mt="sm">
          <Table fz="xs" withTableBorder>
            <Table.Thead>
              <Table.Tr>
                {columns.columns.map((c, i) => (
                  <Table.Th key={i}>{c}</Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {columns.sample.slice(0, 3).map((row, r) => (
                <Table.Tr key={r}>
                  {row.map((cell, c) => (
                    <Table.Td key={c}>{cell}</Table.Td>
                  ))}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      <Group justify="flex-end" mt="sm">
        <Button size="xs" disabled={!ready} loading={busy} onClick={onApply}>
          {t('bank.check', 'Check file')}
        </Button>
      </Group>
    </Alert>
  )
}
