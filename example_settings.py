"""
Example settings file for use with sample Flask app.

Example usage:
$ MONGOGRANT_SETTINGS=example_settings.py \
    gunicorn -w 4 -b 0.0.0.0:10000 mongogrant.app:app
"""

import os

from mongogrant.config import Config, ConfigError
from mongogrant.server import check, path, seed

SERVER_CONFIG_CHECK = check
SERVER_CONFIG_PATH = path
if os.path.exists(SERVER_CONFIG_PATH):
    try:
        Config(check=SERVER_CONFIG_CHECK, path=SERVER_CONFIG_PATH)
        SERVER_CONFIG_SEED = None
    except ConfigError:
        SERVER_CONFIG_SEED = seed
else:
    SERVER_CONFIG_SEED = seed