"""
The single-document pipeline behind /api/analyze and the batch endpoints:

    parse (defusedxml) -> standardize -> validate -> features -> risk score,
    plus the line where the ID, the amount and each rule's evidence sit in the file.

Every endpoint calls analyze_document(), so a file gets exactly the same result
whether it is checked on its own or as part of a batch. Each stage is timed on
the server (timings_ms), so the page can show what the pipeline spent on a file.
"""

import logging
import time

from src.features.extractor import FEATURE_LABELS, FeatureExtractor
from src.ingestion.locator import XMLIndex, index_elements
from src.ingestion.parser import AMOUNT_TAGS, ID_TAGS, MAX_GENERIC_ID_DEPTH, XMLParser
from src.ingestion.xml_loader import XMLLoader, XMLLoadError
from src.prediction.model import RiskPredictor
from src.validation.rules import (
    AMOUNT_ABOVE_REVIEW_LIMIT,
    AMOUNT_NEGATIVE,
    AMOUNT_NOT_NUMERIC,
    BROKEN,
    PASSED,
    REVIEW_THRESHOLD,
    Rule,
    Validator,
)

logger = logging.getLogger(__name__)

NO_PREDICTION = {"risk_score": "N/A", "risk_flag": "N/A"}

# A batch row for a file that could not be read at all, so no rules ran.
REJECTED = "REJECTED"


