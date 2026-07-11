# Design QA

## Scope

- Reference: `.design-qa/source-combined.png`
- Final mini window: `.design-qa/final7/implementation-mini.png`
- Final menu-bar popover: `.design-qa/final7/implementation-popover.png`
- English-language evidence: `.design-qa/final5/en/implementation-mini.png` and `.design-qa/final5/en/implementation-popover.png`
- Test state: healthy module, China Telecom 4G LTE, 90% signal, 38.40 GB / 100 GB used, sufficient balance.

## Viewports

- Mini window: 820 × 300 logical pixels (1640 × 600 Retina capture).
- Popover: 430 logical pixels wide (860-pixel Retina capture); height follows localized content.

## Visual comparison

- The mini window preserves the selected reference hierarchy: app header, large ready state, carrier/network/signal, quota progress, shared-scale up/down speed, and two direct actions.
- The menu-bar popover preserves the selected reference hierarchy: app header and settings, ready state, circular quota, balance badge, live up/down speed, three direct actions, pin action, and compatibility note.
- Status uses green consistently with the physical module state convention; SIM missing, waiting, and error states use amber/red rather than blue.
- Buttons use bundled Font Awesome icons so macOS does not substitute missing-glyph squares.
- The icon is an original generic 4G dongle illustration and contains no DJI logo.
- Simplified Chinese, Traditional Chinese, and English are real UI language packs; country/region is a separate formatting control.

## Functional checks

- All visible compact-surface actions are connected: Settings, Messages, Speed Test, Full App, Pin, and Return to Menu Bar.
- Automated tests: 16 passed.
- Signed ZIP extraction passes `codesign --verify --deep --strict`.
- Source/test scan contains no real user test phone number.

## Issue history

- Initial functional layout did not match the selected mock and was rejected.
- Corrected hierarchy, spacing, dual compact surfaces, circular quota visualization, circular module well, green status icon, balance badge, stable action icons, and actual language switching.
- No open P0, P1, or P2 visual or functional issue remains in the two compact surfaces.

## Result

passed
