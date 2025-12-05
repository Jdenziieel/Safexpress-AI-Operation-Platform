"""File utility functions for I/O operations."""
import json
from datetime import datetime


def save_json(data, filename):
    """Save data to JSON file."""
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)
    print(f"[DEBUG] Saved {filename}")


def load_json(filename):
    """Load data from JSON file."""
    with open(filename, "r") as f:
        return json.load(f)


def generate_kb_filename(source_filename):
    """Generate unique knowledge base filename."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    base_name = source_filename.replace('.pdf', '')
    return f"kb_{timestamp}_{base_name}.json"
