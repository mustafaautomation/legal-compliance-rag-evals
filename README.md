# legal-compliance-rag-evals

[![CI](https://github.com/mustafaautomation/legal-compliance-rag-evals/actions/workflows/ci.yml/badge.svg)](https://github.com/mustafaautomation/legal-compliance-rag-evals/actions/workflows/ci.yml)

Personal open-source demo by Muhammad Mustafa. It is a small RAG assistant over a fictional company's compliance policies, plus short GDPR excerpts, with an evaluation gate for answer checks and retrieval.

Helios Ledger Ltd is not a real company. The policies were written for this demo. The GDPR passages are short excerpts from EUR-Lex, not the official text of record. Nothing here is legal advice.

## What it measures

The offline gate scores a deterministic pipeline. It does not call an LLM, and this repository does not commit RAGAS judge scores.

Retrieval metrics measure whether the right clause was fetched:

- **retrieval_hit_rate** and **MRR** check the gold document in the top clauses.
- **non_llm_context_recall** is RAGAS `NonLLMContextRecall`. It checks whether the gold clause text is similar to a retrieved clause.
- **string_presence** is RAGAS `StringPresence`. It checks whether the labelled phrase appears in the reply.

Guardrail metrics measure the behaviour the prompt asks for:

- **disclaimer_rate**: the reply says it is not legal advice.
- **citation_rate**: an answerable reply includes a `Sources:` line with a clause id or GDPR article.
- **refusal_correctness**: out-of-scope and trap questions are refused with "I don't know" and "will not speculate", and answerable questions quote the source clause instead of guessing.

Live mode, when `OPENAI_API_KEY` is set, also runs the current RAGAS collections metrics: faithfulness, answer relevancy, context precision, and context recall. Those numbers are not in the sample report below, because that run had no API key.

## Architecture

```mermaid
flowchart LR
  docs[Markdown corpus] --> chunks[Clause chunker]
  chunks --> tfidf[TF-IDF embeddings]
  tfidf --> faiss[FAISS index]
  tfidf --> pg[pgvector optional]
  question[Question] --> faiss
  question --> pg
  faiss --> prompt[Guarded or no-guardrail prompt]
  pg --> prompt
  prompt --> provider[Fake, OpenAI, or Anthropic provider]
  provider --> answer[Reply]
  answer --> gate[Threshold gate]
```

Clauses are the `##` sections in `data/corpus`. Embeddings are TF-IDF over those clauses, L2-normalised, and searched with FAISS inner product. The same vectors can be stored in Postgres with pgvector. The default chat provider quotes the retrieved clause when enough question words appear in it, and otherwise refuses. OpenAI and Anthropic use the same system prompt and the same retrieved clauses.

Two broken variants exist so the gate can be shown to fail:

- `no_guardrail` keeps the retriever and drops citations, the disclaimer, and refusals.
- `bad_retriever` ignores the question and returns only the subprocessor schedule.

## Sample report

Scores from the offline run recorded in this repo. The guarded column is the one CI gates.

| Metric | Before: no-guardrail prompt | After: guarded prompt | Bad retriever | Threshold |
| --- | ---: | ---: | ---: | ---: |
| retrieval_hit_rate | 1.0000 | 1.0000 | 0.0000 | 0.90 |
| mrr | 1.0000 | 1.0000 | 0.0000 | 0.80 |
| non_llm_context_recall | 1.0000 | 1.0000 | 0.0000 | 0.90 |
| string_presence | 0.8000 | 1.0000 | 0.2000 | 0.90 |
| disclaimer_rate | 0.0000 | 1.0000 | 1.0000 | 1.00 |
| citation_rate | 0.0000 | 1.0000 | 0.0000 | 0.95 |
| refusal_correctness | 0.0000 | 1.0000 | 0.2000 | 0.95 |

The guarded run passed. The no-guardrail prompt failed disclaimer, citation, string presence, and refusal correctness. The bad retriever failed retrieval, string presence, citation, and refusal correctness. Per-question failures are in [docs/eval_report.md](docs/eval_report.md) and [docs/eval_report.html](docs/eval_report.html).

![Eval report](docs/eval_report.png)

Thresholds live in [configs/thresholds.yaml](configs/thresholds.yaml). `legal-rag-eval` exits non-zero if any scored metric is below its threshold.

## Run locally

Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
uv run legal-rag ask "How long are customer invoices kept after the contract ends?"
uv run legal-rag-eval --mode offline --variant guarded
uv run pytest
uv run ruff check .
uv run mypy
```

Offline mode reads the committed JSONL snapshots in `data/snapshots/` and recomputes the non-LLM metrics. It does not need an API key. Regenerate the snapshots and the report with:

```bash
uv run legal-rag-eval --write-report
```

Live RAGAS judging:

```bash
export OPENAI_API_KEY=...
uv run legal-rag-eval --mode live --provider openai
uv run legal-rag ask --provider openai "How long are customer invoices kept after the contract ends?"
```

Anthropic is the other live provider: `--provider anthropic` with `ANTHROPIC_API_KEY`. Optional model overrides are `OPENAI_MODEL`, `OPENAI_EMBEDDING_MODEL`, and `ANTHROPIC_MODEL`.

pgvector, if you want the Postgres path:

```bash
docker compose up -d
DATABASE_URL=postgresql://legal:legal@localhost:5432/legalrag \
  uv run legal-rag ask --retriever pgvector "How long are customer invoices kept after the contract ends?"
```

Tests use FAISS and do not start Docker.

## Eval set

`data/eval/questions.jsonl` has 40 questions. Each row has a reference answer, the gold document when there is one, and an expected behaviour:

- `answer`: the clause contains the fact.
- `correct`: the question asserts something the clause contradicts. The reply should quote the clause.
- `refuse`: the documents do not contain the answer. The reply should say "I don't know" and refuse to speculate.

The set includes retention, breach, vendor, transfer, marketing, security, and GDPR questions, plus out-of-scope questions (tax, a court decision, a customer count, a wage, a personal phone number) and adversarial prompts that ask the model to ignore the documents or promise an outcome.

## CI

`.github/workflows/ci.yml` runs lint, typecheck, unit tests, and the offline gate. All four jobs are required. None use `continue-on-error`.

`.github/workflows/live-eval.yml` is manual (`workflow_dispatch`). The live RAGAS job runs only when the `OPENAI_API_KEY` secret is set. A dispatch without that secret finishes without calling the API.

## Adapt it to another document set

1. Replace `data/corpus` with your own markdown. Use `Doc-ID`, `Title`, `Source`, and `License` headers, and put operative text under `## Clause` or `## Article` headings.
2. Replace `data/eval/questions.jsonl`. Keep refusals and trap questions in the set. Point `anchors` at a phrase that appears in exactly one clause.
3. Edit `configs/thresholds.yaml` after you have a run you trust.
4. Run `uv run legal-rag-eval --write-report` and commit the new snapshots only after you have read them.
5. For generative answers, run `--mode live` with your key. Treat the offline scores as retrieval and guardrail checks, not as a substitute for the LLM-judged metrics.

## Data and licence

The Python code is MIT. See [LICENSE](LICENSE).

The Helios Ledger policies are synthetic and released CC0-1.0 for this demo. They are not a real company's records and they are not legal advice.

GDPR excerpts are taken from Regulation (EU) 2016/679 as published on EUR-Lex, CELEX:32016R0679, Official Journal of the European Union, L 119, 4 May 2016:

https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679

EUR-Lex content is made available for reuse with source acknowledgement. The files under `data/corpus/HL-REG-GDPR-*.md` are short excerpts, not the complete articles and not the text of record. They are not relicensed as MIT or CC0.

`data/snapshots/manifest.json` records that judge scores were not produced.
