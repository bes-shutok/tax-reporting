# Tax Documentation Layout

Canonical layout for tax-related documentation in this repository.

## Terminology

- Tax-law archive: country-specific legal and filing material.
- Origin archive: chain/operator domicile and source-country material used to resolve crypto origin fields.
- Implementation guideline: repository policy or reporting behavior documented under `docs/domain/`.

## Directory Roles

- `portugal-crypto-tax/`
  - Portugal-specific crypto tax law, AT forms, circulars, binding rulings, and filing-oriented notes.
  - Use this folder for questions such as "what does Portuguese tax law require?" and "which official IRS annex fields matter?".

- `crypto-origin/`
  - Chain/operator origin archive used to resolve `País da Fonte`, operator country, and normalized chain metadata.
  - Use this folder for questions such as "which country should this chain/operator map to?" and "what source supports that mapping?".

- `../domain/crypto_reporting_guidelines.md`
  - Canonical implementation guidance that turns the archived tax/origin sources into repository behavior.

- `../domain/koinly_guidelines.md`
  - Practical Koinly repair workflows for known import defects such as wrapped-asset pool actions that lose cost-basis continuity.

## Non-duplication Rule

- Do not duplicate Portugal tax-law findings inside `crypto-origin/`.
- Do not duplicate chain/operator domicile mapping files inside `portugal-crypto-tax/`.
- If a filing rule depends on an origin mapping, keep the law in `portugal-crypto-tax/`, keep the mapping evidence in `crypto-origin/`, and reference both from the domain guideline.
