import logging
import os
import xml.etree.ElementTree as ET

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring as safe_fromstring

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Deeper documents are rejected instead of being flattened.
MAX_DEPTH = 100


class XMLLoadError(ValueError):
    """
    Raised when a document cannot be loaded. The message is safe to show to users.
    For malformed XML, position is (line, column), both 1-based, and reason is the
    parser's short description (e.g. "mismatched tag"); otherwise both are None.
    """

    def __init__(self, message: str, position: tuple[int, int] | None = None, reason=None):
        super().__init__(message)
        self.position = position
        self.reason = reason


class XMLLoader:
    """
    Responsible for loading and parsing supplier XML files safely.
    Handles deeply nested enterprise structures by flattening them.
    """

    @staticmethod
    def _flatten_tree(elem, current_path="", parsed_data=None, depth=1):
        if parsed_data is None:
            parsed_data = {}
        if depth > MAX_DEPTH:
            raise XMLLoadError(f"XML nesting is too deep (limit is {MAX_DEPTH} levels)")

        # Strip the namespace ({http://...}Tag -> Tag) from this element only,
        # so the parent path is preserved for namespaced documents.
        local_tag = elem.tag.split("}", 1)[-1]
        clean_tag = f"{current_path}.{local_tag}" if current_path else local_tag

        if elem.text and elem.text.strip():
            parsed_data[clean_tag] = elem.text.strip()

        for child in elem:
            XMLLoader._flatten_tree(child, clean_tag, parsed_data, depth + 1)

        return parsed_data

    @staticmethod
    def parse_bytes(content: bytes) -> dict:
        """
        Parses an XML document held in memory into a flat dictionary using
        dot-notation for nested structures. DTDs (and with them entity
        expansion and external references) are refused.
        Raises XMLLoadError if the document cannot be used.
        """
        if not content.strip():
            # Clearer than the parser's "no element found: line 1, column 0".
            raise XMLLoadError("The file is empty")
        try:
            root = safe_fromstring(content, forbid_dtd=True)
        except DefusedXmlException as e:
            raise XMLLoadError("DTDs and entity declarations are not allowed") from e
        except ET.ParseError as e:
            line, column = e.position
            reason = str(e).split(":", 1)[0]
            raise XMLLoadError(
                "Invalid or malformed XML file", position=(line, column + 1), reason=reason
            ) from e
        return XMLLoader._flatten_tree(root)

    @staticmethod
    def parse_file(file_path: str) -> dict:
        """
        Parses an XML file and returns a flat dictionary representation
        using dot-notation for nested structures, or None if it cannot be used.
        """
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return None

        try:
            with open(file_path, "rb") as f:
                return XMLLoader.parse_bytes(f.read())
        except XMLLoadError as e:
            logger.error(
                f"Failed to parse XML file {file_path}: {e} ({e.__cause__ or 'no detail'})"
            )
            return None
        except Exception as e:
            logger.error(f"Unexpected error reading {file_path}: {e}")
            return None

    @staticmethod
    def load_directory(directory_path: str) -> list:
        """
        Loads all XML files from a given directory, in filename order.
        """
        results = []
        if not os.path.exists(directory_path):
            logger.error(f"Directory not found: {directory_path}")
            return results

        for filename in sorted(os.listdir(directory_path)):
            if filename.endswith(".xml"):
                file_path = os.path.join(directory_path, filename)
                parsed = XMLLoader.parse_file(file_path)
                if parsed is not None:
                    parsed["_source_file"] = filename
                    results.append(parsed)

        return results
