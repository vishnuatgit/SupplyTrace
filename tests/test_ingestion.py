import os
import tempfile

from src.ingestion.parser import XMLParser
from src.ingestion.xml_loader import XMLLoader


def test_parse_valid_xml():
    # Create a temporary valid XML file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xml", mode="w") as f:
        f.write("<invoice><id>001</id><amount>500</amount></invoice>")
        temp_path = f.name

    try:
        result = XMLLoader.parse_file(temp_path)
        assert result is not None
        assert result.get("invoice.id") == "001"
        assert result.get("invoice.amount") == "500"
    finally:
        os.remove(temp_path)


def test_parse_invalid_xml():
    # Create a temporary invalid XML file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xml", mode="w") as f:
        f.write("<invoice><id>001</id>")  # Missing closing tags
        temp_path = f.name

    try:
        result = XMLLoader.parse_file(temp_path)
        assert result is None
    finally:
        os.remove(temp_path)


def test_parse_missing_file():
    result = XMLLoader.parse_file("non_existent_file.xml")
    assert result is None


def test_xml_parser_standardize():
    raw_data = {
        "invoice.header.id": "001",
        "invoice.payableamount": "500",
        "currency": "usd",
        "_source_file": "inv.xml",
    }
    standardized = XMLParser.standardize(raw_data)

    # Check intelligent mapping
    assert standardized.get("ID") == "001"
    assert standardized.get("AMOUNT") == "500"

    # Check uppercase standardization
    assert standardized.get("CURRENCY") == "usd"
    assert standardized.get("_source_file") == "inv.xml"

    # Assert old lowercase keys do not exist (except meta)
    assert "invoice.header.id" not in standardized


def test_namespaced_xml_keeps_full_path(tmp_path):
    xml = (
        '<Doc xmlns="urn:x"><Header><Sender><Identifier>S1</Identifier></Sender>'
        "<Receiver><Identifier>R1</Identifier></Receiver></Header></Doc>"
    )
    path = tmp_path / "ns.xml"
    path.write_text(xml)
    result = XMLLoader.parse_file(str(path))
    # Regression: namespaces used to collapse every key to its last tag,
    # so the Sender and Receiver identifiers overwrote each other.
    assert result["Doc.Header.Sender.Identifier"] == "S1"
    assert result["Doc.Header.Receiver.Identifier"] == "R1"


def test_specific_id_alias_beats_nested_generic_id():
    raw = {
        "Doc.Invoice.PaymentMeans.PayeeFinancialAccount.ID": "IBAN-XYZ",
        "Doc.Invoice.DocumentReference.TransactionID": "TXN-1",
    }
    assert XMLParser.standardize(raw)["ID"] == "TXN-1"


def test_deeply_nested_generic_id_is_not_the_transaction_id():
    raw = {"Doc.Invoice.PaymentMeans.PayeeFinancialAccount.ID": "IBAN-XYZ"}
    assert XMLParser.standardize(raw)["ID"] == ""


def test_top_level_generic_id_is_used():
    assert XMLParser.standardize({"Invoice.ID": "INV-9"})["ID"] == "INV-9"
