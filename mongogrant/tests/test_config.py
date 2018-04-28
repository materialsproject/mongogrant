import os
import tempfile
from unittest import TestCase

from mongogrant.config import Config, ConfigError


class TestConfig(TestCase):
    def setUp(self):
        _, self.config_path = tempfile.mkstemp()
        self.good_seed = {"req_list_field": []}
        self.bad_seed = {"foo": "bar"}

        def check(config):
            if not ("req_list_field" in config and
                    isinstance(config["req_list_field"], list)):
                raise ConfigError("bad config")
        self.check = check

    def tearDown(self):
        os.remove(self.config_path)

    def test_init(self):
        self.assertRaises(ConfigError, lambda c, l: Config(c, l),
                          self.check, self.config_path)
        self.assertTrue(Config(self.check, self.config_path, self.good_seed))
        self.assertRaises(ConfigError, lambda c, l, s: Config(c, l, s),
                          self.check, self.config_path, self.bad_seed)
        self.assertTrue(Config(self.check, self.config_path))

    def test_load(self):
        cfg = Config(self.check, self.config_path, self.good_seed)
        self.assertTrue(cfg.load())

    def test_save(self):
        cfg = Config(self.check, self.config_path, self.good_seed)
        config = cfg.load()
        config["req_list_field"].append(3)
        cfg.save(config)
        self.assertEqual(cfg.load()["req_list_field"][-1], 3)
