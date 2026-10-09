# Lease Lens: notes for Claude Code

Ben is building this prototype to support a job application. It reads public commercial leases from SEC EDGAR, extracts 12 key terms per lease with Claude, verifies every citation in code, routes anything unverified to a human review queue, and measures with a hand-labelled eval whether that queue catches the errors. Ben follows RUNBOOK.md step by step; use it to understand where he is.

## Rules

- **Never write gold labels.** `data/labels.csv` must contain only answers Ben recorded himself. Don't fill, edit, guess or "fix" labels, even if asked to speed things up; explain that a model labelling its own test set makes the eval meaningless. You may check the file's format.
- **Never edit `human_verdict` in `data/out/judgements.csv` without Ben agreeing each verdict.** Suggest, then wait.
- **Don't read, print or echo `.env`.** It holds Ben's API key. Scripts load it themselves.
- **Don't change `leases.csv`, the field list in `src/fields.py`, or the extraction prompt in `src/extract.py` without asking.** Changing them mid-way invalidates earlier results.
- Use the virtual environment in `.venv` for every Python command.
- Run `extract.py` on a couple of leases before all of them, and report token use.
- Explain results in plain English. Ben is a product manager, not an ML engineer.

## Layout

- `src/fetch.py`: download leases, convert to text (`data/text/`)
- `src/extract.py`: model call, citation verification, confidence adjustment (`data/out/<id>.json`)
- `src/score.py`: labels template, scoring, review-queue metrics (`data/out/eval.json`, `judgements.csv`)
- `src/build_viewer.py` + `viewer/template.html`: the single-page viewer (`build/lease-lens.html`)
- `tests/`: synthetic leases with planted errors for offline testing (`--mock`)
