# Operator And Chain Origin Registry

Current chain/operator origin mappings used or proposed for crypto reporting in this repository.

## Terminology

- Authority: whether the mapping is direct from official text, inferred from official text, or a repository override.
- Europe override: a local user-directed choice for filing output when the upstream platform spans multiple jurisdictions.
- valid_from: ISO date (YYYY-MM-DD) when this mapping became effective, or null for historical operators where the exact start date is unknown. When null, no lower-bound check is performed but valid_until (if present) still enforces an upper bound.
- service_scope: For platforms that split services by legal entity (e.g., fiat vs crypto), indicates which scope this mapping applies to.

## Current mappings

- `Berachain`
  - country: `British Virgin Islands`
  - authority: `official`
  - valid_from: `2025-02-05`
  - basis: Berachain terms identify `BERA Chain Foundation` and British Virgin Islands governing law.

- `Starknet`
  - country: `Cayman Islands`
  - authority: `inferred from official`
  - valid_from: null
  - basis: Starknet Foundation materials expose official foundation/legal handling with Cayman data-protection references, but the domicile should stay provenance-tagged.

- `zkSync ERA`
  - country: `Cayman Islands`
  - authority: `official`
  - valid_from: null
  - basis: zkSync terms identify `Matter Labs`, a Cayman Islands company.

- `Solana`
  - country: `Switzerland`
  - authority: `official`
  - valid_from: null
  - basis: Solana Foundation is described on the official site as being based in Zug, Switzerland.

- `TON`
  - country: `Switzerland`
  - authority: `official`
  - valid_from: null
  - basis: TON Foundation states it was founded in Switzerland as a non-profit organization in 2023.

- `Ethereum`
  - country: `Switzerland`
  - authority: `official`
  - valid_from: `2024-05-08`
  - basis: Ethereum Foundation is described in official materials as a Swiss `Stiftung`.

- `Aptos`
  - country: `Cayman Islands`
  - authority: `official`
  - valid_from: `2025-08-29`
  - basis: Aptos Foundation terms list a George Town, Grand Cayman registered address.

- `Sui`
  - country: `Cayman Islands`
  - authority: `official`
  - valid_from: null
  - basis: repository Sui Foundation source set anchors Sui to the Cayman Islands.

- `Arbitrum`
  - country: `Cayman Islands`
  - authority: `official`
  - valid_from: `2023-07-20`
  - basis: official Arbitrum Foundation memorandum and articles list a Grand Cayman registered office.

- `Mantle`
  - country: `British Virgin Islands`
  - authority: `public-record supported`
  - valid_from: `2024-03-15`
  - basis: Mantle official terms provide the legal interface and Singapore governing law; a public Hong Kong IPD record names `Mantle Foundation S.A.` in the British Virgin Islands.

- `Polygon`
  - country: `Cayman Islands`
  - authority: `official`
  - valid_from: `2024-01-23`
  - basis: Polygon legal terms identify `Polygon Labs UI (Cayman) Ltd.`.

- `BASE`
  - country: `United States`
  - authority: `official`
  - valid_from: `2025-12-04`
  - basis: Base terms identify `Coinbase Technologies, Inc.` as the contracting party for Base services.

- `Filecoin`
  - country: `United States`
  - authority: `official`
  - valid_from: `2024-04-01`
  - basis: Filecoin Foundation official careers privacy page lists a registered address in Middletown, Delaware.

- `Tonkeeper`
  - country: `United Kingdom`
  - authority: `official`
  - valid_from: null
  - basis: Tonkeeper terms identify `Ton Apps UK Ltd.` in England and Wales.
  - note: Historical operator with unknown exact start date; terms verified 2025-02-12.
  - note: Koinly exports may contain typo "Tonkeper wallet" - code handles both spellings.

- `Kraken`
  - country: `Ireland`
  - authority: `official`
  - valid_from: null
  - basis: official licensing page lists EEA-facing Irish entities.

- `Gate.io`
  - country: `Malta`
  - authority: `official`
  - valid_from: null
  - basis: Gate Europe about page states Malta incorporation / regulation.

- `Wirex (fiat)`
  - country: `GB`
  - authority: `official`
  - service_scope: `fiat`
  - valid_from: `2026-03-08`
  - basis: Wirex Limited (UK) is the legal entity for fiat services per Wirex account terms verified 2026-03-08.

- `Wirex (crypto)`
  - country: `HR`
  - authority: `official`
  - service_scope: `crypto`
  - valid_from: `2026-03-08`
  - basis: Wirex Digital (Croatia) is the crypto operator per Wirex account terms verified 2026-03-08.

- `Binance`
  - country: `Spain`
  - authority: `repository override`
  - valid_from: `2026-01-01`
  - basis: Europe-facing filing override to avoid `Multiple jurisdictions` in workbook output.

- `Binance Smart Chain`
  - country: `Spain`
  - authority: `repository override`
  - valid_from: `2026-01-01`
  - basis: Europe-facing filing override for workbook output. Keep the upstream BNB Chain ADGM / UAE source visible in the archive.
