"""
Synthetic supplier invoices with simulated processing outcomes.

They are the demo dataset and the risk model's training data. Everything comes
from one seeded random generator, so the files, their outcomes and the model
trained on them are the same on every run.

Each file belongs to one case, picked at random with these weights: valid 65%,
and 7% each for missing transaction ID, missing amount, non-numeric amount,
negative amount and amount above the review limit. Independently, 40% of files
are "sparse" (each optional field - issue date, currency, supplier, payment
account - is left out with probability 1/2), and 20% are wrapped in a
three-level transport envelope.

Outcome rules (column "failed" in outcomes.csv, the model's training label):
- A file that breaks a validation rule or needs manual review always fails:
  it cannot be processed straight through.
- Any other file fails with probability
      2% + 4% per missing optional field + 3% if the amount is 100,000 or more
      + 3% if it is wrapped in an envelope,
  capped at 20%.
"""

import csv
import os
import random
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from xml.dom import minidom

from src.features.extractor import LARGE_AMOUNT
from src.validation.rules import REVIEW_THRESHOLD

DEFAULT_COUNT = 400
DEFAULT_SEED = 42
OUTCOMES_FILE = "outcomes.csv"

UBL_NAMESPACE = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"

CASE_WEIGHTS = {
    "valid": 0.65,
    "missing_id": 0.07,
    "missing_amount": 0.07,
    "bad_amount": 0.07,
    "negative_amount": 0.07,
    "high_value": 0.07,
}
EXPECTED_STATUS = {
    "valid": "VALID",
    "missing_id": "INVALID",
    "missing_amount": "INVALID",
    "bad_amount": "INVALID",
    "negative_amount": "INVALID",
    "high_value": "REQUIRES_REVIEW",
}
OPTIONAL_FIELDS = ("issue_date", "currency", "supplier", "payment_account")

FAILURE_BASE = 0.02
FAILURE_PER_MISSING_OPTIONAL = 0.04
FAILURE_LARGE_AMOUNT = 0.03
FAILURE_ENVELOPE = 0.03
FAILURE_CAP = 0.20

SUPPLIERS = [
    "Acme Corp Global",
    "Bluefin Components",
    "Kestrel Logistics",
    "Meridian Packaging",
    "Orchid Textiles",
    "Summit Steelworks",
]
CURRENCIES = ["USD", "EUR", "GBP", "INR"]
ITEMS = ["Steel fasteners", "Packaging film", "Corrugated boxes", "Copper wire", "Safety gloves"]
BAD_AMOUNTS = ["12,50.00", "1,250.00", "1.250,00", "N/A", "TBD", "USD 300.00", "1O0.00"]


def failure_probability(case: str, missing_optional: int, large_amount: bool, wrapped: bool):
    """Chance that a file fails downstream, per the outcome rules above."""
    if case != "valid":
        return 1.0
    probability = (
        FAILURE_BASE
        + FAILURE_PER_MISSING_OPTIONAL * missing_optional
        + (FAILURE_LARGE_AMOUNT if large_amount else 0.0)
        + (FAILURE_ENVELOPE if wrapped else 0.0)
    )
    return min(probability, FAILURE_CAP)


def _add(parent, tag, text=None, **attrs):
    elem = ET.SubElement(parent, tag, **attrs)
    if text is not None:
        elem.text = text
    return elem


def _normal_amount(rng: random.Random) -> float:
    # Mostly everyday invoices, with a thin tail of large ones below the review limit.
    roll = rng.random()
    if roll < 0.85:
        return round(rng.uniform(50, 20_000), 2)
    if roll < 0.95:
        return round(rng.uniform(20_000, LARGE_AMOUNT), 2)
    return round(rng.uniform(LARGE_AMOUNT, REVIEW_THRESHOLD), 2)


