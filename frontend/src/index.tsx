import { registerPlugin } from '@hubra/plugin-sdk'
import { BankImportTab } from './BankImportTab'
import translations from './translations.json'

registerPlugin({
  id: 'bank-import',
  tabs: [
    {
      screen: 'finance',
      id: 'bank',
      label: 'shell.nav.bankImport',
      module: 'finance.bank',
      perm: 'bank.payments.read',
      component: BankImportTab,
      order: 110,
    },
  ],
  translations,
})
