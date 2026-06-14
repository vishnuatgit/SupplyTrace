import xml.etree.ElementTree as ET
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class XMLLoader:
    """
    Responsible for loading and parsing supplier XML files safely.
    """
    
    @staticmethod
    def parse_file(file_path: str) -> dict:
        """
        Parses an XML file and returns a flat dictionary representation.
        Logs an error and returns None if the file is invalid or cannot be read.
        """
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return None
            
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            
            # Simple flattening for starter implementation
            # Assumes a simple key-value structure like <invoice><id>001</id></invoice>
            parsed_data = {}
            for child in root:
                parsed_data[child.tag] = child.text
                
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
                    # Inject filename as source reference
                    parsed['_source_file'] = filename
                    results.append(parsed)
                    
        return results
