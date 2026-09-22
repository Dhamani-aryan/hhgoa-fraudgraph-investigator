# Fraud Policy v1.0

**Source:** the Fraud Policy section of the supplied dataset `README.md`
(`data/raw/README.md`, SHA-256 `57e6dd7c7766b4ef...`). That file is authority #1.
This copy exists so the policy can be retrieved as citable text and loaded into
TigerGraph vector search. If the two ever disagree, the supplied README wins.

Every section below carries a stable anchor. An evidence `ref` of the form
`policy:<anchor>` resolves to the section with that anchor, and the validator's
R21 rule uses those anchors as the allowed policy references.

---

## policy:actions

The agent may recommend several actions for one case, ordered by what happens
first. These fourteen identifiers are the only allowed values.

| Action | What it does | Customer impact |
|---|---|---|
| `ALLOW_TRANSACTION` | Let the flagged transaction stand | None |
| `DECLINE_TRANSACTION` | Decline the flagged authorization only. Card stays active | Low |
| `MONITOR_CARD` | Card stays active; raise monitoring sensitivity for 72 hours | None |
| `MONITOR_CONNECTED_CARDS` | Put other cards linked to the same device profile, region cluster, or ring under monitoring | None |
| `WARN_CUSTOMER` | Send an informational message | None |
| `VERIFY_WITH_CUSTOMER` | Ask the cardholder whether they made the transaction. Card stays active pending reply | Low |
| `STEP_UP_AUTH` | Require a one-time passcode or app confirmation before further activity | Low |
| `BLOCK_CARD` | Block this card and reissue | High |
| `BLOCK_ALL_CARDS` | Block every card the customer holds | Very high |
| `GENERATE_REPORT` | Write up the investigation for the internal record, without opening a case | None |
| `CREATE_CASE` | Open an internal fraud case with the evidence attached, and write it to the graph | None |
| `FILE_REPORT` | File a suspicious activity report with the regulator | None |
| `ESCALATE_TO_ANALYST` | Hand the case to a human analyst with the evidence | None |
| `CLOSE_NO_FRAUD` | Close the alert as legitimate | None |

## policy:routing

| Route | Applies to |
|---|---|
| `auto` | `ALLOW_TRANSACTION`, `MONITOR_CARD`, `MONITOR_CONNECTED_CARDS`, `WARN_CUSTOMER`, `VERIFY_WITH_CUSTOMER`, `STEP_UP_AUTH`, `GENERATE_REPORT`, `CREATE_CASE`, `ESCALATE_TO_ANALYST`, `CLOSE_NO_FRAUD` |
| `L1` (team lead) | `DECLINE_TRANSACTION`; `BLOCK_CARD` when exposure ≤ $2,500 |
| `L2` (fraud manager) | `BLOCK_CARD` when exposure > $2,500; `BLOCK_ALL_CARDS` always; `FILE_REPORT` always |

The agent recommends. Only `auto` actions may be executed by the agent. `L1`
and `L2` actions are recommended with the route stated and wait for a human.

Routing is implemented in `domain.enums.required_route` and checked by
validator rule R10. The LLM cannot choose a route.

## policy:R1

**Verify before you block on a weak signal.** If the case rests on a single
signal (including a risk score alone) and the assessed fraud probability is
below 0.70, recommend `VERIFY_WITH_CUSTOMER` or `STEP_UP_AUTH` before any
block. Blocking a legitimate customer on one signal is a policy breach.

## policy:R2

**Customer denies the transaction.** Recommend `BLOCK_CARD` and `CREATE_CASE`.
Add `FILE_REPORT` if exposure exceeds $1,000 or the case connects to a shared
device profile or another card's fraud.

## policy:R3

**Customer confirms the transaction.** Recommend `CLOSE_NO_FRAUD`. Note the
confirmation in the case file.

## policy:R4

**No reply within 24 hours.** Recommend `MONITOR_CARD` and
`DECLINE_TRANSACTION` for pending authorizations. Escalate if exposure exceeds
$500.

## policy:R5

**Card testing.** Three or more small online authorizations on one card within
an hour, followed by a larger purchase: recommend `DECLINE_TRANSACTION` and
`STEP_UP_AUTH`. If a purchase over $100 has already cleared, recommend
`BLOCK_CARD`.

## policy:R6

**Shared origin.** When several cards show fraud from the same device profile,
the same billing region, or the same recipient email in one window, name the
shared element, recommend `CREATE_CASE` and `FILE_REPORT`, and
`MONITOR_CONNECTED_CARDS` for every card that shares it.

## policy:R7

**Disputed but legitimate.** When the customer disputes a charge that matches
their own recurring pattern (same merchant, same amount, monthly), recommend
`CREATE_CASE`, `VERIFY_WITH_CUSTOMER`, and `WARN_CUSTOMER`. Do not block.

## policy:R8

**Escalate when uncertain and exposed.** If the verdict is `uncertain` and
exposure exceeds $500, or the evidence conflicts, recommend
`ESCALATE_TO_ANALYST`.

## policy:R9

**Undocumented patterns.** When activity fits none of the known patterns but
the evidence shows coordinated or repeated abuse across customers, recommend
`CREATE_CASE`, `FILE_REPORT`, and `ESCALATE_TO_ANALYST`, and describe the
pattern in your own words. Do not force it into a known category.

## policy:R10

**Never `BLOCK_ALL_CARDS`** unless at least two of the customer's cards show
confirmed fraud or the customer's credentials are confirmed compromised.

## policy:case-vs-report

A **case** (`CREATE_CASE`) is the bank's internal record of an investigation.
Open one whenever fraud probability reaches 0.30, whenever evidence is
requested, or whenever a customer disputes a charge. A case can be closed as
fraud or as legitimate, updated when new evidence arrives, and should be
written into the graph so later investigations can find it.

A **suspicious activity report** (`FILE_REPORT`) is a regulatory filing sent
outside the bank. File one when fraud is confirmed or strongly suspected **and**
at least one of these holds:

- exposure exceeds $1,000;
- the activity connects to a shared device profile, a shared region cluster, or
  another customer's fraud;
- the pattern is coordinated or undocumented (R9).

A report always has a case behind it. Most cases never need a report.

## policy:exposure

Exposure is the sum of the absolute amounts of every transaction identified as
part of the fraud episode, including the flagged one, in USD.

The agent never computes this from prose: `validation.dataset_ids.exposure_of`
recomputes it from the supplied amounts and validator rule R07 rejects any
mismatch.

## policy:evidence-gathering

The agent may, without approval, ask the customer to validate a transaction,
request step-up authentication, or request information from an analyst. Those
responses are not provided by the challenge. They must be simulated in-system
and the assumption stated in the answer's `evidence_requests`.

## policy:stopping

Stop investigating when one of these holds:

- fraud probability is at or above 0.85, or at or below 0.15, supported by at
  least two independent pieces of evidence;
- a verification response settles the question;
- further steps are unlikely to change the decision — say so in `stop_reason`.

Investigations that continue past a defensible decision waste time.
Investigations that stop before one create risk. Both are marked down.

## policy:explaining

Every recommendation must state what evidence was used, why more evidence was
requested if it was, and why the chosen actions follow from this policy, citing
the rule number.
