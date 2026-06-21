import os
import tempfile
import pytest
from src.ingestion.xml_loader import XMLLoader
from src.ingestion.parser import XMLParser

def test_parse_valid_xml():
    # Create a temporary valid XML file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xml", mode='w') as f:
        f.write("<invoice><id>001</id><amount>500</amount></invoice>")
        temp_path = f.name
        
    try:
        result = XMLLoader.parse_file(temp_path)
        assert result is not None
        assert result.get('invoice.id') == '001'
        assert result.get('invoice.amount') == '500'
    finally:
        os.remove(temp_path)

def test_parse_invalid_xml():
    # Create a temporary invalid XML file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xml", mode='w') as f:
        f.write("<invoice><id>001</id>") # Missing closing tags
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
    raw_data = {'invoice.header.id': '001', 'invoice.payableamount': '500', 'currency': 'usd', '_source_file': 'inv.xml'}
    standardized = XMLParser.standardize(raw_data)
    
    # Check intelligent mapping
    assert standardized.get('ID') == '001'
    assert standardized.get('AMOUNT') == '500'
    
    # Check uppercase standardization
    assert standardized.get('CURRENCY') == 'usd'
    assert standardized.get('_source_file') == 'inv.xml'
    
    # Assert old lowercase keys do not exist (except meta)
    assert 'invoice.header.id' not in standardized
