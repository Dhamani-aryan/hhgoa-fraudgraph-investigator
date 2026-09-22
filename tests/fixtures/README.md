# Test fixtures

`valid_answer.json` is a **contract fixture**, not an investigation result.

Its identifiers are real: case `HHG-017`, card `C04570-K1`, customer `C04570`,
the flagged transaction `3450629` and its two predecessors on the same card and
device, and closed cases that all closed before the case anchor time. Using
real identifiers lets the same file exercise the dataset-ID validator.

Its conclusions -- the verdict, the probability, the pattern, the narrative --
are illustrative values chosen to make every branch of the contract reachable.
They are **not** the output of an investigation and must never be copied into
`cases/`. The golden end-to-end fixtures promoted in Gate 4 carry real agent
output; this file does not.

`invalid/` holds one file per rule the validator must reject. Each filename
names the rule it breaks.
