# Runbook: from zip file to finished prototype

Every step says who does it. **You** means you, by hand. **Claude Code** means you paste the prompt into Claude Code in VS Code and let it run. Claude Code reads `CLAUDE.md` in this folder automatically, so it already knows the project and its rules.

Total time: about 30 minutes of setup and running, then 3 to 4 hours of labelling.

---

## Before you start (You, 10 minutes)

You need:
- **VS Code** with the **Claude Code** extension, signed in.
- **Python 3.10 or newer.** Check by typing `python3 --version` in the VS Code terminal.
- **An Anthropic API key** from console.anthropic.com (API keys page). This is separate from your Claude subscription. Add a few dollars of credit; the full run of 20 leases should cost a few dollars at most.

Then:
1. Unzip `lease-lens.zip` somewhere sensible, for example `Documents/lease-lens`.
2. In VS Code: **File > Open Folder** and choose the `lease-lens` folder.
3. In the file list, duplicate `.env.example`, rename the copy to `.env`, and fill in both lines:
   - `SEC_USER_AGENT="Ben Coulson your@email.com"` (the SEC asks automated downloads to identify themselves)
   - `ANTHROPIC_API_KEY=` followed by your key

   Do this yourself in the file. Never paste your API key into the Claude Code chat.

---

## Step 1: Set up and run the offline test (Claude Code, 2 minutes)

Paste:

> Set up this project: create a Python virtual environment in .venv, install requirements.txt, then run the offline test from the README (extract, score and build_viewer with --mock). Tell me whether it passed and what the scorer printed. Don't touch .env.

**Checkpoint:** it reports that the test passed, and the scorer shows 3 leases scored. If it fails, let Claude Code fix it, then continue.

## Step 2: Download the 20 leases (Claude Code, 2 minutes)

> Run src/fetch.py using the venv. Report how many leases downloaded and the size of each text file. If any failed, tell me which and why, but don't change leases.csv without asking me.

**Checkpoint:** 20 leases fetched, each roughly 30k to 200k characters. One or two failures are fine; tell me which ones and I'll find replacements.

## Step 3: Trial extraction on two leases (Claude Code, 2 minutes)

> Run src/extract.py on just two leases: --docs zltq crm. Then show me, for each, the value, confidence, citation status and any flag for every term, as a table. Tell me the time and input tokens per lease.

**Checkpoint:** answers look sensible, and most citations show as `exact` or `whitespace`. This is the cheap test before spending money on all 20. If something looks badly wrong (every citation failing, empty answers), stop and send me the output.

## Step 4: Extract all 20 (Claude Code, 5 to 10 minutes)

> Run src/extract.py for all leases. When it's done, give me a summary: leases processed, total input tokens, average time per lease, and how many terms ended up flagged for review.

## Step 5: Build the page and look at it (Claude Code, then You)

> Run src/build_viewer.py and open build/lease-lens.html in my browser.

**You:** click through the Review screen for a few minutes. Does the queue make sense? Do the clauses look right? Note anything odd; it's useful material for the write-up.

## Step 6: Label the right answers (You, 3 to 4 hours)

**This step must be you, not Claude Code.** The whole point of the eval is a person checking the system against the leases. If Claude labels the answers, it's the model marking its own homework, and you'd have nothing honest to say about it in the interview.

1. In the open page, go to **Label** (top right). The system's answers are hidden on this screen so they can't steer you.
2. Pick a lease from the list. For each of the 12 terms, read the lease on the right and type the correct answer.
   - Write `none` if the lease genuinely doesn't contain it (for example, no early termination right).
   - For conditional dates, write the condition: "later of April 1, 2021 or substantial completion".
   - For monthly rent where only annual rent is given, divide by 12.
   - Optional: select the clause in the lease and press **Use highlighted text as source**.
3. Do **12 to 15 leases** in total. Quality matters more than quantity, and you can stop and come back: answers are saved in your browser, as long as you reopen the same file in the same browser.
4. Keep a short note of anything you found tricky or ambiguous. These become your interview stories.
5. When you're done, press **Show labels.csv**, copy everything in the box, and paste it into `data/labels.csv` (create the file if it doesn't exist), replacing anything already there.

## Step 7: Score (Claude Code, 2 minutes)

> Run src/score.py and explain the results to me in plain English: the review queue numbers, the errors that got through the queue, and which terms the system found hardest.

## Step 8: Settle the free-text verdicts (You, with Claude Code's help, 20 minutes)

Free-text terms (rent escalation, renewal option, early termination) are judged roughly by the scorer. Claude Code can suggest verdicts, but you decide.

> Open data/out/judgements.csv. For rows where the term is rent_escalation, renewal_option or early_termination and the auto_verdict is partial or wrong, show me the system's answer next to my answer and suggest a verdict. Don't write anything to the file until I've agreed each one.

Then:

> Write the verdicts I agreed into the human_verdict column, re-run src/score.py, and rebuild the viewer.

## Step 9: Send it back (You)

Send me `build/lease-lens.html` and the scorer's printed summary, plus your notes from Step 6. I'll republish the page with your real numbers, then we write the one-page point of view and plan the Loom.

---

## If something goes wrong

| Problem | What to do |
|---|---|
| `python3: command not found` | Install Python from python.org, restart VS Code. |
| SEC download returns 403 | Check `SEC_USER_AGENT` in `.env` has a real name and email. |
| `authentication_error` from Anthropic | Check `ANTHROPIC_API_KEY` in `.env`, and that the account has credit. |
| `model not found` | Add `LEASE_MODEL=` with a current model name to `.env`. Ask Claude Code which models your key can use. |
| Labels disappeared | Open the same `build/lease-lens.html` in the same browser. Different browsers or copies of the file don't share labels. |
| Anything else | Ask Claude Code to diagnose it, or send me the error. |
