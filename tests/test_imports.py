def test_modules_importable():
    import src
    import src.ingestion
    import src.validation
    import src.features
    import src.prediction
    import src.dashboard
    import src.utils
    
    assert True, "All base modules imported successfully."
