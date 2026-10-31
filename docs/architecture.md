# SupplyTrace Architecture

## Overview
SupplyTrace is a lightweight XML monitoring and validation system. It reads supplier XML files, validates required fields, extracts features, and predicts processing failures using a machine learning model.

## Components
1. **Ingestion**: Parses raw XML files safely (`defusedxml`: no DTDs or entity expansion, at most 100 levels deep) into flat Python dictionaries.
2. **Validation**: Applies rule-based checks (missing ID or amount, non-numeric or negative amount, amounts above 1,000,000) to categorize XML files as VALID, INVALID, or REQUIRES_REVIEW.
3. **Feature Extraction**: Extracts risk signals (problems with the required fields, amount size, missing optional fields, nesting depth) for the ML model.
4. **Prediction**: An experimental Random Forest classifier, trained on synthetic invoices with simulated outcomes (`pipeline/synthetic.py`), estimates the risk of XML processing failure from those signals.
5. **Dashboard**: A visualization layer to monitor XML processing health.

## Data Flow
Supplier XML -> `ingestion/xml_loader.py` -> `ingestion/parser.py` -> `validation/rules.py` -> `features/extractor.py` -> `prediction/model.py` -> `dashboard/exporter.py` + `api/server.py` (dashboard)
