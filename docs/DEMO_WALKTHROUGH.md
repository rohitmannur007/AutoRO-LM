# Demo walkthrough

About two minutes. Stay on DEMO data.

1. Open http://127.0.0.1:5173. Point at the DEMO banner, the document count, and the provider card that says the extractor is not a language model.
2. Text extraction. Load the DEMO sample. Run extraction. Show P0420, the catalytic converter from the sentence that says it was replaced, the evidence quote, and the caveat that a code is not proof of failure. Copy or download the JSON.
3. Diagnostic QA. Use the answerable P0420 question. Open the citation and the highlighted passage. Then use the torque question and show the abstention banner. No torque number should appear.
4. Data sources. Show the DEMO badge and provenance. Do not start an NHTSA download unless you intend to.
5. Synthetic studio. Generate two terse/CCC paraphrases from `demo-civic-catalyst`. Show that the provider is deterministic and not an LLM. Mention that the Camry holdout cannot be a seed.
6. Experiments. Run “Rules extraction”. Open the stored run and say the numbers are from that run on the fixture gold set, not a public benchmark. If the synthetic-share chart is empty, say the missing arms were skipped because approved synthetic rows were not available.
7. Settings. Show that the hosted key field is only “present: yes/no”.

Screen recording script, spoken:

“This is AutoRO-LM, a local research prototype for automotive repair text. The banner means we are on hand-written fixtures and a rule extractor, not a dealer system and not a downloaded LLM. I extract a Civic note: the code is P0420 and the converter is filled only because the note says it was replaced. I ask what P0420 means and the answer quotes the fixture that says the code is not proof the converter failed. A head-bolt torque question abstains. Evaluations on this page are computed from the stored gold file; I am not claiming a leaderboard result.”
