import os
import pandas as pd
from src.dashboard.exporter import DashboardExporter

def test_dashboard_export(tmpdir):
    # Mock some data
    data = {
        'status': ['VALID', 'INVALID', 'VALID', 'REQUIRES_REVIEW'],
        'risk_score': [10.5, 85.0, 'N/A', 65.5],
        'risk_flag': ['LOW', 'HIGH', 'N/A', 'HIGH']
    }
    df = pd.DataFrame(data)
    
    output_file = os.path.join(tmpdir, "powerbi_summary.csv")
    
    DashboardExporter.export_summary(df, output_file)
    
    assert os.path.exists(output_file)
    
    # Verify contents
    summary_df = pd.read_csv(output_file)
    assert len(summary_df) == 1
    
    # 4 total records
    assert summary_df.iloc[0]['Total_Processed'] == 4
    assert summary_df.iloc[0]['Valid_Transactions'] == 2
    assert summary_df.iloc[0]['Invalid_Transactions'] == 1
    assert summary_df.iloc[0]['Requires_Review'] == 1
    
    # 1 invalid out of 4 = 25% failure rate
    assert summary_df.iloc[0]['Failure_Rate_Percent'] == 25.0
    
    # average of 10.5, 85.0, 65.5 = 53.67
    assert summary_df.iloc[0]['Average_Risk_Score'] == 53.67
    
    # 2 high risk flags
    assert summary_df.iloc[0]['Total_High_Risk_Flags'] == 2
