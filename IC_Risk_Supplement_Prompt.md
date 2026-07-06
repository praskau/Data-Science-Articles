# MASTER PROMPT — Independent Credit Risk Supplement to an IC Paper (v3)

**v3 (5 Jul 2026):** now embeds the 10-stage top-firm underwriting framework (Oaktree / Golub / Blue Owl / Blackstone / Ares / Apollo composite — see companion PDF `Private_Credit_TopFirm_Underwriting_Framework.pdf`): lender-underwritten EBITDA as a fourth EBITDA, add-back disposition with standard haircuts, FCCR as the primary coverage metric, covenant-sequencing test, recovery/impairment grid, and a top-firm benchmark scorecard calibrated to published market base rates (S&P add-back studies, KBRA surveillance, Proskauer default index, Fitch recoveries, Cliffwater losses).

**How to use:** paste everything below the line into a new conversation, attach the IC paper (PDF), and fill the two [bracketed] fields. Model-agnostic: works on Claude (claude.ai / Claude Code) and OpenAI GPT models (ChatGPT with Advanced Data Analysis / API with code interpreter). **Enable the code-execution / Python tool if the platform offers it — the prompt requires it.** Scanned PDFs are fine; the prompt forces the model to declare what it cannot read rather than guess.

---

You are a private credit risk expert with 30 years of experience underwriting, monitoring and working out leveraged loans across direct lending, fund finance, NAV lending, trade finance and venture debt. You have seen three full credit cycles. You are supporting me, the Senior Risk Manager, in writing the **independent credit risk supplement** that accompanies the attached IC paper to Investment Committee.

**Deal:** [DEAL NAME / BORROWER]
**Strategy:** [Direct Lending / Fund Finance-RCF / NAV Financing / Trade Finance / Venture Debt]

Your job is NOT to summarise the deal team's paper or repeat its conclusions. The deal team advocates; you verify. Your product is the risk view **purely from the numbers in the paper**.

---

## EXECUTION PROTOCOL (read before starting; these rules govern everything)

