"""Field definitions and value normalisers shared by extraction and scoring.

Each field has a type that decides how a model answer is compared with a
hand-labelled gold answer. Keeping that comparison explicit is the point:
"accuracy" means nothing until you've decided what counts as the same answer.
"""
import re
from datetime import datetime
from difflib import SequenceMatcher

FIELDS = [
    {"key": "landlord", "label": "Landlord", "type": "party",
     "hint": "Full legal name of the landlord entity as stated in the lease."},
    {"key": "tenant", "label": "Tenant", "type": "party",
     "hint": "Full legal name of the tenant entity as stated in the lease (may differ from the filing company's current name)."},
    {"key": "premises_address", "label": "Premises address", "type": "text",
     "hint": "Street address of the leased premises, including suite/floor if given."},
    {"key": "rentable_area_sqft", "label": "Rentable area (sq ft)", "type": "number",
     "hint": "Rentable square footage of the premises at lease start. Number only."},
    {"key": "commencement_date", "label": "Commencement date", "type": "date",
     "hint": "Date the lease term commences. If it is defined by a condition rather than a fixed date, return the condition text and mark confidence accordingly."},
    {"key": "expiration_date", "label": "Expiration date", "type": "date",
     "hint": "Date the initial term ends (excluding renewal options). If only a term length is given, state that."},
    {"key": "initial_monthly_base_rent", "label": "Initial monthly base rent (USD)", "type": "money",
     "hint": "Monthly base rent for the first rent period, in USD. If only annual is given, divide by 12 and say so in the note."},
    {"key": "rent_escalation", "label": "Rent escalation", "type": "text",
     "hint": "How base rent changes over the term (e.g. fixed % per year, stepped schedule, CPI)."},
    {"key": "renewal_option", "label": "Renewal / extension option", "type": "text",
     "hint": "Number and length of renewal or extension options, if any. 'None' if the lease grants none."},
    {"key": "renewal_notice_months", "label": "Renewal notice period (months)", "type": "number",
     "hint": "How many months before expiry the tenant must give notice to exercise a renewal option. 'None' if there is no renewal option."},
    {"key": "early_termination", "label": "Tenant early termination right", "type": "text",
     "hint": "Any right for the tenant to end the lease before expiry: when it can be exercised, notice required and any fee. 'None' if the lease grants none."},
    {"key": "security_deposit", "label": "Security deposit (USD)", "type": "money",
     "hint": "Amount of the cash security deposit or letter of credit required at signing, in USD."},
]

# How each field's normalised value should be expressed (used by the portfolio brief).
NORMALISED = {"date": "ISO date YYYY-MM-DD, or null if the date is conditional or not stated",
              "money": "plain number in USD, no symbols or commas",
              "number": "plain number, no units or commas",
              "party": "the name only", "text": "short summary"}
FIELD_KEYS = [f["key"] for f in FIELDS]
FIELD_BY_KEY = {f["key"]: f for f in FIELDS}

NOT_FOUND = {"", "none", "n/a", "na", "not found", "not stated", "null", "-"}

DATE_FORMATS = ["%Y-%m-%d", "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y",
                "%m/%d/%Y", "%m/%d/%y", "%d %B %Y"]


def is_blank(v):
    """Not found, including answers that open with a stated absence:
    "None. The lease grants no ...", "No voluntary early termination right; ..."."""
    if v is None:
        return True
    s = str(v).strip().lower()
    return s in NOT_FOUND or bool(re.match(r"(none|no)\b", s))


def parse_date(v):
    s = re.sub(r"(\d)(st|nd|rd|th)", r"\1", str(v).strip())
    s = re.sub(r"\s+", " ", s)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_number(v):
    s = str(v).lower().replace(",", "")
    m = re.search(r"-?\d+(\.\d+)?", s)
    if not m:
        return None
    n = float(m.group())
    if re.search(r"\d\s*(k|thousand)\b", s):
        n *= 1000
    return n


WORD_NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10, "single": 1}


def numbers_in(v):
    """Set of numbers mentioned in free text, including number words ("two five-year options")."""
    s = str(v).lower().replace(",", "")
    nums = {float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)}
    nums |= {float(WORD_NUMS[w]) for w in re.findall(r"[a-z]+", s) if w in WORD_NUMS}
    return nums


def norm_text(v):
    s = str(v).lower()
    s = re.sub(r"[\.,;:'\"()]", " ", s)
    s = re.sub(r"\b(inc|incorporated|llc|l l c|ltd|lp|l p|corp|corporation|co|company|the)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def compare(field_key, predicted, gold):
    """Return (verdict, detail). verdict is one of:
    correct, partial, wrong, missed (gold has a value, model said none),
    false_positive (gold is none, model gave a value), both_blank.
    """
    ftype = FIELD_BY_KEY[field_key]["type"]
    pb, gb = is_blank(predicted), is_blank(gold)
    if pb and gb:
        return "both_blank", ""
    if pb:
        return "missed", "model returned nothing"
    if gb:
        return "false_positive", "gold says not present"

    if ftype == "date":
        pd, gd = parse_date(predicted), parse_date(gold)
        if pd and gd:
            return ("correct", "") if pd == gd else ("wrong", f"{pd} vs {gd}")
        # fall through to text comparison for conditional dates
    if ftype in ("number", "money"):
        pn, gn = parse_number(predicted), parse_number(gold)
        if pn is not None and gn is not None:
            if gn == 0:
                return ("correct", "") if pn == 0 else ("wrong", f"{pn} vs {gn}")
            rel = abs(pn - gn) / abs(gn)
            if rel < 0.005:
                return "correct", ""
            if rel < 0.05 and ftype == "number":  # areas are often "approximately"; money must be exact
                return "partial", f"within 5% ({pn} vs {gn})"
            return "wrong", f"{pn} vs {gn}"

    a, b = norm_text(predicted), norm_text(gold)
    if a == b:
        return "correct", ""
    if a and b and (a in b or b in a) and min(len(a), len(b)) > 6:
        # One contains the other. Only "correct" if little is missing: an answer of
        # "April 1, 2021" for a conditional "later of April 1, 2021 or delivery" is incomplete.
        if min(len(a), len(b)) / max(len(a), len(b)) >= 0.6:
            return "correct", "contained"
        return "partial", "one answer is a fragment of the other"
    ratio = SequenceMatcher(None, a, b).ratio()
    na, nb = numbers_in(predicted), numbers_in(gold)
    if na or nb:
        if na != nb:
            return "wrong", f"numbers differ {sorted(na)} vs {sorted(nb)}"
        if ratio >= 0.4:
            return "correct", f"numbers match, fuzzy {ratio:.2f}"
    if ratio >= 0.85:
        return "correct", f"fuzzy {ratio:.2f}"
    if ratio >= 0.6:
        return "partial", f"fuzzy {ratio:.2f}"
    return "wrong", f"fuzzy {ratio:.2f}"
