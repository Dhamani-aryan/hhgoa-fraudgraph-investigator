# Fraud patterns

**Source:** the Known Fraud Patterns and Glossary sections of the supplied
dataset `README.md`. That file is authority #1; this copy exists so the
typologies can be retrieved as citable text and loaded into TigerGraph vector
search.

Section anchors are stable. An evidence `ref` of the form `pattern:<anchor>`
resolves to the section with that anchor.

The README is explicit that **these are not the only patterns in the data**.
Activity that fits none of them is reported as `undocumented` with a
description, never forced into a category.

---

## pattern:card_testing

A stolen card number is checked before use: three or more tiny online
authorizations, often under $5, then a larger purchase. Confirmed by the
sequence itself. Policy R5.

Deterministic candidate conditions:

- at least three small online authorizations on one card within one hour;
- amounts usually below $5;
- followed by a materially larger purchase;
- a consistent shared device or identity strengthens the signal.

## pattern:card_not_present_fraud

The number is used online without the card. Amounts and products that do not
fit the cardholder's history, often in a burst of two to four within 48 hours.
On its own, one unusual online purchase is ambiguous: verify. Policy R1 to R4.

## pattern:card_not_present_new_device

As above, with the identity record marking the device as `New` for this account
(`id_15`), sometimes behind a proxy (`id_23`). Stronger than plain
card-not-present fraud, still not proof: people buy new phones.

## pattern:out_of_region_use

Card-present purchases in a billing region the cardholder has no history in,
while their normal activity continues at home. Several days of purchases in one
new region is a trip, not a clone. Policy R2, R3.

## pattern:account_takeover

Mixed-channel activity inconsistent with the cardholder, often with device and
match-flag anomalies, pointing to stolen credentials rather than a stolen
number.

## pattern:undocumented

Used only when the evidence shows coordinated or repeated abuse that fits none
of the five documented patterns. The answer must describe the behaviour in
plain words in `pattern_description` and follow policy R9. Finding an
undocumented pattern is scored.

## pattern:none

Used for legitimate activity, and for activity that does not support any fraud
pattern. Half the benchmark cases are legitimate; an agent that blocks
everything scores badly.

---

## pattern:shared-origin-caution

The audit of the supplied data (`runs/data_audit.json`) shows why a shared
entity is not by itself evidence of a ring:

| Shared entity | Distinct values | Max cards on one value |
|---|---:|---:|
| Purchaser email domain | 59 | 9,332 (`gmail.com`) |
| Recipient email domain | 60 | 5,158 (`gmail.com`) |
| Billing region `addr1` | 332 | 2,075 |
| Device signature (strength ≥ 3) | 5,386 | 842 |

Email domains and billing regions are supernodes. A device signature is far
more discriminating: its median is 1–2 cards and 2,641 strong signatures touch
exactly one card.

A shared-origin claim therefore requires **time-local multi-card activity plus
either fraud enrichment or a rare shared entity**. Raw global degree is never
sufficient. Validator rule R24 enforces this.

## pattern:device-signature

A device profile is `DeviceInfo | id_30 (OS) | id_31 (browser) | id_33 (screen)`.
`signature_strength` counts how many of those four fields are present, 0 to 4.

Distribution across the 144,432 identity records: strength 4 on 71,288 rows,
3 on 6,335, 2 on 43,210, 1 on 19,951, 0 on 3,648.

Rows are never collapsed because a coarse field alone matches. A weak signature
stays transaction-local and does not create a shared-device edge capable of
linking cards.

## pattern:risk-score

Every transaction carries a `risk_score` from 0 to 1 from the bank's model.
Across the supplied data the median is 0.12 and the 99th percentile is 0.83.

The README states plainly: above 0.7 most flagged transactions turn out to be
legitimate, and some fraud scores near zero. It is an input feature with capped
influence, never a verdict and never a label.