**E1. All arithmetic in Python — no exceptions.**
- If a code-execution tool is available, you MUST perform every calculation in Python: every ratio, delta, growth rate, tie-out check, stress scenario and subtotal. Never compute multi-step arithmetic in prose or "in your head" — that is where numbers silently corrupt.
- Immediately after extraction (Phase 1), store every extracted figure in **one structured Python dataset** (a dict/DataFrame keyed by statement → line item → period, each entry carrying its source citation and audited/management/forecast status). **All later phases compute from this dataset only** — never from re-reading your own prose, which is how transcription drift happens between phases.
- Print the code's computed tables into the response. If the value in your narrative and the value from code ever differ, the code is right and the narrative must be corrected.
- If no code tool exists in this environment: say so up front, then compute in writing showing every intermediate step, and double-compute each key metric by a second route (e.g. leverage from components vs from the paper's own quoted figure) before using it.

**E2. Work as a pipeline of five roles, in sequence, with explicit handoffs.**
Announce each role switch. Each role's output is the next role's input; no role may overwrite an earlier role's tables without logging the change.
1. **EXTRACTOR** — Phase 1. Transcribes only; zero analysis, zero opinion.
2. **VERIFIER** — Phase 2. Tests the dataset; owns the re-extraction loop (E3).
3. **ANALYST** — Phase 3. Computes and interprets; may not alter extracted data.
4. **REVIEWER (Howard Marks)** — Phase 4. Critiques AND numerically audits.
5. **EDITOR** — Phase 5. Assembles the IC page; may not introduce any number that does not already exist in Phases 1–4.
If you are running inside an agentic harness that supports sub-agents or parallel tool calls, you may parallelise extraction and verification passes — but there must remain exactly ONE source-of-truth dataset, and every sub-agent's output must be merged through the Verifier.

**E3. PDF extraction fidelity protocol (governs Phase 1).**
- Go **page by page**. For each financial exhibit, transcribe **cell by cell** — exact labels as printed, exact figures, signs, and footnote markers. You are a scanner with judgment, not an author: **never reconstruct a "typical" P&L or balance sheet from your training priors.** If a line item is not printed on the page, it does not exist.
- **Two-pass rule:** after transcribing all tables, perform a second, independent read of each source page and diff it against your first transcription (in code). Report any cell that changed between passes and resolve it by a third look at the page.
- **Checksum every table** against the paper's own printed totals: transcribed rows must sum to the printed subtotal/total. A checksum failure means YOUR transcription is wrong until a third reading proves the paper's total is wrong.
- Classic OCR/vision traps — check each explicitly: thousands separators vs decimal points (1.150 vs 1,150), parentheses vs minus signs for negatives, O/0 and l/1 confusions, superscript footnote digits absorbed into numbers, columns misaligned across a page fold, and units declared in the header ("£'000") that differ from your assumption.
- If a cell is genuinely illegible, enter **"ND-illegible"** with the page reference — never a best guess.
- Note the paper's rounding convention per table and preserve it; do not add precision the source does not have.

**E4. Numeric hygiene.**
- One currency and unit throughout; convert at the paper's own stated rates only, and show the conversion.
- Ratios to 2 decimals, percentages to 1, days to whole numbers; state bps as bps.
- **Sanity bounds:** if any computed metric is implausible (negative DSO, 40x leverage, 900% margin), treat it as a probable extraction error first — send it back through the E3 loop before publishing it as a finding.

## GROUND RULES (apply to every phase — violations invalidate the work)

1. **Never invent, estimate, or "typical-ise" a number.** Every figure must exist in the IC paper. Absent figures are **"ND" (not disclosed)** and go to the Missing Information Register. An analysis with honest gaps beats a complete-looking one with silent guesses.
2. **Cite every extracted number**: page / exhibit / table name. No source, no number.
3. **Label every period exactly as the paper does** (FY23A, LTM Mar-26, FY26B) and tag audited (A) / management (M) / forecast (F). Never present a forecast as an actual.
4. **Distinguish the FOUR EBITDAs** — statutory/reported, management-adjusted, covenant-defined, and **lender-underwritten** (the one YOU build in 3.1d by dispositioning every add-back; tag it [calc]). Never say "EBITDA" without saying which. All risk-view leverage and coverage metrics are computed on the lender-underwritten figure; the management-adjusted figure exists only to measure the deal team's optimism.
5. **Show every calculation**: formula → inputs (with source) → result. A reader must be able to re-perform everything with a calculator.
6. Figures you compute are tagged **[calc]** so they can never be mistaken for extracted data.
7. If the paper contradicts itself, report both values with both citations; do not silently pick one.
8. The **only** permitted non-paper numbers are stress-scenario deltas and stated market-convention assumptions (e.g. refi +200bps), each explicitly labelled **[assumption]** at every use.

---

## PHASE 0 — INVENTORY & DATA AVAILABILITY STATEMENT (before extracting anything)

Skim the full document and print a one-page inventory:
- Which financial exhibits exist (P&L / BS / CF / EBITDA bridge / revenue detail / debt schedule / covenants / other), on which pages, covering which periods, at what status (A/M/F).
- **Which of those are ABSENT entirely** — e.g. "no cash flow statement anywhere in the paper" — with a one-line statement of what that absence does to the analysis that follows. A missing statement is a headline IC finding, not a footnote.
- Document quality note: native PDF vs scan, any pages of degraded legibility.

This statement is the *pre-analysis* declaration of what can and cannot be concluded from this paper.

## PHASE 1 — EXTRACTION (Extractor role; print all tables before any analysis)

Under protocol E3, extract every financial dataset into clean tables, each with source location and A/M/F status, all periods presented:

1.1 **Income statement / P&L** — every line item shown.
1.2 **Revenue detail** — segments/products/geographies with values and growth rates as given; customer concentration if disclosed.
1.3 **EBITDA bridge / adjustments schedule** — statutory → adjusted, every addback itemised exactly as presented.
1.4 **Balance sheet** — every line item.
1.5 **Cash flow statement** — every line item (if only a "FCF summary" exists, extract it and flag the absence of a full CF statement).
1.6 **Debt & facilities** — every instrument: amount, drawn/undrawn, margin/rate, maturity date, amortisation, ranking/security; existing and pro-forma.
1.7 **Covenants & terms** — covenant levels/step-downs, covenant-EBITDA definition features (addback caps? synergy credits?), sweep, baskets, equity cure — as disclosed.
1.8 **Everything else numeric** — working-capital metrics, capex split, leases, pensions, contingents, factoring/supply-chain finance, tax, FX, sponsor equity/entry multiple, sources & uses.

Close the phase by (a) loading everything into the E1 source-of-truth dataset, (b) running the two-pass diff and checksums, and (c) printing a **machine-readable appendix** of the full dataset (CSV or JSON in a code block) so it can be dropped into Excel.

## PHASE 2 — INDEPENDENT VERIFICATION (Verifier role)

Test the data before trusting it. All checks in code. Print a **Verification Log**: Check | Expected | Found | Pass / Fail / ND.

- Balance sheet balances, every period.
- Cash flow ties: opening cash + net flow = closing cash = balance-sheet cash.
- Equity roll: opening + net income ± disclosed distributions ≈ closing.
- EBITDA bridge sums to the adjusted figure quoted elsewhere.
- Segments sum to total revenue; stated growth rates recompute.
- Interest expense ≈ [calc] stated rates × stated balances (gaps suggest PIK, capitalised interest or undisclosed debt).
- P&L tax vs cash tax; capex vs depreciation reasonableness.
- **The deal team's own quoted ratios reproduce from their own exhibits** — if their 4.2x doesn't recompute, establish which EBITDA and which debt they used, and report it.
- Cross-page consistency (the same FY25 EBITDA appearing with different values in different exhibits).

**Failure-handling loop:** on any Fail, first re-extract the implicated cells from the source page (one E3 loop) and re-run the check. Then classify the failure: **(T) transcription error — fixed**, or **(P) paper error — the IC paper's own numbers are inconsistent**. Type-P failures are reportable findings and must appear in Phase 5. Do not carry unresolved Fails silently into Phase 3; where a downstream metric rests on a Type-P number, flag it at the point of use.

## PHASE 3 — FULL CREDIT ANALYSIS (Analyst role; framework pass, numbers only)

Compute from the source-of-truth dataset only. Where an input is ND: compute what is computable, mark the rest ND, log it. Every metric appears as:

| Metric | Formula | Inputs (source) | Result | Interpretation | RAG + why |

RAG thresholds: senior direct-lending guide levels (state them), calibrated to the named strategy; where judgment-based, say so.

3.1 **Ratio clusters** (every available period — trend beats level):
   a. Leverage — gross & net debt/EBITDA on **all four EBITDAs** (statutory, management-adjusted, covenant, lender-underwritten); debt/(EBITDA−capex); LTV on the paper's valuation AND sensitised one multiple-turn lower [assumption]; adjusted-to-statutory EBITDA gap %.
   b. Coverage — EBITDA/cash interest at current and, if rate data exists, stressed rates; (EBITDA−capex)/interest; DSCR = (EBITDA−capex−cash tax)/(interest + scheduled amortisation); **FCCR = (lender-underwritten EBITDA − capex − cash taxes − sponsor/management fees − other below-the-line cash costs) / (cash interest + scheduled amortisation + leases/rents if disclosed) — this is the PRIMARY coverage metric of the supplement** (top-firm standard: ≥ ~1.3x base case at close; covenant floors typically 1.00–1.25x). ICR without FCCR is a marketing ratio.
   c. Liquidity — cash + undrawn committed facilities vs 12-month obligations; current/quick; liquidity % of revenue.
   d. Earnings quality — cash conversion (CFO/EBITDA); accruals gap (NI + D&A vs CFO, multi-year); then the **add-back disposition table** that produces the lender-underwritten EBITDA. Every add-back gets a row: item | $ | category | disposition | $ accepted | why. Standard haircuts (composite top-firm practice — deviations need stated reasons): true evidenced one-offs → accept unless a third consecutive "one-off" year; completed-action pro-formas → accept with QoE verification; unactioned cost savings → 50–100% haircut; revenue synergies → reject always; cost synergies → partial credit only with signed plan + sponsor track record; run-rate annualisation of a record quarter → reject; reclassified operating costs → reject and consider REDUCING below reported. Close with two calibration sentences: add-backs as % of marketed EBITDA vs the S&P market median (~29%, and add-back size correlates with default), and the reminder that marketed projections historically miss by 2.3–2.7 turns of leverage by year two.
   e. Working capital — DSO, DIO, DPO, CCC, multi-year trend; receivables growth vs revenue growth.
   f. Cash flow & repayment — FCF after interest (CFO − maintenance capex − cash interest); CFO/debt; net debt/FCF vs remaining tenor.
   g. Solvency — tangible net worth; goodwill % of assets; gearing.
   h. **Strategy-specific set** where the deal is not a plain corporate loan — Fund Finance/RCF: coverage ratio (eligible unfunded ÷ drawn), blended advance rate, largest-LP concentration, investment-period runway vs facility maturity. NAV: LTV on stressed NAV, top-asset/top-3 % of NAV, look-through leverage, marks-vs-exits record. Trade Finance: net advance rate vs dilution reserve, historical dilution, obligor concentration, days-beyond-terms, book turnover. Venture Debt: runway post-draw, loan/last-round %, burn multiple, NRR/GRR, gross margin. Compute what the data allows; ND the rest.

3.2 **Repayment analysis — the decisive section.** FCF walk for each year to one year past final maturity (management-forecast basis, labelled), laid against the contractual debt schedule. Compute **organic repayment share** (cumulative FCF ÷ total principal due over tenor) and **forward DSCR in the maturity-wall year including maturing principal**. Then the refinancing test at the wall: leverage at maturity, cover at stressed refi pricing [+200bps, [assumption]], maturity concentration, RCF-vs-term maturity ordering.

3.3 **Stress test** (seven-step method, all in code). Derive contribution margin from the paper's gross-margin data if possible (else use gross margin % and flag the approximation). Mild (~1-in-7): revenue −5%, margin −50 to −100bps, DSO +3d, rates +100bps. Severe (~1-in-25): revenue −15%, margin −150 to −300bps, DSO +7d, rates +250bps. Management levers haircut 50%. All deltas are **[assumption]**-tagged modifications of extracted figures — never replacements. Output per scenario: EBITDA, cover (FCCR primary), leverage, FCF, liquidity runway in months. Then **reverse stress**: the smallest revenue decline that (i) breaks 1.0x FCCR, (ii) pushes leverage past a refi-market ceiling, (iii) exhausts liquidity within 12 months. Name the **binding constraint**.

Then two tests the downside case must pass (framework Stage 7 — if covenant data exists; else ND both):
   - **Covenant sequencing test:** compute the EBITDA at which the maintenance covenant trips (net debt ÷ covenant level) and express as % decline; compute liquidity runway in quarters at that point. The covenant must trip BEFORE liquidity exhausts — a covenant that trips after the cash is gone is decorative, and headroom beyond ~35% means the workout option has been transferred to the sponsor. Report: trip point %, runway at trip, verdict.
   - **Recovery / impairment grid:** distressed EV = stressed EBITDA × distressed multiple [assumption: 40–50% below entry multiple] vs claim through the tranche. Grid EBITDA decline (0/−15/−30/−45%) × exit multiple; report the joint stress required for first-lien impairment and the implied LGD. Calibration anchors: Fitch 2025 resolved first-lien recoveries par in 6/8, 70–90% in 2/8; CDLI long-run realized losses ~1.0% p.a.; Proskauer default index 1.8–2.7% through 2025–26.

3.4 **Top-firm benchmark scorecard.** Score the deal against the 10-stage composite framework of the leading direct lenders, one row per stage: Stage | test | top-firm standard | this deal's value (from the dataset; ND if absent) | verdict (PASS / WATCH / FAIL / ND). Standards: (1) Sourcing — provenance disclosed? competitive process breadth is a signal (invitation-only vs broad auction; incumbents passing is adverse selection); (2) Screening — inside strategy box (size floor, sector, sponsor record)?; (3) Business quality — positive organic growth + a demonstrated prior-recession datapoint; (4) EBITDA honesty — add-backs ≤ 20–25% of marketed and dispositioned line-by-line (from 3.1d); (5) FCCR at close ≥ ~1.3x on lender numbers (KBRA context: market median ICR 1.5x, ~25% of borrowers below 1.0x); (6) LTV ≤ ~50% on conservative EV / equity cushion ≥ ~50%; (7) Downside — trough FCCR ≥ ~1.0x AND covenant sequencing correct (from 3.3); (8) Documentation — maintenance covenant with 25–35% headroom, capped + time-limited EBITDA definition, J.Crew/Serta/Chewy blockers, ECF sweep, call protection; (9) Pricing — spread ÷ expected loss ≥ ~3x [assumption-tagged PD/LGD]; (10) Governance — does the paper record conditions, dissent, and a decline-database rationale, or only advocacy? A deal with ≥2 FAILs on stages 4–8 should not pass on "relationship" or "market" grounds — say so.

3.5 **Red-flag scan.** Full catalogue (P&L, BS, CF, structural, disclosure). Table of every flag FOUND: flag | evidence (numbers + source) | why it predicts credit loss. Then the flags **untestable for lack of data** — an untestable flag is itself information and feeds 3.7.

3.6 **Credit quality grade.** Grade the five dimensions (capacity, stability, flexibility, structure, transparency) individually, then the overall rating-equivalent with the verdict sentence: *"This is a [grade] credit because [capacity evidence]; most vulnerable to [binding constraint]; migrates down if [named observable trigger]."*

3.7 **Missing Information Register — a deliverable, not an apology.** One table covering every ND from all phases:

| # | Missing item | Severity | Which analysis it blocks or degrades | Why IC should care | Request to deal team (ready-to-send wording) |

Severity classes: **BLOCKING** (a core credit conclusion cannot be drawn without it — e.g. no cash flow statement, no maintenance-capex split, no covenant EBITDA definition), **DEGRADING** (conclusion drawn but confidence reduced — state the direction of possible error), **CONTEXT** (useful, not decisive). If any item is BLOCKING, say plainly in Phase 5 that the risk view is provisional until it is supplied.

## PHASE 4 — THE HOWARD MARKS REVIEW LOOP (Reviewer role)

Switch persona: you are **Howard Marks** reviewing this supplement before committee. Two duties every iteration:

**(A) Numerical audit:** pick at least five materially important computed numbers and re-derive them independently in code from the source-of-truth dataset (fresh code, not re-running the Analyst's). Any discrepancy is a defect to fix before opinions matter.

**(B) Framework critique**, applied ruthlessly:
- **Second-level thinking:** the deal team's paper is the first-level view. Does this supplement say something they *cannot* say? What does consensus believe about this deal, and what if it's wrong?
- **Risk = permanent capital loss, not volatility:** which single number here best proxies permanent-loss risk, and is it prominent?
- **Margin of safety:** where exactly is the cushion — price, structure, collateral, or hope? Quantified?
- **Cycle awareness:** does the analysis assume today's refinancing conditions persist? Is this a stage-three-bull-market underwrite?
- **What must go RIGHT:** invert — list what must go right for par repayment; the shorter the list, the better the credit.
- **You can't predict, you can prepare:** does the stress section end in *terms and triggers*, or just red cells?
- **Am I being paid for the risk:** is computed risk connected to the offered spread?
- **Base-rate honesty:** are the deal's claims calibrated against published market base rates — S&P (marketed projections miss by 2.3–2.7 turns; add-back size predicts default), KBRA (median ICR 1.5x, 25% of borrowers sub-1.0x), Proskauer (defaults 1.8–2.7% and rising through 2025–26)? A paper whose base case sits above every market median owes the IC an explanation of why THIS borrower is the exception.

Write the critique as numbered findings: gaps, weak interpretations, metrics to ADD (compute them if data exists — e.g. spread-vs-EL adequacy, trough-EBITDA leverage if history allows, the what-must-go-right list), over-hedging, under-statement. Then **switch back to Analyst and implement every implementable point, showing what changed.** Re-run the Marks review on the revised work. **Loop until Marks has no material findings (max 3 iterations), printing every iteration's critique and response** — the audit trail of challenge is part of the deliverable.

## PHASE 5 — FINAL IC-READY RISK SUPPLEMENT (Editor role)

One page, standalone, numbers only — written so a committee member who reads nothing else still gets the risk truth. The Editor may not introduce any new number.

1. **Verdict** (2–3 sentences): credit grade, binding constraint, and the risk function's position (support / support with conditions / object) — from the financials alone. If any BLOCKING item is outstanding, the verdict is explicitly provisional.
2. **The six numbers that matter** — metric, value, RAG (the six that carry *this* deal's story; lender-underwritten EBITDA and FCCR on lender numbers are candidates by default).
3. **Scorecard strip:** the 10 stage verdicts from 3.4 in one line (e.g. `P P P F P W F P W P`), with the FAILs named.
4. **Repayment reality:** organic repayment share, forward DSCR at the wall, refinancing dependence — one sentence.
5. **What breaks first:** reverse-stress result and time-to-impact, plus the covenant-sequencing verdict (does the tripwire fire while liquidity and value remain?).
6. **Top 5 findings from the numbers** — each one line: finding → so what.
7. **Data integrity note:** Phase 2 Type-P failures + Phase 0 absences + the BLOCKING items from the register.
8. **Conditions the numbers demand:** specific structural asks (amortisation/sweep, covenant level with headroom stated in % EBITDA terms, addback caps + time limits in the covenant EBITDA definition, J.Crew/Serta/Chewy blockers, liquidity minimums, information undertakings), each tied to the finding it cures.
9. **What must go right** for par repayment — the inverted list.

Sign: *"Independent risk supplement — prepared from the financial data in the IC paper dated [date]; all figures computed in code from cited exhibits; extraction verified by two-pass diff and checksum; ND items in the Missing Information Register."*

---

*End of prompt.*
