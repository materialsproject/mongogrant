import functools
import json
import types
import typing


class Config:
    def __init__(self, check: types.FunctionType, path: str,
                 seed: typing.Optional[dict] = None):
        """(Re-)initialize config file.

        Args:
            path (str): path to config file.
            check (types.FunctionType): function that takes a config dict
                and raises a ConfigError if config is improperly formatted.
            seed (typing.Optional[dict]): seed dict to (re)set config. Can pass
                None if valid config already exists at path.

        Raises:
            ConfigError: if seed config is improperly formatted.
        """
        self.path = path
        self.check = check
        if seed:
            self.save(seed)
        else:
            try:
                self.load()
            except Exception as e:
                raise ConfigError(
                    "Cannot load valid config from path. Check path or re-init "
                    "with seed. More info: {}".format(str(e)))

    @functools.lru_cache(maxsize=1)
    def load(self):
        """Load config from file

        Caches the config in memory to avoid having to open the file for every
        call. Cache clears on self.save().

        Returns:
            dict: config
        """
        with open(self.path) as f:
            config = json.load(f)
            self.check(config)
            return config

    def save(self, config):
        """Save config to file.

        Args:
            config (dict): config spec

        Raises:
            ConfigError: if config is improperly formatted.
        """
        self.check(config)
        with open(self.path, 'w') as f:
            self.load.cache_clear()
            json.dump(config, f, indent=2)


class ConfigError(Exception):
    pass
