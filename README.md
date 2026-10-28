# Bank file import

A plugin for [Hubra](https://hubra.club). Import bank statements (camt.053, camt.054, MT940 or CSV). Payments are matched to invoices and marked paid, other bookings go into the books by your rules, with a dry run first.

**Version** 1.1.0 · **Works with** Hubra >=0.1,<1 · **Plugin id** `bank-import`

## Install

Platform admins install it from the plugin catalogue in the manager portal
(official Marketplace, <https://plugins.hubra.club/index.json>, signed with
the Hubra project key). Clubs then switch it on under Einstellungen → Module
& Plugins.

## Develop

Clone this repository into `plugins/bank-import` of a Hubra checkout. Its tests
then run with Hubra's (`cd app/backend && pytest ../../plugins/bank-import`), and
`npm run build:plugin` in `app/frontend` builds its frontend. The workflow
does the same against Hubra's `main` on every push and pull request.

## Releasing

Bump `version` in `plugin.yaml`, add a `## <version>` section to
`CHANGELOG.md`, commit, then publish a GitHub release tagged `v<version>`
(web UI, or `gh release create v<version> --target main --notes ""`). The
workflow tests the plugin and builds its frontend; a separate job in the
`plugin-signing` environment, the only one with the `HUBRA_SIGNING_KEY`
secret, signs it; then `bank-import-<version>.zip` is attached to the release. Files listed in `.releaseignore` stay out of the zip.

Source: <https://github.com/hubra-app/hubra-plugin-bank-import>
