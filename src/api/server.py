import os
import tempfile
import pandas as pd
import logging
import json
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from src.ingestion.xml_loader import XMLLoader
from src.ingestion.parser import XMLParser
from src.validation.rules import Validator
from src.features.extractor import FeatureExtractor
from src.prediction.model import RiskPredictor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="SupplyTrace API")

# Allow CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

predictor = RiskPredictor()

@app.on_event("startup")
def startup_event():
    """Train the model on startup if historical data exists."""
    csv_path = os.path.join("results", "results.csv")
    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path)
            has_valid = (df['status'] == 'VALID').any()
            has_invalid = (df['status'] != 'VALID').any()
            if has_valid and has_invalid:
                logger.info("Training ML model from historical results.csv...")
                predictor.fit(df)
            else:
                logger.warning("Historical data lacks class diversity. Model untrained.")
        except Exception as e:
            logger.error(f"Failed to train model on startup: {e}")
    else:
        logger.warning(f"No historical data at {csv_path}. Model will return N/A for risk.")

@app.post("/api/analyze")
async def analyze_xml(file: UploadFile = File(...)):
    if not file.filename.endswith('.xml'):
        raise HTTPException(status_code=400, detail="Only .xml files are supported")
    
    # Save uploaded file temporarily so our existing pipeline can read it
    try:
        content = await file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xml") as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name
            
        # 1. Ingest
        raw_record = XMLLoader.parse_file(temp_file_path)
        if raw_record is None:
            raise HTTPException(status_code=400, detail="Invalid or malformed XML file")
            
        raw_record['_source_file'] = file.filename
        
        # 2. Standardize
        standardized = XMLParser.standardize(raw_record)
        
        # 3. Validate
        status, errors = Validator.validate(standardized)
        
        # 4. Extract Features
        features = FeatureExtractor.extract_features(standardized, file_path=temp_file_path)
        
        # Clean up temp file
        os.remove(temp_file_path)
        
        # 5. Predict Risk
        risk_score = "N/A"
        risk_flag = "N/A"
        
        # Check if predictor has been fitted (it has a fitted_ model attribute if using sklearn)
        if hasattr(predictor, 'model') and hasattr(predictor.model, 'classes_'):
            try:
                # Prepare features dict
                pred_features = {col: features.get(col, 0) for col in predictor.feature_columns}
                pred_result = predictor.predict_risk(pred_features)
                risk_score = pred_result['risk_score']
                risk_flag = pred_result['risk_flag']
            except Exception as e:
                logger.error(f"Prediction failed: {e}")
                
        response_data = {
            "filename": file.filename,
            "status": status.value,
            "errors": errors,
            "features": features,
            "prediction": {
                "risk_score": risk_score,
                "risk_flag": risk_flag
            }
        }
        
        # Write to Audit Log
        write_single_audit_log(response_data)
        
        return response_data
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def write_single_audit_log(result: dict):
    """Helper to append a single analysis transaction to the audit log."""
    audit_dir = "results"
    os.makedirs(audit_dir, exist_ok=True)
    audit_path = os.path.join(audit_dir, "audit_log.jsonl")
    try:
        with open(audit_path, "a", encoding="utf-8") as f:
            log_entry = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "source_file": result["filename"],
                "transaction_id": result["features"].get("transaction_id", "N/A"), # Or check fallback
                "validation_status": result["status"],
                "errors": "; ".join(result["errors"]) if result["errors"] else "",
                "risk_score": result["prediction"]["risk_score"],
                "risk_flag": result["prediction"]["risk_flag"]
            }
            # Fallback if ID wasn't structured inside features dictionary
            if log_entry["transaction_id"] == "N/A" and "ID" in result:
                log_entry["transaction_id"] = result["ID"]
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        logger.error(f"Failed to write single audit log: {e}")

@app.get("/api/stats")
async def get_dashboard_stats():
    """Returns aggregated system metrics for the frontend dashboard."""
    summary_path = os.path.join("results", "powerbi_summary.csv")
    if not os.path.exists(summary_path):
        return {
            "Total_Processed": 0,
            "Valid_Transactions": 0,
            "Invalid_Transactions": 0,
            "Requires_Review": 0,
            "Failure_Rate_Percent": 0.0,
            "Average_Risk_Score": 0.0,
            "Total_High_Risk_Flags": 0
        }
        
    try:
        df = pd.read_csv(summary_path)
        if df.empty:
            raise ValueError("Summary CSV is empty")
        
        # Convert first row to dictionary
        stats = df.iloc[0].to_dict()
        return stats
    except Exception as e:
        logger.error(f"Failed to read stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to load dashboard statistics")

@app.get("/api/history")
async def get_history():
    """Returns the last 15 processed transactions for the dashboard log."""
    csv_path = os.path.join("results", "results.csv")
    if not os.path.exists(csv_path):
        return []
    try:
        df = pd.read_csv(csv_path)
        # Take last 15 records, fill NaN with empty string
        df = df.tail(15).fillna("")
        records = df.to_dict(orient="records")
        # Return in reverse chronological order (newest first)
        return records[::-1]
    except Exception as e:
        logger.error(f"Failed to read history: {e}")
        raise HTTPException(status_code=500, detail="Failed to load transaction history")

# Serve the static frontend
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
os.makedirs(frontend_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    uvicorn.run("src.api.server:app", host="127.0.0.1", port=8000, reload=True)
