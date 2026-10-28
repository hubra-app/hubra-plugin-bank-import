# Changelog

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
