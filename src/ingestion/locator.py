"""
Line numbers for the elements of an XML document, so a finding can point at
the line that caused it.

XMLLoader (ElementTree) does not keep line numbers, so this makes a second,
lightweight pass with Python's built-in expat parser. It only runs on documents
that XMLLoader has already accepted (no DTD, limited depth), and it refuses a
DOCTYPE itself as well, so it never expands entities.

Paths are built exactly like XMLLoader's flattened keys: local tag names (the
namespace removed) joined with dots, e.g. "Invoice.LegalMonetaryTotal.PayableAmount".
"""

import xml.parsers.expat
from dataclasses import dataclass, field


@dataclass
class ElementSpan:
    path: str  # flattened path, as XMLLoader writes it
    tag: str  # local tag name
    line: int  # line of the start tag (1-based)
    end_line: int  # line of the end tag
    has_text: bool = False  # True when XMLLoader keeps a value for this element
    has_children: bool = False

    @property
    def depth(self) -> int:
        return self.path.count(".") + 1


@dataclass
class XMLIndex:
    elements: list = field(default_factory=list)  # every element, in document order
    by_path: dict = field(default_factory=dict)  # uppercased path -> element whose value is kept

    def element_for_key(self, key: str | None) -> ElementSpan | None:
        """The element behind a flattened key (any case), as used by XMLParser."""
        return self.by_path.get(key.upper()) if key else None

    def first_tag(self, *tags: str) -> ElementSpan | None:
        """The first element whose tag (any case) is one of `tags`."""
        wanted = {t.upper() for t in tags}
        return next((e for e in self.elements if e.tag.upper() in wanted), None)

    @property
    def root(self) -> ElementSpan | None:
        return self.elements[0] if self.elements else None


class _DoctypeRefused(Exception):
    pass


def index_elements(content: bytes) -> XMLIndex:
    """
    Records where every element starts and ends. Best effort: returns an empty
    index if the document cannot be read, since line numbers are only a display aid.
    """
    index = XMLIndex()
    open_elements = []  # stack of (span, text chunks before the first child)
    parser = xml.parsers.expat.ParserCreate(namespace_separator="}")
    parser.buffer_text = True

    def start(name, _attributes):
        tag = name.split("}", 1)[-1]
        if open_elements:
            parent = open_elements[-1][0]
            parent.has_children = True
            path = f"{parent.path}.{tag}"
        else:
            path = tag
        span = ElementSpan(path, tag, parser.CurrentLineNumber, parser.CurrentLineNumber)
        index.elements.append(span)
        open_elements.append((span, []))

    def text(data):
        # Like ElementTree's .text: only the text before the element's first child.
        if open_elements and not open_elements[-1][0].has_children:
            open_elements[-1][1].append(data)

    def end(_name):
        span, chunks = open_elements.pop()
        span.end_line = parser.CurrentLineNumber
        span.has_text = bool("".join(chunks).strip())
        if span.has_text:
            # XMLLoader keeps the last value for a repeated path; so does this.
            index.by_path[span.path.upper()] = span

    def refuse_doctype(*_args):
        raise _DoctypeRefused

    parser.StartElementHandler = start
    parser.CharacterDataHandler = text
    parser.EndElementHandler = end
    parser.StartDoctypeDeclHandler = refuse_doctype

    try:
        parser.Parse(content, True)
    except (xml.parsers.expat.ExpatError, _DoctypeRefused):
        return XMLIndex()
    return index
