# Loads Nestor's settings: defaults from config.example.yaml, overridden by the user's own config.yaml
import os
import yaml
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_DIR, "config.yaml")
EXAMPLE_PATH = os.path.join(PROJECT_DIR, "config.example.yaml")
CACHE_DIR = os.path.join(PROJECT_DIR, "cache")
DATA_DIR = os.path.join(PROJECT_DIR, "data")  # State that should survive a restart, e.g. alerts held overnight
SECRETS_PATH = os.path.join(PROJECT_DIR, ".env")  # API keys (gitignored)

# Read the KEY=value lines in .env (Nestor's own keys, kept out of git); empty if the file is missing. Nestor reads
# them from here rather than from the environment, so it never picks up another app's key by mistake.
def load_secrets():
    secrets = {}

    # No file, no keys
    if not os.path.exists(SECRETS_PATH):
        return secrets
    with open(SECRETS_PATH, encoding="utf-8") as secrets_file:
        # One KEY=value per line; blank lines and # comments are skipped
        for line in secrets_file:
            line = line.strip()

            # Only real settings
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                secrets[key.strip()] = value.strip().strip("\"'")
    return secrets

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
