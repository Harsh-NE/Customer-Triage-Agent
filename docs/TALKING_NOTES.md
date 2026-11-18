# Talking notes: 8-minute talk + demo (two presenters)

Plan: **8:00 talk, about 1:50 demo, then questions.** Member 1 presents slides 1-7 (about 4:00); Member 2 presents slides 8-18 (about 4:05) and runs the demo from slide 12. Slides 13 (engineer view, 10 s in the demo), 19 (references) and 20 are not spoken. The same text is in each slide's speaker notes in `INT450_Docker_Triage_Agent_Presentation_v7.pptx`. Spoken text is about 976 words (about 7.5 minutes at a calm pace), which leaves a short buffer for slide changes and pauses.

Evaluation numbers in the deck come from the last real-LLM run (Gemini 3.5 Flash-Lite, 13 Oct 2026: 29 scenarios + 65 forum questions, simulated customer), plus recall@8 from the offline gold set. See `reports/presentation/METRICS_SUMMARY.md`.

| Slide | Speaker | Time | Topic |
|---|---|---|---|
| 1 | Member 1 | 0:15 | Title |
| 2 | Member 1 | 1:00 | Problem statement |
| 3 | Member 1 | 0:40 | Why we need an agent |
| 4 | Member 1 | 0:15 | Objectives and scope |
| 5 | Member 1 | 0:25 | Why an agent, not one LLM call |
| 6 | Member 1 | 0:25 | Data and knowledge sources |
| 7 | Member 1 | 1:00 | System architecture |
| 8 | Member 2 | 0:15 | Agents and tools |
| 9 | Member 2 | 0:25 | The agent in code |
| 10 | Member 2 | 0:25 | One request, end to end |
| 11 | Member 2 | 0:35 | Safety and guardrails |
| 12 | Member 2 | demo | Live demo |
| 14 | Member 2 | 0:20 | How we tested it |
| 15 | Member 2 | 0:55 | Results |
| 16 | Member 2 | 0:40 | Where it fails |
| 17 | Member 2 | 0:05 | Who built what |
| 18 | Member 2 | 0:25 | Conclusion |

If you are running late, drop slide 8 (modules; slide 7 covers it) and shorten slide 16 to its first sentence.

---

## Member 1

### Slide 1: Title (0:15)

Good morning. We are Team T__, presenting our Docker Support Triage Agent: a ticket goes in, and out comes a cited fix, or a ready-made case for a human engineer. I will cover the problem and design; my teammate, the modules and results.

### Slide 2: Problem statement (1:00)

The problem comes from a real industry setting. For every ticket, a support engineer repeats one routine: read it, work out product, symptom and urgency, search the docs and old tickets, then decide: fix or escalate. It is repetitive, the same problem arrives in different words so answers are not reused, and risky cases like data loss wait in the same queue. Our one-sentence problem: given a support ticket, the system must understand it, find grounded evidence and propose a cited fix, so engineers handle only hard cases, and it must escalate when evidence is weak or the case is risky. Example: 'docker pull fails with HTTP 429'. We return a summary, priority and a sourced fix, or an escalation.

### Slide 3: Why we need an agent (0:40)

Here is that routine, side by side. Understand: the agent extracts a problem signature and asks only for missing details, at most three questions. Prioritise: by code rules, so data loss or P1 goes straight to a human. Search: a cache, then docs, guides and old tickets, with a confidence check at each step. Decide: a cited fix, or a hand-over with a summary. And because two users describe one issue differently, we normalise every ticket into a signature so trusted answers can be reused.

### Slide 4: Objectives and scope (0:15)

Four measurable objectives: never miss a case needing a human; cite every fix; wrong fixes under 5%; and the right docs section in the top eight for 80% of real questions. We return to these in the results.

### Slide 5: Why an agent, not one LLM call (0:25)

Why not one LLM call? A single prompt answers from memory: no source, no check, no way to say 'I don't know'. Our task needs steps, tools, self-checking, recovery and hand-over, so one prompt cannot do it reliably: four stages, three tools, and it must be able to refuse.

### Slide 6: Data and knowledge sources (0:25)

Our knowledge is public: 11,440 chunks from 961 Docker doc pages, 661 community-guide chunks, and 13,092 resolved tickets. Only 2.5% of the docs are troubleshooting. Our test set has 89 questions, 65 of them real forum posts, including 46 the docs cannot answer, plus vague, urgent and injection cases, on purpose.

### Slide 7: System architecture (1:00)

The architecture, left to right. Input guard: OCR for screenshots, personal data masked, injection blocked. The Clarifier diagnoses and asks at most three questions. Hybrid retrieval, dense embeddings plus BM25, searches docs, then guides, then tickets. A code gate refuses if the evidence score is under 0.55. Only then does the LLM, Gemini Flash-Lite, draft a fix, and a verifier checks every step is cited. Red dashed arrows go to a human. Blue is plain code; orange is the only LLM. Stack: LangGraph for orchestration, ChromaDB with bge embeddings, Tesseract for OCR, and FastAPI with SQLite behind a React interface. Over to my teammate.

