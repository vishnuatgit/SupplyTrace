# Tag names that can hold the transaction ID and the amount, most specific first.
ID_TAGS = ("TransactionID", "InvoiceID", "DocumentID", "ID")
AMOUNT_TAGS = ("PayableAmount", "TotalAmount", "InvoiceAmount", "Amount", "Total")

# A bare <ID> only counts this close to the root (counted in path segments), so a
# nested account or party ID (e.g. PayeeFinancialAccount.ID) is never mistaken
# for the transaction ID.
MAX_GENERIC_ID_DEPTH = 3


def _uppercase_keys(raw_data: dict) -> dict:
    """The document's flattened keys, uppercased, with stripped values (meta keys left out)."""
    return {
        str(key).strip().upper(): value.strip() if value else ""
        for key, value in raw_data.items()
        if key != "_source_file"
    }


def _first_key(data: dict, tags: tuple, generic_id_depth: int | None = None) -> str | None:
    """
    The first key whose last segment is one of `tags` and whose value is not empty.
    Earlier tags win over later ones. With generic_id_depth, a bare ID only
    counts when the key has at most that many segments.
    """
    for tag in (t.upper() for t in tags):
        for key, value in data.items():
            parts = key.split(".")
            if parts[-1] != tag or not value:
                continue
            if generic_id_depth is not None and tag == "ID" and len(parts) > generic_id_depth:
                continue
            return key
    return None


def _field_sources(data: dict) -> dict:
    return {
        "ID": _first_key(data, ID_TAGS, MAX_GENERIC_ID_DEPTH),
        "AMOUNT": _first_key(data, AMOUNT_TAGS),
    }


class XMLParser:
    """
    Standardizes parsed XML data into a consistent, uppercase-keyed format.
    Intelligently maps deeply nested enterprise keys to standard pipeline keys.
    """

    @staticmethod
    def field_sources(raw_data: dict) -> dict:
        """
        The flattened key (uppercased) that the ID and the AMOUNT are taken
        from, or None when the document has no usable value for that field.
        """
        return _field_sources(_uppercase_keys(raw_data or {}))

    @staticmethod
    def standardize(raw_data: dict) -> dict:
        """
        Takes flat dictionary output from XMLLoader (using dot-notation for nested tags).
        Converts keys to uppercase and extracts standard 'ID' and 'AMOUNT' fields
        regardless of their nesting depth or naming conventions.
        """
        if not raw_data:
            return {}

        standardized_data = {}
        # Keep meta tags untouched
        if "_source_file" in raw_data:
            standardized_data["_source_file"] = raw_data["_source_file"]

        # Every document key, uppercased
        data = _uppercase_keys(raw_data)
        standardized_data.update(data)

        # Map ID and AMOUNT. Specific tags win over generic ones (see ID_TAGS).
        sources = _field_sources(data)
        standardized_data["ID"] = data[sources["ID"]] if sources["ID"] else ""
        standardized_data["AMOUNT"] = data[sources["AMOUNT"]] if sources["AMOUNT"] else ""

        return standardized_data
