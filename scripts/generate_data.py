import os

from src.pipeline.synthetic import DEFAULT_COUNT, DEFAULT_SEED, generate_dataset

RAW_DATA_DIR = os.path.join("data", "raw_xml")


def main(seed: int = DEFAULT_SEED, count: int = DEFAULT_COUNT):
    print("Generating synthetic supplier invoices...")
    # fixed seed: same files, same outcomes, same model
    outcomes = generate_dataset(RAW_DATA_DIR, count=count, seed=seed)
    print(
        f"Data generation complete. {len(outcomes)} XML files and outcomes.csv in {RAW_DATA_DIR}."
    )


if __name__ == "__main__":
    main()
