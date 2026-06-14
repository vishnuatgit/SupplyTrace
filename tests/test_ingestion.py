import os
import tempfile
import pytest
from src.ingestion.xml_loader import XMLLoader

def test_parse_valid_xml():
    # Create a temporary valid XML file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xml", mode='w') as f:
        f.write("<invoice><id>001</id><amount>500</amount></invoice>")
        temp_path = f.name
        
    try:
        result = XMLLoader.parse_file(temp_path)
        assert result is not None
        assert result.get('id') == '001'
        assert result.get('amount') == '500'
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
