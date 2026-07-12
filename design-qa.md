# Design QA

## Scope

- Reference: `.design-qa/source-combined.png`
- Full overview reference: `.design-qa/full-overview-reference.png`
- Final full overview: `.design-qa/full-overview-final.png`
- Full-view side-by-side evidence: `.design-qa/full-overview-comparison.jpg`
- Final mini window: `.design-qa/final7/implementation-mini.png`
- Final menu-bar popover: `.design-qa/final7/implementation-popover.png`
- English-language evidence: `.design-qa/final5/en/implementation-mini.png` and `.design-qa/final5/en/implementation-popover.png`
- Test state: healthy module, China Telecom 4G LTE, 90% signal, 38.40 GB / 100 GB used, sufficient balance.

## Viewports

- Mini window: 820 × 300 logical pixels (1640 × 600 Retina capture).
- Popover: 430 logical pixels wide (860-pixel Retina capture); height follows localized content.
- Full overview: 1180 × 840 logical pixels (2360 × 1680 Retina capture), matching the reference aspect ratio.

## Visual comparison

- The mini window preserves the selected reference hierarchy: app header, large ready state, carrier/network/signal, quota progress, shared-scale up/down speed, and two direct actions.
- The menu-bar popover preserves the selected reference hierarchy: app header and settings, ready state, circular quota, balance badge, live up/down speed, three direct actions, pin action, and compatibility note.
- Status uses green consistently with the physical module state convention; SIM missing, waiting, and error states use amber/red rather than blue.
- Buttons use bundled Font Awesome icons so macOS does not substitute missing-glyph squares.
- The icon is an original generic 4G dongle illustration and contains no DJI logo.
- Simplified Chinese, Traditional Chinese, and English are real UI language packs; country/region is a separate formatting control.
- The expanded overview matches the selected two-column dashboard: flat header navigation, connection/signal/usage/balance/speed on the left, network/IP/SIM/time information on the right, and initialization readiness at the bottom.
- Full-view comparison confirms matching information hierarchy, two-column proportions, semantic colors, border radii, row dividers, typography hierarchy, icon family, and copy density.
- Focused-region comparison was performed on the left usage panel and right network panel within `.design-qa/full-overview-comparison.jpg`; separate crops were unnecessary because all labels and values remain legible in the normalized comparison.

## Functional checks

- All visible compact-surface actions are connected: Settings, Messages, Speed Test, Full App, Pin, and Return to Menu Bar.
- Full-view navigation buttons switch between Overview, Messages, Contacts, and Settings; network switching and cellular mode controls remain available under Settings.
- Automated tests: 16 passed.
- Signed ZIP extraction passes `codesign --verify --deep --strict`.
- Source/test scan contains no real user test phone number.

## Issue history

- Initial functional layout did not match the selected mock and was rejected.
- Corrected hierarchy, spacing, dual compact surfaces, circular quota visualization, circular module well, green status icon, balance badge, stable action icons, and actual language switching.
- Full overview iteration 1 (`full-overview-v1.png`) exposed stale dynamic values and a vertically stacked legacy density. Dynamic labels were rebound to live state and the layout was rebuilt as two dashboard columns.
- Iteration 2 (`full-overview-v2.png`) fixed live/demo value binding but retained scrollbars and clipped the initialization footer. The overview scroll wrapper was removed and the footer controls were made conditional.
- Iterations 3–5 corrected viewport ratio, repaint artifacts, vertical rhythm, and signal presentation. Final evidence is `full-overview-final.png` and `full-overview-comparison.jpg`.
- Remaining differences are P3 only: the original generic dongle artwork differs from the reference illustration, and exact macOS font rasterization varies with display scale.
- No open P0, P1, or P2 visual or functional issue remains.

## Final result

passed
