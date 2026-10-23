class XMLParser:
    """
    Standardizes parsed XML data into a consistent, uppercase-keyed format.
    Intelligently maps deeply nested enterprise keys to standard pipeline keys.
    """

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

        # First pass: Uppercase everything
        temp_data = {}
        for key, value in raw_data.items():
            if key != "_source_file":
                standardized_key = str(key).strip().upper()
                temp_data[standardized_key] = value.strip() if value else ""
                standardized_data[standardized_key] = temp_data[standardized_key]

        # Second pass: map ID and AMOUNT. Specific aliases win over generic ones,
        # and a generic "ID" only counts near the top of the document, so a
        # nested account or party ID (e.g. PayeeFinancialAccount.ID) is never
        # mistaken for the transaction ID.
        id_aliases = ["TRANSACTIONID", "INVOICEID", "DOCUMENTID", "ID"]
        amount_aliases = ["PAYABLEAMOUNT", "TOTALAMOUNT", "INVOICEAMOUNT", "AMOUNT", "TOTAL"]
        max_generic_id_depth = 3

        def first_match(aliases, depth_limit=None):
            for alias in aliases:
                for k, v in temp_data.items():
                    parts = k.split(".")
                    if parts[-1] != alias or not v:
                        continue
                    if depth_limit is not None and alias == "ID" and len(parts) > depth_limit:
                        continue
                    return v
            return ""

        mapped_data = {
            "ID": first_match(id_aliases, max_generic_id_depth),
            "AMOUNT": first_match(amount_aliases),
        }

        # Merge mapped fields back
        standardized_data.update(mapped_data)

        return standardized_data
