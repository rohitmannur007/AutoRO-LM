# Technical report template

Fill this only with measurements you produced. Leave a cell blank rather than estimating it.

## Data actually used

- Source and access date:
- Record counts by narrative kind:
- Demo versus external:
- Split sizes (train / validation / test):
- Known leakage checks:

## Method

- Extractor or classifier:
- Provider and model revision:
- Seed:
- Hardware (machine, Python, max RSS if recorded):
- Commit:

## Measured results

| Run id | Task | Status | Metric | Value | Support | Caveat |
| --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |

Synthetic share (only rows with a stored macro F1):

| Share | Status | Train size | Macro F1 | Reason if skipped |
| --- | --- | --- | --- | --- |
| 0 |  |  |  |  |
| 0.25 |  |  |  |  |
| 0.5 |  |  |  |  |
| 0.75 |  |  |  |  |
| 1 |  |  |  |  |

Retrieval:

| Mode | Recall@5 | MRR | Precision@5 | Support |
| --- | --- | --- | --- | --- |
| lexical |  |  |  |  |
| vector |  |  |  |  |
| hybrid |  |  |  |  |

## Error analysis

Attach `artifacts/<run_id>_errors.json` when the run created one. Group the rows. Do not invent categories that are not in the file.

## Limits

- Fixture scale versus a real complaint corpus:
- What was not run (Ollama, MLX, full NHTSA flat files):
- Metric definitions that were undefined because of empty support:

## Future work

- 
