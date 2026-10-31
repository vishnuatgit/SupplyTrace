from src.ingestion.locator import index_elements
from src.ingestion.parser import XMLParser
from src.ingestion.xml_loader import XMLLoader

DOC = b"""<?xml version="1.0"?>
<Doc xmlns="urn:x" xmlns:c="urn:c">
  <Invoice>
    <c:TransactionID>TXN-1</c:TransactionID>
    <Line><ID>1</ID></Line>
    <Line><ID>2</ID></Line>
    <Note>first
      second</Note>
    <Empty/>
  </Invoice>
</Doc>"""


def test_elements_get_start_and_end_lines():
    index = index_elements(DOC)
    note = index.first_tag("Note")
    assert (note.line, note.end_line) == (7, 8)
    assert index.root.tag == "Doc" and index.root.line == 2
    assert index.first_tag("transactionid").line == 4  # tags match in any case


def test_paths_match_the_loader_keys():
    index = index_elements(DOC)
    raw = XMLLoader.parse_bytes(DOC)
    # Every key the loader keeps has an element in the index, under the same path.
    for key in raw:
        assert index.element_for_key(key).path == key


def test_repeated_paths_keep_the_last_element_like_the_loader():
    index = index_elements(DOC)
    assert XMLLoader.parse_bytes(DOC)["Doc.Invoice.Line.ID"] == "2"
    assert index.element_for_key("DOC.INVOICE.LINE.ID").line == 6


def test_empty_and_container_elements_have_no_text():
    index = index_elements(DOC)
    empty = index.first_tag("Empty")
    assert not empty.has_text and not empty.has_children
    invoice = index.first_tag("Invoice")
    assert not invoice.has_text and invoice.has_children


def test_crlf_line_endings_count_as_one_line():
    index = index_elements(b"<a>\r\n<b>x</b>\r\n<c>y</c>\r\n</a>")
    assert index.first_tag("c").line == 3


def test_field_source_points_at_the_line_used():
    raw = XMLLoader.parse_bytes(DOC)
    sources = XMLParser.field_sources(raw)
    assert sources["ID"] == "DOC.INVOICE.TRANSACTIONID"
    assert index_elements(DOC).element_for_key(sources["ID"]).line == 4


def test_doctype_and_broken_documents_give_an_empty_index():
    assert index_elements(b'<!DOCTYPE a [<!ENTITY x "y">]><a>&x;</a>').elements == []
    assert index_elements(b"<a><b></a>").elements == []
