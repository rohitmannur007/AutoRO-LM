# Experiment protocol

## What the code measures today

`synthetic_share` fits a TF-IDF logistic regression classifier. Its macro F1 is not an LLM extraction score. `synthetic_share_llm` stays `unavailable` until a separate fine-tuned adapter exists for each mixture, and it does not copy the classifier score. `extraction_provider` and `qa_rag` call the provider selected in settings. If that provider is down, the run is unavailable and the job fails. A demo-provider score is a rules or extractive baseline.

## Hypothesis

On a held-out real extraction set, changing the share of approved synthetic training rows changes field-level F1 of a fine-tuned small LLM. The classifier study above is a separate, narrower question: does the same mixture change component-category macro F1? An arm that cannot be filled is skipped. Scores are not interpolated, and a rising curve is not assumed.

## Baselines

1. Rules extractor for DTC and field JSON. It is not a language model.
2. TF-IDF (word and bigram) plus logistic regression for `component_category` only. It does not emit full repair JSON.
3. Demo extractive RAG for questions with hand labels.
4. Retrieval modes on the same questions: BM25, TF-IDF cosine, and reciprocal rank fusion (k=60).

A prompted LLM baseline exists only when Ollama or a hosted endpoint is configured and actually responds. A missing model is a 503, not a score.

## Data

- Gold file: `backend/data/demo/gold_examples.json` (DEMO, guideline 1.0.0).
- Train rows may be used to fit the classifier. Validation is not the reported test.
- Test rows, including the 2019 Camry holdout group, are not training data and are not synthetic seeds.
- Synthetic rows enter a mixture only when they are stored examples. Rejected rows are excluded from the filtered arm. The unfiltered arm still drops rule-rejected rows and records that choice.

## Synthetic shares

Target size equals the number of real train gold rows. Shares 0, 0.25, 0.5, 0.75, and 1.0 are attempted. If the 0% arm has no real rows, or a higher share needs more synthetic rows than exist, that arm is stored as `skipped` with a reason and `macro_f1: null`. Scores are not interpolated.

## Metrics

Definitions live in `backend/app/metrics.py`.

- Field precision, recall, and F1: non-null gold is the positive class. Null/null is a true negative and is outside the denominator. An empty denominator is null, reported as unavailable.
- DTC scores are micro-averaged set overlap.
- Exact match is full target equality.
- Schema-valid rate is the share of extractor outputs that passed evidence checks.
- Hallucination rate is unsupported predicted non-null scalars or extra DTCs divided by predicted non-null items.
- Retrieval: Recall@5, Precision@5, and MRR over hand-labeled relevant document ids. Questions with an empty relevant set do not contribute a recall.
- QA fact rate checks required and forbidden phrases. It is not a human grading study.
- Abstention treats “gold unanswerable and system abstained” as the positive class.
- Bootstrap: percentile interval of the mean of per-example scores, 1000 resamples, seed 42. With a handful of fixture rows this describes resampling of that set, not a population of repair orders.

## Error analysis

Extraction and classifier runs write up to 50 mismatches under `metrics.error_analysis` and, when any exist, `data/runtime/artifacts/<run_id>_errors.json`. Categories include DTC mismatch, component mismatch, unsupported component, and symptom mismatch.

## Reporting

Do not copy a number into the technical report unless it is in a stored experiment payload from a command you ran. Fixture-scale scores are not a benchmark claim.
