import os
import random
import xml.etree.ElementTree as ET
from xml.dom import minidom

RAW_DATA_DIR = os.path.join("data", "raw_xml")

def create_nested_xml(filename, include_id=True, include_amount=True, amount_value=None):
    """
    Generates a realistic, highly nested UBL-style enterprise XML payload.
    """
    # Root Element
    root = ET.Element("StandardBusinessDocument", xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2")
    
    # Header block
    header = ET.SubElement(root, "StandardBusinessDocumentHeader")
    header_version = ET.SubElement(header, "HeaderVersion")
    header_version.text = "1.0"
    
    sender = ET.SubElement(header, "Sender")
    sender_id = ET.SubElement(sender, "Identifier", Authority="DUNS")
    sender_id.text = "123456789"
    
    receiver = ET.SubElement(header, "Receiver")
    receiver_id = ET.SubElement(receiver, "Identifier", Authority="GLN")
    receiver_id.text = "987654321"

    # Payload Block
    invoice = ET.SubElement(root, "Invoice")
    
    # Deeply nested ID
    if include_id:
        doc_ref = ET.SubElement(invoice, "DocumentReference")
        transaction_id = ET.SubElement(doc_ref, "TransactionID")
        transaction_id.text = f"TXN-{random.randint(10000, 99999)}"
        
    issue_date = ET.SubElement(invoice, "IssueDate")
    issue_date.text = "2026-06-20"
    
    # Vendor Block
    vendor = ET.SubElement(invoice, "AccountingSupplierParty")
    party = ET.SubElement(vendor, "Party")
    party_name = ET.SubElement(party, "PartyName")
    name = ET.SubElement(party_name, "Name")
    name.text = "Acme Corp Global"
    
    # Deeply nested Amount
    payment_means = ET.SubElement(invoice, "PaymentMeans")
    payee_account = ET.SubElement(payment_means, "PayeeFinancialAccount")
    account_id = ET.SubElement(payee_account, "ID")
    account_id.text = "IBAN-XYZ"
    
    if include_amount:
        legal_total = ET.SubElement(invoice, "LegalMonetaryTotal")
        amount = ET.SubElement(legal_total, "PayableAmount", currencyID="USD")
        if amount_value is not None:
            amount.text = str(amount_value)
        else:
            amount.text = str(round(random.uniform(100.0, 5000.0), 2))
            
    # Pretty print string
    xmlstr = minidom.parseString(ET.tostring(root)).toprettyxml(indent="    ")
    
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    with open(os.path.join(RAW_DATA_DIR, filename), "w", encoding="utf-8") as f:
        f.write(xmlstr)

def main():
    print("Generating deeply nested enterprise XML data...")
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    
    # Clear old files
    for file in os.listdir(RAW_DATA_DIR):
        if file.endswith(".xml"):
            os.remove(os.path.join(RAW_DATA_DIR, file))
            
    # Generate 5 Valid highly nested files
    for i in range(1, 6):
        create_nested_xml(f"enterprise_valid_{i}.xml")
        
    # Generate Invalid files (Missing ID deeply nested)
    create_nested_xml("enterprise_invalid_missing_id_6.xml", include_id=False)
    create_nested_xml("enterprise_invalid_missing_id_7.xml", include_id=False)
    
    # Generate Invalid files (Missing Amount deeply nested)
    create_nested_xml("enterprise_invalid_empty_amount_8.xml", include_amount=False)
    create_nested_xml("enterprise_invalid_empty_amount_9.xml", include_amount=False)
    
    # Generate Review file (Huge amount deeply nested)
    create_nested_xml("enterprise_review_high_amount_10.xml", amount_value="5000000.00")
    
    print("Data generation complete. 10 Enterprise XML files generated.")

if __name__ == "__main__":
    main()
