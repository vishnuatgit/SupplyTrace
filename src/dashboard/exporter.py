import os
import pandas as pd
import logging

logger = logging.getLogger(__name__)

class DashboardExporter:
    """
    Aggregates the granular results into a clean, flat summary CSV
    optimized for native Power BI ingestion and visualization.
    """
    
    @staticmethod
    def export_summary(results_df: pd.DataFrame, output_path: str):
        """
        Creates a summary of the processed batch for the dashboard.
        """
        if results_df.empty:
            logger.warning("Empty dataframe provided to DashboardExporter. Skipping export.")
            return

        total_processed = len(results_df)
        
        # Calculate validation statuses
        valid_count = len(results_df[results_df['status'] == 'VALID'])
        invalid_count = len(results_df[results_df['status'] == 'INVALID'])
        review_count = len(results_df[results_df['status'] == 'REQUIRES_REVIEW'])
        
        # Calculate risk distributions (only considering rows where model actually predicted something numeric)
        # We need to filter out 'N/A' strings if the model didn't train
        numeric_risks = pd.to_numeric(results_df['risk_score'], errors='coerce').dropna()
        avg_risk_score = numeric_risks.mean() if not numeric_risks.empty else 0.0
        
        high_risk_flags = len(results_df[results_df['risk_flag'] == 'HIGH'])
        
        # Prepare the flat summary record
        summary = {
            "Total_Processed": total_processed,
            "Valid_Transactions": valid_count,
            "Invalid_Transactions": invalid_count,
            "Requires_Review": review_count,
            "Failure_Rate_Percent": round((invalid_count / total_processed) * 100, 2) if total_processed > 0 else 0,
            "Average_Risk_Score": round(avg_risk_score, 2),
            "Total_High_Risk_Flags": high_risk_flags
        }
        
        # Save to CSV
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        summary_df = pd.DataFrame([summary])
        summary_df.to_csv(output_path, index=False)
        logger.info(f"Dashboard summary exported successfully to {output_path}")
