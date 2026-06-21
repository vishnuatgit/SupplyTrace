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
        if '_source_file' in raw_data:
            standardized_data['_source_file'] = raw_data['_source_file']
            
        # First pass: Uppercase everything
        temp_data = {}
        for key, value in raw_data.items():
            if key != '_source_file':
                standardized_key = str(key).strip().upper()
                temp_data[standardized_key] = value.strip() if value else ""
                standardized_data[standardized_key] = temp_data[standardized_key]
                
        # Second pass: Intelligent mapping for ID and AMOUNT
        mapped_data = {'ID': '', 'AMOUNT': ''}
        
        # Mapping definitions
        id_aliases = ['ID', 'DOCUMENTID', 'INVOICEID', 'TRANSACTIONID']
        amount_aliases = ['AMOUNT', 'TOTALAMOUNT', 'INVOICEAMOUNT', 'PAYABLEAMOUNT', 'TOTAL']
        
        for k, v in temp_data.items():
            # Extract just the very last tag in a nested path (e.g., 'INVOICE.HEADER.DOCUMENTID' -> 'DOCUMENTID')
            last_tag = k.split('.')[-1]
            
            if last_tag in id_aliases and not mapped_data['ID']:
                mapped_data['ID'] = v
            elif last_tag in amount_aliases and not mapped_data['AMOUNT']:
                mapped_data['AMOUNT'] = v
                
        # Merge mapped fields back
        standardized_data.update(mapped_data)
                
        return standardized_data
