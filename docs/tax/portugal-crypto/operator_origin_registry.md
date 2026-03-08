# Operator Origin Registry (Implemented Defaults)

The implementation maps wallet/platform names to operator origin metadata and always keeps a review flag because account-level legal entities may differ by region.

## Terminology

- Service scope: whether mapping applies to crypto activity or fiat/card activity.
- Review required: marker that manual entity verification is still required for filing confidence.

## Current defaults

- `Wirex` + crypto transaction type
  - service scope: `crypto`
  - operator entity: `Wirex Digital (crypto operator, verify account terms)`
  - country: `Croatia`
  - review required: `true`

- `Wirex` + fiat transaction type
  - service scope: `fiat`
  - operator entity: `Wirex Limited`
  - country: `United Kingdom`
  - review required: `true`

- `Bybit`
  - operator entity: `Bybit group entity (account-region specific)`
  - country: `United Arab Emirates`
  - review required: `true`

- `Binance`
  - operator entity: `Binance group entity (account-region specific)`
  - country: `Multiple jurisdictions`
  - review required: `true`

- `Kraken`
  - operator entity: `Payward group entity (account-region specific)`
  - country: `Multiple jurisdictions`
  - review required: `true`
