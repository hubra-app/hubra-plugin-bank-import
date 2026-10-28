import { useState } from 'react'
import {
  ActionIcon,
  Button,
  Group,
  Paper,
  Select,
  Switch,
  Table,
  Text,
  TextInput,
} from '@mantine/core'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { IconTrash } from '@tabler/icons-react'
import { useT } from '@hubra/plugin-sdk'
import { listTxCategories } from '@hubra/plugin-sdk'
import { createBankRule, deleteBankRule, listBankRules, updateBankRule, type BankRule } from './api'

const EMPTY = {
  name: '',
  pattern: '',
  direction: 'debit' as BankRule['direction'],
  matchField: 'counterparty' as BankRule['matchField'],
  categoryId: null as string | null,
}

/** Rules book recurring lines (rent, phone, a sponsor) into a category. */
export function BankRules({
  canEdit,
  onError,
}: {
  canEdit: boolean
  onError: (err: unknown) => void
}) {
  const { t } = useT()
  const queryClient = useQueryClient()
  const { data: rules = [] } = useQuery({ queryKey: ['bank-rules'], queryFn: listBankRules })
  const { data: categories = [] } = useQuery({
    queryKey: ['tx-categories'],
    queryFn: listTxCategories,
    enabled: canEdit,
  })
  const [draft, setDraft] = useState(EMPTY)

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['bank-rules'] })
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn()
      await refresh()
    } catch (err) {
      onError(err)
    }
  }

  const directions = [
    { value: 'debit', label: t('bank.direction.debit', 'Money out') },
    { value: 'credit', label: t('bank.direction.credit', 'Money in') },
    { value: 'any', label: t('bank.direction.any', 'Both') },
  ]
  const fields = [
    { value: 'counterparty', label: t('bank.matchField.counterparty', 'Who') },
    { value: 'text', label: t('bank.matchField.text', 'Booking text') },
    { value: 'iban', label: t('bank.matchField.iban', 'IBAN') },
    { value: 'any', label: t('bank.matchField.any', 'Anywhere') },
  ]
  const label = (list: { value: string; label: string }[], value: string) =>
    list.find((o) => o.value === value)?.label ?? value

  if (!canEdit && rules.length === 0) return null

  const add = () =>
    act(async () => {
      await createBankRule({
        name: draft.name || draft.pattern,
        pattern: draft.pattern,
        direction: draft.direction,
        matchField: draft.matchField,
        categoryId: Number(draft.categoryId),
        description: null,
        active: true,
      })
      setDraft(EMPTY)
    })

  return (
    <Paper withBorder shadow="sm" radius="lg" p="lg">
      <Text fw={600} mb={4}>
        {t('bank.rulesTitle', 'Booking rules')}
      </Text>
      <Text fz="sm" c="dimmed" mb="md">
        {t(
          'bank.rulesHint',
          'A rule books every line whose text contains the pattern into a category, for example "Swisscom" as Telephone. Lines that pay an invoice are matched first.',
        )}
      </Text>
      {rules.length > 0 && (
        <Table fz="sm" verticalSpacing={6} mb="md">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('bank.ruleName', 'Name')}</Table.Th>
              <Table.Th>{t('bank.ruleWhen', 'When')}</Table.Th>
              <Table.Th>{t('bank.pickCategory', 'Category')}</Table.Th>
              <Table.Th>{t('bank.ruleActive', 'Active')}</Table.Th>
              {canEdit && <Table.Th />}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rules.map((r) => (
              <Table.Tr key={r.id}>
                <Table.Td>{r.name}</Table.Td>
                <Table.Td>
                  {label(directions, r.direction)} · {label(fields, r.matchField)} ∋ “{r.pattern}”
                </Table.Td>
                <Table.Td>{r.categoryName ?? '—'}</Table.Td>
                <Table.Td>
                  <Switch
                    size="xs"
                    checked={r.active}
                    disabled={!canEdit}
                    onChange={(e) =>
                      act(() => updateBankRule(r.id, { active: e.currentTarget.checked }))
                    }
                  />
                </Table.Td>
                {canEdit && (
                  <Table.Td>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      aria-label={t('common.delete', 'Delete')}
                      onClick={() => act(() => deleteBankRule(r.id))}
                    >
                      <IconTrash size={14} />
                    </ActionIcon>
                  </Table.Td>
                )}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {canEdit && (
        <Group align="flex-end" gap="xs">
          <TextInput
            size="xs"
            w={140}
            label={t('bank.ruleName', 'Name')}
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.currentTarget.value })}
          />
          <Select
            size="xs"
            w={120}
            label={t('bank.ruleDirection', 'Direction')}
            data={directions}
            value={draft.direction}
            allowDeselect={false}
            onChange={(v) =>
              setDraft({ ...draft, direction: (v ?? 'any') as BankRule['direction'] })
            }
          />
          <Select
            size="xs"
            w={130}
            label={t('bank.ruleField', 'Look in')}
            data={fields}
            value={draft.matchField}
            allowDeselect={false}
            onChange={(v) =>
              setDraft({ ...draft, matchField: (v ?? 'any') as BankRule['matchField'] })
            }
          />
          <TextInput
            size="xs"
            w={150}
            label={t('bank.rulePattern', 'Contains')}
            value={draft.pattern}
            onChange={(e) => setDraft({ ...draft, pattern: e.currentTarget.value })}
          />
          <Select
            size="xs"
            w={160}
            searchable
            label={t('bank.pickCategory', 'Category')}
            data={categories.map((c) => ({ value: String(c.id), label: c.name }))}
            value={draft.categoryId}
            onChange={(v) => setDraft({ ...draft, categoryId: v })}
          />
          <Button size="xs" disabled={!draft.pattern.trim() || !draft.categoryId} onClick={add}>
            {t('bank.addRule', 'Add rule')}
          </Button>
        </Group>
      )}
    </Paper>
  )
}