## Member 2

### Slide 8: Agents and tools (0:15)

Five modules, one job each: the Clarifier finds the likely issue; the retriever and gate refuse weak evidence; the drafter is the only LLM; the verifier drops uncited steps; the escalator hands over with a summary.

### Slide 9: The agent in code (0:25)

This is the real code. The orchestration is a LangGraph state machine, so failure paths are explicit edges, not hidden in a prompt. Two guards are plain code: data loss or security always escalates by rule, and the verifier drops any step without a valid citation.

### Slide 10: One request, end to end (0:25)

One request: 'Docker Hub pulls failing with 429'. It finds product and error code, asks one question because two docs entries match, retrieves the Docker Hub page, verifies citations, and answers with a link. If the customer says it did not work, we retry once with different evidence, then hand over.

### Slide 11: Safety and guardrails (0:35)

Safety is code, not prompts. The input guard blocks injection and masks personal data. The action gate sends data loss, security or production-down to a human before any question or model call. Steps without citations are dropped. Under 0.55 evidence, two failed fixes, or three unanswered questions, it hands over with a reason code. The LLM suggests; code decides.

### Slide 12: Live demo (demo, outside the 8 minutes)

DEMO (about 1:50, outside the 8 minutes). Case 1: pull-rate-limit message; expect no question and a cited answer. Case 2: 'Docker Hub pulls failing with 429'; expect one targeted question. Case 3: 'production database volume deleted'; expect an immediate P1 escalation. Then show slide 13 for 10 seconds: the engineer's view with reason, next checks and activity log.

### Slide 14: How we tested it (0:20)

We ran the real Gemini model on 94 cases: our 29 scenarios and 65 real forum questions, with a simulated customer. Honestly: we saw the test split while building, labels were reviewed by a model, the run is from October 13th, before our latest fixes, and we have not yet run a faithfulness judge on the wording.

### Slide 15: Results (0:55)

Results with the real Gemini model: every one of the 61 cases with no answer ended in escalation or rejection; 86% of all 94 cases ended in the right action; the wrong-fix rate is 4.3%, 4 of 94, just under our 5% limit; and all 27 fixes sent were cited. Retrieval narrowly missed: 78.9% against 80%. The key gap: on our own scenarios 85% are fixed first time; on real forum questions only 23%, 3 of 13. The rest are escalated, which we prefer to guessing. All 94 cases cost seven cents. Three of four objectives met.

### Slide 16: Where it fails (0:40)

Where it fails: on real questions with a documented fix, Gemini fixed 3 of 13; 8 were escalated and 2 got a wrong first fix, because the right section is found but ranked low, and only 2.5% of the docs are troubleshooting. Long pasted logs cut recall at eight from 0.84 to 0.65. Typos and two issues in one message also hurt. Limits: a small test set, model-reviewed labels, and wording quality not yet judged.

### Slide 17: Who built what (0:05)

Please ask each of us about the part listed here.

### Slide 18: Conclusion (0:25)

In short: with the real model, every case with no answer reached a human, and every fix sent was cited. Its weakness, ranking on real questions, is measured, with next steps. Remember us for this: an agent that answers only when it can cite the docs, and otherwise hands over with a summary. Thank you.

---

## Questions you are likely to get (short answers)

- **Why not just one LLM?** One prompt has no sources, no self-check and cannot refuse; we need steps, tools, verification and hand-over (slide 5).
- **Why Docker, when the problem statement was about Microsoft support?** Same support-engineer workflow; Docker's docs and public Q&A were available, so we built and measured it there.
- **Only 23% fixed on real forum questions: is it useful?** In the real-Gemini run all 61 no-answer cases reached a human and 4.3% of cases got a wrong first fix; the gap is ranking, which we measured and have a plan for.
- **Is the test set clean?** No: we saw the test split during development, and labels were reviewed by a model. We say so on slide 14.
- **Is the real-LLM evaluation current?** It is from 13 October, before our later fixes (early escalation, chatter filter, retry/validation). The offline runs on the current code gave the same outcomes on the 94 cases, but we have not re-run Gemini.
- **Where is faithfulness/answer quality?** Not measured: the faithfulness judge was not run. The Gemini run shows that every sent fix cites evidence, not that the wording is faithful.
- **What did it cost?** $0.07 for all 94 cases (155 LLM calls, about 3 s median per call).
- **Why 0.55?** It is the evidence-score threshold for the gate; it was set early and calibration is listed as future work.
- **What is the LLM used for?** Only drafting the fix (Gemini Flash-Lite); guards, gate and verifier are plain code.
