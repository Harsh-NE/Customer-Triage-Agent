# Final talk script: Kaaviya and Harshini (about 9.5 minutes including the demo)

Slide numbers refer to `INT450_Docker_Triage_Agent_Presentation_Final.pptx`. Speak from the ideas, not the slide text. About 1,220 spoken words, which is roughly 9.5 minutes at a relaxed pace, so it fills the 10 minutes. The live demo runs while you speak; if the demo takes longer, use the cut at the bottom.

| Part | Who | Slides | Words | About |
|---|---|---|---|---|
| Opening, problem, solution | Kaaviya | 1-3 | 264 | 2:00 |
| Objectives, why an agent, data and RAG, architecture, Clarifier, orchestration | Harshini | 4-9 | 526 | 4:00 |
| One request, safety, live demo | Kaaviya | 10-13 | 174 | 1:20 |
| Evaluation | Harshini | 14-16 | 193 | 1:30 |
| Close | Kaaviya | 18 | 66 | 0:30 |

## Kaaviya: slides 1-3

**Slide 1.** Good morning, sir. We are Team 12, I am Kaaviya and this is Harshini. Our project is a Docker support triage agent: a customer's ticket goes in, and out comes either a fix with sources, or a case handed to a human engineer with everything they need.

**Slide 2.** Let me start with the problem, because it shaped everything else. Think about what a support engineer does with every ticket: read it, work out what is really going wrong and how urgent it is, search the docs and old tickets, then decide, fix it or escalate. It is the same routine every time. Customers describe the same problem in different words, so good answers are not reused. And risky cases, like "my data is gone", can sit in the same queue as a simple how-do-I.

So we built an assistant for the engineer: given a ticket, it understands it, finds evidence, and proposes a fix with citations, so engineers only handle the hard cases. And when it is not sure, it says so and hands over. For example, "docker pull fails with a 429": we return a summary, a priority, and steps with the doc link.

**Slide 3.** It follows the engineer's own routine, with checks built in. It turns the ticket into a structured problem and asks only for what is missing. Priority comes from plain rules, so data loss goes straight to a human. It searches a cache, then docs, guides and old tickets. And it either sends a cited fix, or hands over with a summary. Harshini will now take you through how it works.

## Harshini: slides 4-9

**Slide 4.** Thanks. First, we set four goals we could actually measure. Never miss a case that needs a human. Every fix carries a citation. Wrong fixes under five percent. And the right docs section in the top eight for 80% of real questions. We also drew a line: Docker only, text and screenshots, and it never runs commands on a customer's machine.

**Slide 5.** Why not just give the ticket to an LLM? Because a single prompt answers from memory: no source, no check, and no way to say "I don't know", which is the dangerous part in support. We need steps, tools, a check on the answer, recovery, and a path to a human. That is why it is an agent.

**Slide 6.** Now the knowledge, the RAG part. We use retrieval because answers must come from the Docker documentation, not the model's memory, so we can cite them. The main source is the official docs: about 960 pages, split by heading into 11,440 chunks and tagged by type. Then a small tier of community guides. Then about 13,000 resolved tickets, used only as a fallback, because they are community answers, five years old on median. A small knowledge graph of 153 entities links how customers describe a problem to the right doc section. One honest finding: only 2.5% of the docs are troubleshooting. And a reranker and filters we tried did not help, so we left them off.

**Slide 7.** Here is the whole system, left to right. The input guard runs OCR on screenshots, masks personal data, and blocks injection. The Clarifier, which I will come to, works out the problem. Retrieval is hybrid: embeddings plus keyword search, merged by rank fusion, because exact error strings matter in support. It searches docs first, then guides, then tickets. Then a code gate checks the evidence score: below 0.55, the model is not allowed to write anything. Only then does the LLM draft, and a verifier checks every step has a citation. Blue is plain code, orange is the one LLM step, red is the hand-over to a human.

**Slide 8, the Clarifier.** This is the part I built. Its job is to turn a messy message into a clear problem with as few questions as possible. It extracts the product, symptoms and error text, then searches the knowledge base and ranks which known issues could match, like a differential diagnosis. If one clearly leads, it says READY. If several are close, it asks the one question that best separates them, not a generic "tell me more". If the customer already pasted the documented error, it asks nothing. And we cap it at three questions, so it never keeps pestering.

**Slide 9, orchestration.** This is how it is wired, with LangGraph. The Clarifier and the Resolver are two nodes, and the interesting part is the conditional edges. After the guard: escalate, go back to the Clarifier, or continue. After the gate: draft, search the next tier, or escalate. After the verifier: send, retry, or escalate. Each is an ordinary Python function, not a prompt, so failure paths are explicit and testable. When it needs the customer, the graph pauses and saves its state. Kaaviya will take the resolver side.

## Kaaviya: slides 10-13

**Slide 10.** Quick example: "Docker Hub pulls are failing with a 429". The Clarifier sees two similar entries and asks one question. Retrieval finds the Docker Hub page, the verifier checks the citations, and the customer gets steps with a link. If it fails, we retry once with different evidence, then hand over.

**Slide 11.** Safety is where we were strictest, and none of it is "we told the model to be careful". It is code. Data loss, security or production-down goes to a human before any question or model call. Steps without citations are dropped. Weak evidence, two failed fixes, or three unanswered questions means hand over, with a reason code. The model suggests, code decides. Let me show you.

**Slides 12-13, live demo.** Case one, a clear message: no question, a cited answer. Case two, the vague 429: one targeted question first. Case three, "production database volume deleted": escalated at once as P1, no fix attempted. And here is what the engineer sees: priority, why the agent stopped, next checks, and the log, so they do not start from zero.

## Harshini: slides 14-16

**Slide 14.** For evaluation, we ran the real Gemini model on 94 cases: 29 scenarios we wrote and 65 real forum questions, with a simulated customer. To be upfront: we saw the test split while building, labels were reviewed by a model, and that run predates a few later fixes.

**Slide 15.** Safety first. All 61 cases with no answer ended with a human: 100%. About 86% of all cases ended in the right action. Wrong fixes were 4.3%, under our five percent limit, every fix sent was cited, and the whole run cost about seven cents. The honest gap is how often it fixes things: 85% on our own scenarios, but only 3 of 13 on real forum questions; the rest were escalated, not guessed. Retrieval just missed, 78.9% against 80%. So three of four objectives met.

**Slide 16.** Why the gap? The right section is often found but ranked too low, and the docs have little troubleshooting content. Long pasted logs also hurt: recall fell from 0.84 to 0.65. We did find and fix one bug: "thanks in advance" confused the Clarifier. Next: curated cards from tickets, extracting error lines from logs, and testing with real users.

## Kaaviya: slide 18

To wrap up: it never missed a case that needed a human, and it only sends fixes it can cite. Its weakness, ranking on real questions, is measured, and we know how to improve it. If you remember one thing: an agent that answers only when it can cite the docs, and otherwise hands over with a summary. Thank you, we are happy to take questions.

## If you run long

Skip slide 10 (the demo shows the same flow) and the last two sentences of slide 6.

## Who answers what

- **Harshini:** the Clarifier, question cap, knowledge base, retrieval, knowledge graph, orchestration, evaluation.
- **Kaaviya:** the Resolver, gate threshold 0.55, verifier, escalation rules, API, OCR, demo.
- **Either:** why Docker when the original problem was Microsoft support (same workflow; Docker's docs and public Q&A were available); why the real-LLM run is from 13 Oct; why there is no faithfulness score yet.