def _make_invoice(rng: random.Random) -> tuple[str, str, int]:
    """Returns (pretty-printed XML, case, failed) for one random invoice."""
    case = rng.choices(list(CASE_WEIGHTS), weights=list(CASE_WEIGHTS.values()))[0]
    sparse = rng.random() < 0.4
    wrapped = rng.random() < 0.2
    keep = {name: not (sparse and rng.random() < 0.5) for name in OPTIONAL_FIELDS}
    currency = rng.choice(CURRENCIES)

    root = ET.Element("StandardBusinessDocument", xmlns=UBL_NAMESPACE)
    header = _add(root, "StandardBusinessDocumentHeader")
    _add(header, "HeaderVersion", "1.0")
    _add(_add(header, "Sender"), "Identifier", str(rng.randrange(10**8, 10**9)), Authority="DUNS")
    _add(_add(header, "Receiver"), "Identifier", str(rng.randrange(10**8, 10**9)), Authority="GLN")

    invoice = _add(root, "Invoice")
    if case != "missing_id":
        transaction_id = f"TXN-{rng.randint(10000, 99999)}"
        style = rng.random()
        if style < 0.7:
            _add(_add(invoice, "DocumentReference"), "TransactionID", transaction_id)
        elif style < 0.9 or wrapped:
            _add(invoice, "InvoiceID", transaction_id)
        else:
            # A generic <ID> only counts near the top of the document (see XMLParser).
            _add(invoice, "ID", transaction_id)

    if keep["issue_date"]:
        issued = date(2026, 1, 1) + timedelta(days=rng.randrange(300))
        _add(invoice, "IssueDate", issued.isoformat())
    if keep["currency"]:
        _add(invoice, "DocumentCurrencyCode", currency)
    if keep["supplier"]:
        party = _add(_add(invoice, "AccountingSupplierParty"), "Party")
        _add(_add(party, "PartyName"), "Name", rng.choice(SUPPLIERS))
    if keep["payment_account"]:
        account = _add(_add(invoice, "PaymentMeans"), "PayeeFinancialAccount")
        _add(account, "ID", f"IBAN-{rng.randrange(10**9, 10**10)}")

    for line_number in range(1, rng.randint(1, 4) + 1):
        line = _add(invoice, "InvoiceLine")
        _add(line, "ID", str(line_number))
        _add(line, "InvoicedQuantity", str(rng.randint(1, 500)))
        line_amount = f"{rng.uniform(10, 5000):.2f}"
        _add(line, "LineExtensionAmount", line_amount, currencyID=currency)
        _add(_add(line, "Item"), "Name", rng.choice(ITEMS))

    amount = None
    if case in ("valid", "missing_id"):
        amount = _normal_amount(rng)
        amount_text = f"{amount:.2f}"
    elif case == "high_value":
        amount_text = f"{rng.uniform(REVIEW_THRESHOLD + 1, 25_000_000):.2f}"
    elif case == "negative_amount":
        amount_text = f"-{rng.uniform(10, 5000):.2f}"
    elif case == "bad_amount":
        amount_text = rng.choice(BAD_AMOUNTS)
    if case != "missing_amount":
        total = _add(invoice, "LegalMonetaryTotal")
        _add(total, "PayableAmount", amount_text, currencyID=currency)

    if wrapped:
        envelope = ET.Element("Envelope")
        _add(_add(envelope, "Body"), "Payload").append(root)
        root = envelope

    missing_optional = sum(not kept for kept in keep.values())
    large_amount = amount is not None and amount >= LARGE_AMOUNT
    probability = failure_probability(case, missing_optional, large_amount, wrapped)
    failed = int(rng.random() < probability)

    xml = minidom.parseString(ET.tostring(root)).toprettyxml(indent="    ")
    return xml, case, failed


def generate_dataset(out_dir: str, count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED) -> list:
    """
    Writes `count` invoices (invoice_0001.xml, ...) and outcomes.csv to out_dir,
    replacing any XML files already there. Returns the outcome rows.
    """
    rng = random.Random(seed)
    os.makedirs(out_dir, exist_ok=True)

    # Clear old files
    for name in os.listdir(out_dir):
        if name.endswith(".xml") or name == OUTCOMES_FILE:
            os.remove(os.path.join(out_dir, name))

    outcomes = []
    for index in range(1, count + 1):
        filename = f"invoice_{index:04d}.xml"
        xml, case, failed = _make_invoice(rng)
        with open(os.path.join(out_dir, filename), "w", encoding="utf-8", newline="\n") as f:
            f.write(xml)
        outcomes.append({"source_file": filename, "case": case, "failed": failed})

    with open(os.path.join(out_dir, OUTCOMES_FILE), "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["source_file", "case", "failed"])
        writer.writeheader()
        writer.writerows(outcomes)

    return outcomes
