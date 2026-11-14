# Loads Nestor's settings: defaults from config.example.yaml, overridden by the user's own config.yaml
import os
import yaml
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_DIR, "config.yaml")
EXAMPLE_PATH = os.path.join(PROJECT_DIR, "config.example.yaml")
CACHE_DIR = os.path.join(PROJECT_DIR, "cache")

# Read one YAML file into a dict (empty if the file is missing or blank)
def read_yaml(path):
    # A missing file just means no settings from it
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as yaml_file:
        return yaml.safe_load(yaml_file) or {}

# Return all settings, with config.yaml values replacing the example defaults
def load_config():
    settings = read_yaml(EXAMPLE_PATH)
    settings.update(read_yaml(CONFIG_PATH))
    return settings