class AnalysisError(Exception):
    """
    A file that cannot be analysed. status_code and detail are sent to the client;
    for malformed XML, position (line, column) and reason say where and why.
    """

    def __init__(self, status_code: int, detail: str, position=None, reason=None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.position = position
        self.reason = reason

    def to_json(self) -> dict:
        """The error response body: detail, plus line, column and reason when known."""
        body = {"detail": self.detail}
        if self.position:
            body.update(line=self.position[0], column=self.position[1], reason=self.reason)
        return body


def too_large_detail(max_bytes: int) -> str:
    return f"File is too large. The demo accepts XML files up to {max_bytes / 1_000_000:g} MB."


def check_upload(filename: str | None, content: bytes, max_bytes: int):
    """Raises AnalysisError for a file the demo does not accept: not .xml, or too big."""
    if not filename or not filename.lower().endswith(".xml"):
        raise AnalysisError(400, "Only .xml files are supported")
    if len(content) > max_bytes:
        raise AnalysisError(413, too_large_detail(max_bytes))


def predict(predictor: RiskPredictor, features: dict) -> tuple[dict, dict | None]:
    """
    The risk score and what drove it, or N/A and None when the model is
    untrained or fails.
    """
    if predictor.is_trained:
        try:
            prediction, drivers = predictor.predict_risk(features), predictor.explain(features)
            for driver in drivers["contributions"]:
                driver["label"] = FEATURE_LABELS[driver["feature"]]
            return prediction, drivers
        except Exception as e:
            logger.error(f"Prediction failed: {e}")
    return dict(NO_PREDICTION), None


def analyze_document(filename: str, content: bytes, predictor: RiskPredictor) -> dict:
    """
    Runs one XML document through the pipeline. Raises AnalysisError (400) for
    a document that cannot be parsed safely, or (500) if the analysis fails.
    """
    started = time.perf_counter()
    laps = [started]

    def lap() -> float:
        """Milliseconds since the previous stage ended."""
        laps.append(time.perf_counter())
        return round((laps[-1] - laps[-2]) * 1000, 2)

    # 1. Parse safely and flatten (in memory: the upload is never written to disk)
    try:
        raw_record = XMLLoader.parse_bytes(content)
    except XMLLoadError as e:
        logger.warning(f"Rejected {filename}: {e} ({e.__cause__ or 'no detail'})")
        raise AnalysisError(400, str(e), e.position, e.reason) from e
    timings = {"parse": lap()}

    try:
        # 2. Find the ID and amount, and apply the rules
        sources = XMLParser.field_sources(raw_record)
        raw_record["_source_file"] = filename
        standardized = XMLParser.standardize(raw_record)
        checklist = Validator.checklist(standardized)
        status, broken = Validator.check(standardized)
        timings["validate"] = lap()

        # 3. Extract features and score the risk
        features = FeatureExtractor.extract_features(standardized, xml_size=len(content))
        prediction, drivers = predict(predictor, features)
        timings["score"] = lap()

        # 4. Point every rule at a line of the file
        index = index_elements(content)
        fields = {
            name: describe_field(standardized.get(name, ""), sources[name], index)
            for name in ("ID", "AMOUNT")
        }
        findings = [locate_finding(rule, fields, index) for rule in broken]
        checks = [describe_check(rule, state, fields, findings) for rule, state in checklist]
        timings["locate"] = lap()
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise AnalysisError(500, "Analysis failed") from e

    return {
        "filename": filename,
        "id": standardized.get("ID", ""),
        "status": status.value,
        "errors": [rule.message for rule in broken],
        "findings": findings,
        "checks": checks,
        "fields": fields,
        "features": features,
        "prediction": prediction,
        "risk_drivers": drivers,
        # Measured server-side time to analyse the file, excluding the upload.
        "processing_ms": round((laps[-1] - started) * 1000, 2),
        "timings_ms": timings,
    }


def rejected_result(filename: str | None, error: AnalysisError) -> dict:
    """A batch row for a file that was refused before any rule ran."""
    return {
        "filename": filename or "",
        "id": "",
        "status": REJECTED,
        "errors": [error.detail],
        "findings": [],
        "checks": [],
        "fields": None,
        "features": None,
        "prediction": dict(NO_PREDICTION),
        "risk_drivers": None,
        "processing_ms": None,
        "timings_ms": None,
        "parse_error": error.to_json() if error.position else None,
    }


def describe_field(value: str, key: str | None, index: XMLIndex) -> dict:
    """The value used for ID or AMOUNT and the element (path and lines) it came from."""
    element = index.element_for_key(key)
    return {
        "value": value,
        "path": element.path if element else None,
        "line": element.line if element else None,
        "end_line": element.end_line if element else None,
    }


def locate_finding(rule: Rule, fields: dict, index: XMLIndex) -> dict:
    """
    Where a broken rule shows in the file. target is one of:
      "value"    - the element holding the bad (or high) value
      "empty"    - an element meant for the field that is present but empty
      "expected" - nothing usable was found; the element it was expected in
    """
    finding = {
        "rule": rule.code,
        "field": rule.field,
        "message": rule.message,
        "target": None,
        "line": None,
        "end_line": None,
        "note": "",
    }

    source = fields[rule.field]
    if source["line"]:
        tag = source["path"].rsplit(".", 1)[-1]
        if rule is AMOUNT_ABOVE_REVIEW_LIMIT:
            note = (
                f"<{tag}> on line {source['line']} holds {source['value']}, "
                f"above the {REVIEW_THRESHOLD:,} review limit."
            )
        else:
            note = f'<{tag}> on line {source["line"]} holds "{source["value"]}".'
        finding.update(target="value", line=source["line"], end_line=source["end_line"], note=note)
        return finding

    empty = _empty_candidate(rule.field, index)
    if empty:
        finding.update(
            target="empty",
            line=empty.line,
            end_line=empty.end_line,
            note=f"<{empty.tag}> on line {empty.line} is empty.",
        )
        return finding

    if rule.field == "ID":
        note = (
            "No TransactionID, InvoiceID or DocumentID element was found, "
            f"and no plain ID within {MAX_GENERIC_ID_DEPTH} levels of the root."
        )
    else:
        note = f"No {', '.join(AMOUNT_TAGS[:-1])} or {AMOUNT_TAGS[-1]} element was found."
    anchor = _expected_container(rule.field, index)
    if anchor:
        note += f" Marked: <{anchor.tag}> on line {anchor.line}, where it was expected."
        finding.update(target="expected", line=anchor.line, end_line=anchor.line)
    finding["note"] = note
    return finding


def describe_check(rule: Rule, state: str, fields: dict, findings: list) -> dict:
    """
    One row of the rule checklist: what happened to the rule (passed, broken or
    skipped), the status it sets when broken, and the line that shows it.
    """
    check = {
        "rule": rule.code,
        "title": rule.title,
        "field": rule.field,
        "state": state,
        "outcome": rule.outcome.value if state == BROKEN else None,
        "line": None,
        "end_line": None,
        "note": "",
    }
    if state == BROKEN:
        finding = next(f for f in findings if f["rule"] == rule.code)
        check.update(line=finding["line"], end_line=finding["end_line"], note=finding["note"])
        return check

    source = fields[rule.field]
    if state == PASSED:
        value = source["value"]
        if rule is AMOUNT_NOT_NUMERIC:
            note = f"{value} is a plain decimal number."
        elif rule is AMOUNT_NEGATIVE:
            note = f"{value} is not below zero."
        elif rule is AMOUNT_ABOVE_REVIEW_LIMIT:
            note = f"{value} is within the {REVIEW_THRESHOLD:,} review limit."
        elif source["line"]:
            note = f"{value} found on line {source['line']}."
        else:
            note = f"{value} found."
        check.update(line=source["line"], end_line=source["end_line"], note=note)
    elif not source["value"]:
        check["note"] = "Not checked: there is no amount."
    elif rule is AMOUNT_NEGATIVE:
        check["note"] = "Not checked: the amount is not a number."
    else:
        check["note"] = "Not checked: only applies when every other rule passes."
    return check


def _empty_candidate(field_name: str, index: XMLIndex):
    """The first element that could hold the field but has no value, if any."""
    tags = {t.upper() for t in (ID_TAGS if field_name == "ID" else AMOUNT_TAGS)}
    for element in index.elements:
        tag = element.tag.upper()
        if element.has_text or element.has_children or tag not in tags:
            continue
        if field_name == "ID" and tag == "ID" and element.depth > MAX_GENERIC_ID_DEPTH:
            continue  # a nested account or party ID, not the transaction ID
        return element
    return None


def _expected_container(field_name: str, index: XMLIndex):
    """The element a missing field would normally sit in: the totals block or the invoice."""
    if field_name == "AMOUNT":
        totals = index.first_tag("LegalMonetaryTotal")
        if totals:
            return totals
    return index.first_tag("Invoice") or index.root
