# Bank file import

[![Test and release](https://github.com/hubra-app/hubra-plugin-bank-import/actions/workflows/release.yml/badge.svg?branch=main)](https://github.com/hubra-app/hubra-plugin-bank-import/actions/workflows/release.yml?query=branch%3Amain) [![License: all rights reserved](https://img.shields.io/badge/license-all%20rights%20reserved-lightgrey)](LICENSE)

A plugin for [Hubra](https://hubra.club). Import bank statements (camt.053, camt.054, MT940 or CSV). Payments are matched to invoices and marked paid, other bookings go into the books by your rules, with a dry run first.

**Version** 1.2.0 · **Works with** Hubra >=0.2,<1 · **Plugin id** `bank-import`

## Install

Platform admins install it from the Plugin catalogue in manage
(official Marketplace, <https://plugins.hubra.club/index.json>, signed with
the Hubra project key). Clubs then switch it on under Einstellungen → Module.

## Develop

Clone this repository into `plugins/bank-import` of a Hubra checkout. Its tests
then run with Hubra's (`cd app/backend && pytest ../../plugins/bank-import`), and
`npm run build:plugin` in `app/frontend` builds its frontend. The workflow
does the same against Hubra's `main` on every push and pull request.

## Releasing

Bump `version` in `plugin.yaml`, add a `## <version>` section to
`CHANGELOG.md` and merge. Then tag the merged commit on main and push the tag:

```sh
git switch main && git pull
git tag v<version> && git push origin v<version>
```

The workflow tests the plugin and builds its frontend, the `plugin-signing`
job signs it after your approval, and only then is the GitHub release
`v<version>` published, with `bank-import-<version>.zip` and its `.sha256` attached. Files
listed in `.releaseignore` stay out of the zip. Releases are immutable, so a
published version never changes: fix a bad one with a new version.

Source: <https://github.com/hubra-app/hubra-plugin-bank-import>
