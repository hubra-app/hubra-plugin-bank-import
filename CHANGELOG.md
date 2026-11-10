# Changelog

## Unreleased

- German texts are in Standard German now; they were still in Swiss German dialect.

## 1.4.0

- Gives the standard roles access when a club first switches it on (`role_defaults`, docs/roles.md in hubra-app/hubra): Vorstand Ansehen, Kassier/in Alles. Roles without access don't see it; their own data from it stays on their profile. Needs Hubra 0.2.5 or later.
- Dashboard widget **Offene Zahlungen**: how many imported payments still need a look (suggested, unmatched, wrong amount, paid twice); needs `bank.payments.read`.

## 1.3.2

1.3.1 was tagged but couldn't be signed, so it was never released. 1.3.2 is the same plugin, signed. What it brings:

- An add-on of Finances: it needs the Finances plugin (1.x) and shows inside
  its card in the Plugin catalogue. Its rules book into the books Finances
  keeps, so install or update Finances first.

- A matched invoice payment is booked again when no plugin keeps the
  invoices' bookings (Hubra with the books moved into the Finances plugin, but
  Finances not installed). With Finances, its booking is completed as before.

## 1.3.1

1.3.0 was tagged but couldn't be signed, so it was never released. 1.3.1 is the same plugin, signed. What 1.3.0 brings:

- An add-on of Finances: it needs the Finances plugin (1.x) and shows inside
  its card in the Plugin catalogue. Its rules book into the books Finances
  keeps, so install or update Finances first.

- A matched invoice payment is booked again when no plugin keeps the
  invoices' bookings (Hubra with the books moved into the Finances plugin, but
  Finances not installed). With Finances, its booking is completed as before.

## 1.3.0

- An add-on of Finances: it needs the Finances plugin (1.x) and shows inside
  its card in the Plugin catalogue. Its rules book into the books Finances
  keeps, so install or update Finances first.

- A matched invoice payment is booked again when no plugin keeps the
  invoices' bookings (Hubra with the books moved into the Finances plugin, but
  Finances not installed). With Finances, its booking is completed as before.

## 1.2.0

Built for Hubra 0.2 (Mantine 9, plugin host API 2). Needs Hubra 0.2 or newer.

## 1.1.2

- A payment assigned to an invoice by hand books the amount that arrived,
  not the invoice amount.
- A booked debit is stored as a negative amount, like expenses entered by
  hand. Before, it counted as income in the finance overview.
- A second payment of an already paid invoice now waits in the review
  queue, where it can be booked into a category, put on another invoice or
  left out of the books. Before, it only showed in the import summary and
  could not be booked at all.
- A malformed file (an impossible date, a bad CSV column mapping) is
  refused with a message instead of a server error, and camt amounts such
  as NaN or Infinity are not read as numbers.
- A rule whose name, pattern or description is not text is refused with
  a message instead of a server error.

## 1.1.1

- camt files with a DOCTYPE are refused wherever it appears and in any
  encoding (the XML parser refuses it, not a text search).

## 1.1.0

- Reads camt.053 (daily statement) and camt.052 as well as camt.054, plus
  MT940 and CSV exports. The format is detected from the file.
- Debits are imported too, so money going out reaches the books.
- camt.053 and MT940 files: the opening balance plus the bookings is checked
  against the closing balance before you import.
- Collective QR bookings in a camt.053 are kept as one "collective booking"
  line; import the bank's camt.054 for the single payments.
- CSV: columns are found by their header (PostFinance, UBS, Raiffeisen, ZKB
  and the cantonal banks name them alike). When they are not recognised you
  map them once, and the mapping is kept for files with the same columns.
- Payments without a QR reference are suggested for an open invoice when the
  amount fits and the payer is the invoice's member (by name, or by an IBAN
  that paid for that member before). The treasurer confirms.
- Booking rules put recurring lines (rent, phone, sponsors) into a finance
  category automatically. Any other line can be booked into a category by
  hand, or left out of the books.
- New endpoints: `POST /api/v1/bank/import`, `POST /bank/csv/columns`,
  `POST /bank/payments/<id>/confirm|book|ignore`, `/bank/rules`.
  `POST /bank/camt054` still works and now reads any camt file.

Each bank file format has its own references, so import one format per
account (camt.053 if your bank offers it). The same payment from a CSV and
from a camt.053 would be imported twice.

## 1.0.0

First release as a plugin. Before, Bank file import was built into Hubra.
