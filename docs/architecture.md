# SupplyTrace Architecture

## Overview
SupplyTrace is a lightweight XML monitoring and validation system. It reads supplier XML files, validates required fields, extracts features, and predicts processing failures using a machine learning model.

## Components
1. **Ingestion**: Parses raw XML files into structured Python dictionaries.
2. **Validation**: Applies rule-based checks (e.g., missing fields, empty values) to categorize XML files as VALID, INVALID, or REQUIRES_REVIEW.
3. **Feature Extraction**: Extracts key metrics (e.g., payload size, missing fields count) and saves them for the ML model.
4. **Prediction**: A Random Forest classifier predicts the risk of XML processing failure based on extracted features.
5. **Dashboard**: A visualization layer to monitor XML processing health.

## Data Flow
Supplier XML -> `xml_loader.py` -> `validator.py` -> `feature_extractor.py` -> `predictor.py` -> Dashboard
