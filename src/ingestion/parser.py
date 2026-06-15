class XMLParser:
    """
    Standardizes parsed XML data into a consistent, uppercase-keyed format.
    """
    
    @staticmethod
    def standardize(raw_data: dict) -> dict:
        """
        Takes raw dictionary output from XMLLoader and standardizes the schema.
        Converts all keys to uppercase (e.g., 'id' -> 'ID').
        """
        if not raw_data:
            return {}
            
        standardized_data = {}
        for key, value in raw_data.items():
            if key == '_source_file':
                standardized_data[key] = value # Keep source file meta untouched
            else:
                standardized_key = str(key).strip().upper()
                standardized_data[standardized_key] = value.strip() if value else ""
                
        return standardized_data
