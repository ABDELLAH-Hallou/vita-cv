"""Keep model commentary qualitative while retaining candidate achievement metrics."""

import re

# Split prose into clauses without splitting English or French decimal numbers.
SENTENCES = re.compile(r"(?<!\d)[.!?](?:\s+|$)|(?<=\d)[.!?](?!\d)(?:\s+|$)|[;\n]+")
CLAUSES = re.compile(
    r",(?!\d)\s*|"
    r"\s+(?:and|but|while|whereas|due to|thanks to|backed by|supported by|including|"
    r"with|reflecting|driven by|despite|mais|tandis que|grâce à|et)\s+",
    re.IGNORECASE,
)
NUMBER = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|percent(?:age)?|per\s+cent|pour\s+cent|/\s*100)?", re.IGNORECASE)
ASSESSMENT = re.compile(
    r"\b(?:score|scores|fit|match|matching|coverage|alignment|suitability|compatibility|"
    r"adéquation|compatibilité|couverture|correspondance|note\s+globale|taux\s+d'adéquation|"
    r"overall\s+(?:assessment|evaluation|rating)|(?:CV|resume|candidate)\s+(?:earns|achieves|gets|receives))\b",
    re.IGNORECASE,
)
COMPARISON = re.compile(
    r"\b(?:(?:no|missing|without)\s+(?:a\s+|the\s+)?baseline|"
    r"baseline(?=[^.!?;\n]*(?:\b(?:available|unavailable|missing|provided|absent|exists?|present|comparison)\b|:\s*\d))|"
    r"initial\s+(?:evaluation|assessment|analysis)|"
    r"(?:previous|prior|original)\s+(?:evaluation|assessment|analysis|score)|"
    r"(?:before|after)[- ]adaptation\s+score|comparison|"
    r"(?:évaluation|analyse)\s+initiale|comparaison|score\s+initial|"
    r"(?:tailor(?:ing|ed)?|adaptation|(?:CV|resume)\s+edits?|rewrit(?:ing|e))"
    r"(?=[^.!?;\n]*\b(?:points?|score|match|fit|coverage|gain)\b))\b",
    re.IGNORECASE,
)
# Distance to an achievement term distinguishes e.g. "40% cost reduction"
# from "44.50% overall fit", even when both appear in the same summary.
ACHIEVEMENT = re.compile(
    r"\b(?:costs?|reduction|reduced|reducing|revenue|latency|throughput|accuracy|"
    r"sales|retention|conversion|productivity|efficiency|savings|saved|uptime|"
    r"years?|months?|coûts?|réduction|réduit|latence|précision|économies|chiffre\s+d'affaires)\b",
    re.IGNORECASE,
)


def _distance(number: re.Match, label: re.Match) -> int:
    return max(label.start() - number.end(), number.start() - label.end(), 0)


def _assessment_claim(clause: str) -> bool:
    if COMPARISON.search(clause):
        return True
    assessments = list(ASSESSMENT.finditer(clause))
    achievements = list(ACHIEVEMENT.finditer(clause))
    return bool(assessments) and any(
        min((_distance(number, label) for label in assessments), default=float("inf"))
        < min((_distance(number, label) for label in achievements), default=float("inf"))
        for number in NUMBER.finditer(clause)
    )


def qualitative_text(text: str) -> str:
    """Discard assessment/comparison clauses, rather than all percentages.

    Numeric achievement clauses remain unchanged. Criteria and source evidence
    are not passed through this prose filter. Safe prose keeps its punctuation
    and conjunctions; split mixed sentences only when removing a claim.
    """
    sentences = [sentence.strip(" \t\r\n.!?;") for sentence in SENTENCES.split(text)]
    if not any(_assessment_claim(sentence) for sentence in sentences):
        return text
    kept = []
    for sentence in sentences:
        clauses = CLAUSES.split(sentence) if _assessment_claim(sentence) else [sentence]
        kept.extend(clause.strip() for clause in clauses if clause.strip() and not _assessment_claim(clause))
    return ". ".join(kept) + ("." if kept else "")
