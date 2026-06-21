import xml.etree.ElementTree as ET
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class XMLLoader:
    """
    Responsible for loading and parsing supplier XML files safely.
    Handles deeply nested enterprise structures by flattening them.
    """
    
    @staticmethod
    def _flatten_tree(elem, current_path="", parsed_data=None):
        if parsed_data is None:
            parsed_data = {}
            
        path = f"{current_path}.{elem.tag}" if current_path else elem.tag
        
        # Remove namespace brackets {http://...} tag
        clean_tag = path.split('}')[-1] if '}' in path else path
        
        if elem.text and elem.text.strip():
            parsed_data[clean_tag] = elem.text.strip()
            
        for child in elem:
            XMLLoader._flatten_tree(child, clean_tag, parsed_data)
            
        return parsed_data

    @staticmethod
    def parse_file(file_path: str) -> dict:
        """
        Parses an XML file and returns a flat dictionary representation
        using dot-notation for nested structures.
        """
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return None
            
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            
            parsed_data = XMLLoader._flatten_tree(root)
            return parsed_data
            
        except ET.ParseError as e:
            logger.error(f"Failed to parse XML file {file_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error reading {file_path}: {e}")
            return None

    @staticmethod
    def load_directory(directory_path: str) -> list:
        """
        Loads all XML files from a given directory.
        """
        results = []
        if not os.path.exists(directory_path):
            logger.error(f"Directory not found: {directory_path}")
            return results
            
        for filename in os.listdir(directory_path):
            if filename.endswith(".xml"):
                file_path = os.path.join(directory_path, filename)
                parsed = XMLLoader.parse_file(file_path)
                if parsed is not None:
                    parsed['_source_file'] = filename
                    results.append(parsed)
                    
        return results
