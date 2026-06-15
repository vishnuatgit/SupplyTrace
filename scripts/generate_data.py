import os

DATA_DIR = os.path.join("data", "raw_xml")

def generate_sample_xml(filename: str, content: str):
    os.makedirs(DATA_DIR, exist_ok=True)
    file_path = os.path.join(DATA_DIR, filename)
    with open(file_path, "w") as f:
        f.write(content)
        
def run():
    print("Generating synthetic XML data...")
    
    # Valid XMLs
    for i in range(1, 6):
        content = f"<invoice><id>INV-00{i}</id><amount>{i * 100}</amount></invoice>"
        generate_sample_xml(f"valid_{i}.xml", content)
        
    # Invalid XMLs (Missing ID)
    for i in range(6, 8):
        content = f"<invoice><id></id><amount>{i * 100}</amount></invoice>"
        generate_sample_xml(f"invalid_missing_id_{i}.xml", content)
        
    # Invalid XMLs (Empty Amount)
    for i in range(8, 10):
        content = f"<invoice><id>INV-00{i}</id><amount></amount></invoice>"
        generate_sample_xml(f"invalid_empty_amount_{i}.xml", content)
        
    # Requires Review (High amount)
    content = f"<invoice><id>INV-010</id><amount>5000000</amount></invoice>"
    generate_sample_xml("review_high_amount_10.xml", content)

    print("Data generation complete. 10 XML files generated.")

if __name__ == "__main__":
    run()
