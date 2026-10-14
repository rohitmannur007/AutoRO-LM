# Annotation guidelines

Guideline version: **1.0.0**. Schema version: **1.0.0**.

These rules apply to gold JSON and to what the rule extractor is allowed to emit.

## Fields

- `vehicle.make`, `vehicle.model`, `vehicle.model_year`: copy only values written in the note or supplied as metadata. Use the alias table in code for spelling (`chevy` to Chevrolet). Do not infer a platform from a part name.
- `vin`: only when a person supplied it for their own note. Do not store VINs from NHTSA complaints.
- `complaint`: the customer’s reported problem when the note says the customer reports or states it, or a `Complaint:` line. Otherwise null.
- `symptom`: one normalized operational symptom that is literally supported (check engine light, grind, rough idle, and the other labels in the extractor). If several appear, the gold label records the primary one and the note should say so.
- `dtc_codes`: normalized `P|C|B|U` plus four digits. Do not invent a code from a symptom.
- `component`: a part the note says was replaced, repaired, installed, or explicitly called failed, outside a mere suspicion. A DTC is not enough.
- `suspected_component`: a part named with suspect, possible, or likely. It must stay distinct from `component`.
- `repair_action` and `correction`: the stated action. If no action is stated, null. Do not fill a “typical” repair.
- `cause`: only a `Cause:` line or “caused by / due to”. Otherwise null.
- `unknown_fields`: every core field that stayed null.

## Evidence

Each non-null extracted field should point at a quote that occurs in the note, with character offsets when the extractor can find them. Catalog knowledge that is not in the note is not evidence for a filled field.

## Narrative kinds

Keep these distinct in `narrative_kind`:

- `consumer_complaint` — NHTSA owner narrative, not a confirmed repair
- `recall` — campaign summary
- `manufacturer_communication` — concise communication summary, not a full manual
- `demo_technician_note` — fictional demonstration note
- `reference_note` — hand-written DEMO explanation of a generic OBD code title

## Splits

Assign a source group (make, model, year, or an explicit group id) before writing synthetic text. Every document in a group shares one split. The gold test split is not used for training, prompt editing, or synthetic seeds. The fixture holdout group is `grp-holdout-camry-2019`.

If a real corpus has fewer than three groups, say so and do not invent a validation split. The helper in `app/splits.py` documents that fallback.

## Reviewers

`reviewer_notes` may describe the decision. Do not store a reviewer’s name or contact details.
