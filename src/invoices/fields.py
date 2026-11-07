"""
The key fields of an invoice that duplicate detection (and the vendor directory)
compare: who the supplier is, the issue date, the currency and the amount.

They are read from the standardized record, where every key is the document's
dot-notation path in capitals, such as
INVOICE.ACCOUNTINGSUPPLIERPARTY.PARTY.PARTYNAME.NAME.
"""

from datetime import date

from src.validation.rules import parse_amount

# Path segments that mark a supplier party (the same names the feature extractor uses).
SUPPLIER_SEGMENTS = {"ACCOUNTINGSUPPLIERPARTY", "SUPPLIER", "SELLER", "SELLERPARTY"}
SUPPLIER_NAME_TAGS = {"SUPPLIERNAME", "SELLERNAME"}
SUPPLIER_ID_TAGS = {"ID", "ENDPOINTID", "COMPANYID"}
DATE_TAGS = {"ISSUEDATE", "INVOICEDATE"}
CURRENCY_TAGS = {"DOCUMENTCURRENCYCODE", "CURRENCYCODE", "CURRENCY"}


def _first(record: dict, wanted) -> str:
    """The first non-empty value whose key passes the `wanted(parts)` test, or an empty string."""
    for key, value in record.items():
        if key.startswith("_") or not value:
            continue
        if wanted(key.split(".")):
            return str(value).strip()
    return ""


def vendor_key(supplier_id: str, supplier_name: str) -> str:
    """
    One text per vendor: the supplier ID if the invoice has one, otherwise the name,
    lower-cased with spaces collapsed so "Acme  Corp" and "acme corp" are the same vendor.
    Empty when the invoice does not say who the supplier is.
    """
    return " ".join((supplier_id or supplier_name).casefold().split())


def parse_issue_date(text: str) -> date | None:
    """A YYYY-MM-DD date (ignoring any time after it), or None."""
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def key_fields(record: dict) -> dict:
    """The supplier, issue date, currency and amount of a standardized record."""
    supplier_id = _first(
        record,
        lambda p: bool(SUPPLIER_SEGMENTS & set(p[:-1])) and p[-1] in SUPPLIER_ID_TAGS,
    )
    supplier_name = _first(
        record,
        lambda p: (
            (bool(SUPPLIER_SEGMENTS & set(p[:-1])) and p[-1] == "NAME")
            or p[-1] in SUPPLIER_NAME_TAGS
        ),
    )
    issued = parse_issue_date(_first(record, lambda p: p[-1] in DATE_TAGS))
    kind, amount = parse_amount(record.get("AMOUNT"))
    return {
        "supplier_id": supplier_id,
        "supplier_name": supplier_name,
        "vendor_key": vendor_key(supplier_id, supplier_name),
        "issue_date": issued.isoformat() if issued else "",
        "currency": _first(record, lambda p: p[-1] in CURRENCY_TAGS),
        "amount": amount if kind == "ok" else None,
    }
