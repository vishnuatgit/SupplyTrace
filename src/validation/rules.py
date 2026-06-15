from enum import Enum

class Status(Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"

class Validator:
    """
    Deterministic rule-based validation engine for standardized supplier XML data.
    """
    
    @staticmethod
    def validate(record: dict) -> tuple[Status, list[str]]:
        """
        Validates a structured record based on deterministic rules.
        Returns the classification status and a list of error messages.
        """
        errors = []
        
        # Rule 1: Missing ID -> FAIL
        if not record.get('ID') or not str(record.get('ID')).strip():
            errors.append("Missing required field: ID")
            
        # Rule 2: Missing Amount -> FAIL
        if not record.get('AMOUNT') or not str(record.get('AMOUNT')).strip():
            errors.append("Missing required field: AMOUNT")
        elif not str(record.get('AMOUNT')).replace('.', '', 1).isdigit():
            errors.append("Invalid format: AMOUNT must be numeric")
            
        # Classify
        if errors:
            return Status.INVALID, errors
            
        # Rule 3: Requires Review (e.g., suspicious large amounts)
        # Assuming we flag anything over 1000000 as requiring review
        if float(record.get('AMOUNT')) > 1000000:
            return Status.REQUIRES_REVIEW, ["High value amount, requires manual review"]
            
        return Status.VALID, []
