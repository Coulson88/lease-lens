# Lease Lens

Turns a stack of real US leases into a due-diligence brief. Every number traces to the clause it came from, anything the system can't vouch for goes to a person first, and an eval measures whether that routing actually catches the mistakes.

Built as a working answer to one question: how do you present AI-extracted insight so a professional trusts it enough to act?

## What it does

1. **Fetch** 20 public leases from SEC EDGAR (companies file material leases as exhibits). Listed in `leases.csv`.
2. **Extract** 12 terms per lease: landlord, tenant, premises, rentable area, commencement, expiration, initial monthly rent, escalation, renewal option, renewal notice period, tenant early termination right, security deposit. For each one the model returns a value, a normalised value for calculation, a verbatim quote, a confidence level and a note.
3. **Verify** every citation in code. The quote is searched for in the lease. If it isn't there, the answer is flagged unverified and confidence is capped at low. If the value doesn't appear in its own quote (a calculation, or a misreading), high confidence is cut to medium. The model never gets to vouch for itself.
4. **Label** the correct answers yourself, blind to the model's output.
5. **Brief** (opening view): one question first, "what needs a person before this goes to committee?", as a review queue ranked by rent at stake. Beside it, portfolio findings (rent roll, early termination exposure, renewal options, rent per sq ft, security held, rent-weighted term), each split into verified and waiting-for-review. Confirming or correcting a term in the queue updates the brief.
6. **Score**: the product metrics first. Review burden (share of terms sent to a person), error capture (share of mistakes that landed in the queue), accuracy of what passed unchecked, and the errors that escaped. Then raw accuracy per term, and whether confidence predicts accuracy.
7. **Lease desk**: the abstract beside the source lease, cited clauses highlighted, confirm / correct / reject on each term.

## Run it

**Step-by-step instructions, including what to hand to Claude Code and what to do yourself, are in RUNBOOK.md.** The commands below are the short version.

```bash
pip install -r requirements.txt
cp .env.example .env    # then fill in SEC_USER_AGENT and ANTHROPIC_API_KEY

python src/fetch.py                  # download and clean the 20 leases (data/text/)
python src/extract.py                # extract + verify (data/out/<lease>.json)
python src/build_viewer.py           # build/lease-lens.html, open it in a browser
```

Labelling and scoring:

```bash
python src/score.py --init-labels    # blank data/labels.csv
# Label in the viewer's Label tab (model answers hidden), press
# "Show labels.csv", paste into data/labels.csv. Or fill the CSV directly.
python src/score.py                  # prints the scorecard, writes data/out/eval.json
python src/build_viewer.py           # rebuild so the Eval tab shows results
```

Free-text fields (escalation, renewal) are scored with rough automatic rules. Open `data/out/judgements.csv`, fill `human_verdict` where you disagree, and re-run `score.py`. Your verdicts are kept as long as the model's answer is unchanged.

Model is set by `LEASE_MODEL` (defaults to `claude-sonnet-5-5`). One lease is roughly 20 to 40k input tokens.

Offline test (no API key; three synthetic leases with scripted answers containing a fabricated quote, a miscounted option, an invented deposit and a rent read from the wrong row):

```bash
python src/extract.py --mock --force && python src/score.py --mock && python src/build_viewer.py --mock
```

## Labelling rules

- Label a lease before looking at the model's answer for it. Seeing the answer first anchors you and inflates the score.
- Write the operative term. If an amendment or a later clause overrides an earlier one, the later one wins.
- `none` means the lease genuinely doesn't contain it. A blank cell means "not labelled yet" and is skipped.
- Conditional dates ("later of April 1 or substantial completion") are labelled as the condition, not just the date.
- Monthly rent: if the lease gives annual rent only, divide by 12.
- Keep notes on anything you weren't sure about. Those are the interesting cases.

## Files

| Path | What |
|---|---|
| `leases.csv` | The 20 EDGAR leases: id, company, description, filing date, URL |
| `src/fields.py` | Field definitions and the rules for when two answers count as the same |
| `src/fetch.py` | Download and HTML-to-text |
| `src/extract.py` | Claude call (forced tool use), citation location, confidence adjustment |
| `src/score.py` | Labels template, scoring, judgements and eval report |
| `src/build_viewer.py` | Bundles everything into one HTML page |
| `viewer/template.html` | Review, Label and Eval views |
| `tests/` | Synthetic lease and scripted response for offline testing |
