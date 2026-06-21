# SupplyTrace: Enterprise XML Validation & Risk Prediction

![SupplyTrace Logo](https://img.shields.io/badge/Status-Active-success) ![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-teal)

## Overview
Enterprise systems process millions of supplier transactions using XML documents that move across multiple processing stages before reaching the final business application. During this process, XML files may become invalid, incomplete, delayed, or fail to process correctly, resulting in silent downstream failures.

**SupplyTrace** is a lightweight, full-stack XML monitoring and validation system. It automatically ingests deeply nested enterprise XML files (e.g., UBL-style invoices), validates required fields, runs a Machine Learning model to predict processing risk, and presents failure insights through an interactive web dashboard.

This project reduces manual verification effort and drastically improves visibility into XML processing reliability.

## Architecture

```mermaid
graph TD
    A[Raw XML Files] -->|Ingested via Web UI| B(FastAPI Backend)
    B --> C{Recursive XML Parser}
    C -->|Flattens Data| D[Validation Engine]
    D --> E[Feature Extractor]
    E --> F((Random Forest ML Model))
    F -->|JSON Response| G[Premium System Dashboard]
```

## Key Features
1. **Deep Recursive XML Parsing**: Automatically traverses infinitely nested enterprise XML payloads to intelligently map critical identifiers (like `ID` and `Amount`) without rigid schema definitions.
2. **Machine Learning Risk Prediction**: Uses a trained `scikit-learn` Random Forest Classifier to assess hidden metadata (like latency, file size, and missing field ratios) to predict the likelihood of a transaction failing in the downstream application.
3. **Enterprise Dashboard**: A glassmorphic, responsive web interface that instantly visualizes historical failure rates, average risk scores, and total processed volume.
4. **Live Transaction Inspector**: A drag-and-drop tool within the dashboard that allows analysts to simulate a payload in real-time to see exactly how the ML model interprets the data.

## Directory Structure

```text
SupplyTrace/
├── frontend/             # Vanilla JS/HTML/CSS Web Application
│   ├── index.html        # Dashboard & Inspector UI
│   ├── styles.css        # Glassmorphism styling & animations
│   └── app.js            # Fetch API integration
├── src/                  # Core Python Pipeline
│   ├── api/              # FastAPI server (server.py)
│   ├── ingestion/        # Recursive XML loader & intelligent parser
│   ├── validation/       # Deterministic rules engine
│   ├── features/         # Feature engineering (metadata extraction)
│   ├── prediction/       # ML inference wrapper
│   └── pipeline/         # Orchestrator to tie all modules together
├── models/               # Serialized ML model weights (Random Forest)
├── results/              # Output CSVs for historical tracking
├── scripts/              # Helper utilities (generate_data.py)
└── tests/                # Full pytest suite validating pipeline integrity
```

## Getting Started

### Prerequisites
- Python 3.10+
- A modern web browser

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/vishnuatgit/SupplyTrace.git
   cd SupplyTrace
   ```
2. Create and activate a virtual environment:
   ```bash
   # Windows
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   
   # Linux/Mac
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Running the System

1. **Generate Enterprise Test Data**  
   Run the data generator to create highly nested UBL-style XML test files inside `data/raw_xml/`.
   ```bash
   python scripts/generate_data.py
   ```

2. **Train the ML Model & Process Batch Data**  
   Run the pipeline to process the generated data, extract features, and train the Random Forest model.
   ```bash
   python -m scripts.run_pipeline
   ```

3. **Start the Web Dashboard**  
   Boot up the FastAPI server, which hosts both the REST endpoints and the static frontend.
   ```bash
   python -m src.api.server
   ```

4. **Access the Application**  
   Open your browser and navigate to:  
   **[http://127.0.0.1:8000](http://127.0.0.1:8000)**  
   *You can drag and drop the generated files from `data/raw_xml/` directly into the UI to test the live inspector.*

## Testing
SupplyTrace is fully tested using `pytest`. The test suite covers ingestion, validation, feature extraction, and prediction to ensure robust CI/CD integration.
```bash
python -m pytest tests/
```

## License
Developed as an enterprise architecture solution and portfolio demonstration. All rights reserved.
