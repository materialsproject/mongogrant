import re
import typing
from uuid import uuid4

import os
import pymongo
import requests
from pymongo import MongoClient

from mongogrant.config import Config, ConfigError


path = os.path.join(os.getenv("HOME") or os.path.expanduser("~"), ".mongogrant.json")


def seed():
    """Initial config."""
    return {
        "fetch": {
            "remotes": [],
            "host_aliases": {},
            "db_aliases": {},
        },
        "auth": [],
    }


def check(config):
    """Verify config is properly formatted.

    Args:
        config (dict): config spec

    Raises:
        ConfigError: if config is improperly formatted.
    """
    fetch = config["fetch"]
    auth = config["auth"]
    if not set(config.keys()) >= {"fetch", "auth"}:
        raise ConfigError("config missing fetch and auth keys")
    if not set(fetch.keys()) >= {"remotes", "host_aliases", "db_aliases"}:
        raise ConfigError("fetch config missing fields")
    if not (isinstance(fetch["remotes"], list) and
            isinstance(fetch["host_aliases"], dict) and
            isinstance(fetch["db_aliases"], dict)):
        raise ConfigError("fetch config field of wrong type")
    if not (isinstance(auth, list) and
            all(set(a.keys()) == {'host', 'db', 'role', 'username',
                                  'password'}
                for a in auth)):
        raise ConfigError("auth config of wrong type")


class Client:
    def __init__(self, config: typing.Optional[Config] = None):
        """Get/set config for remotes, aliases, and auth.

        Args:
            config (Config): client configuration
        """
        self.cfg = config
        if config is None:
            try:
                self.cfg = Config(check=check, path=path)
            except ConfigError:
                self.cfg = Config(check=check, path=path, seed=seed())

    def set_remote(self, endpoint: str, token: str):
        """Set endpoint URL and auth token to retrieve database credentials.

        Args:
            endpoint (str): URL of server endpoint
            token (str): used to authenticate with server
        """
        config = self.cfg.load()
        rems = config["fetch"]["remotes"]
        for r in rems:
            if r["endpoint"] == endpoint:
                r["token"] = token
                break
        else:
            if endpoint.endswith("/"):
                endpoint = endpoint[:-1]
            rems.append(dict(endpoint=endpoint, token=token))
        self.cfg.save(config)

    def remotes(self):
        """Get list of remotes.

        Returns:
            list: of dicts, each with `endpoint` and `token` keys.
        """
        return self.cfg.load()["fetch"]["remotes"]

    def set_alias(self, alias: str, actual: str, which="host"):
        """Set alias for host or db so that e.g. FQDNs needn't be hard-coded.

        Args:
            alias (str): Nickname for host or db, e.g. "dev", "prod", etc.
            actual (str): Actual name of host or db, e.g. "server.example.com".
            which (str): "host" or "db".
        """
        config = self.cfg.load()
        config["fetch"]["{}_aliases".format(which)][alias] = actual
        self.cfg.save(config)

    def aliases(self, which="host"):
        """Get mapping of host_aliases or db_aliases (key->alias, value->actual).

        Args:
            which (str): "host" or "db"

        Returns:
            dict: mapping of alias to actual value.
        """
        return self.cfg.load()["fetch"]["{}_aliases".format(which)]

    @classmethod
    def check_auth(cls, auth: dict):
        """Check auth info for host db role credentials.

        Args:
            auth (dict): config spec

        Raises:
            AuthError: If authentication fails, if read role can write, or if
                readWrite role cannot write.
        """
        kwargs = dict(
            host=auth["host"],
            username=auth["username"],
            password=auth["password"],
            authSource=auth["db"],
        )
        client = MongoClient(**kwargs)
        db = client[auth["db"]]
        cname = "test_{}".format(uuid4())
        try:
            db[cname].insert_one({"test": 1})
            db.drop_collection(cname)
            if auth["role"] == "read":
                raise AuthError("Read-only user can write to database")
        except pymongo.errors.OperationFailure:
            if auth["role"] == "readWrite":
                raise AuthError("Read-write user cannot write to database")

    def set_auth(self, host: str, db: str, role: str,
                 username: str, password: str, check=False):
        """Set auth info for role (read-only or read-write) on host db.

        Args:
            host (str): Host name, e.g. "my.server.com", "my.server.com:27018".
                Port 27017 is assumed unless otherwise specified.
            db (str): Database name on host.
            role (str): one of {"read", "readWrite"}.
            username (str): User for host db.
            password (str): Password for host db.
            check (bool): Whether to validate the auth info, i.e. try to connect
                to db and verify role.
        Raises:
            AuthError: If authentication fails, if read role can write, or if
                readWrite role cannot write.
        """
        auth = dict(
            host=host, db=db, role=role, username=username, password=password)
        if check:
            self.check_auth(auth)
        config = self.cfg.load()
        for a in config["auth"]:
            if a["host"] == host and a["db"] == db and a["role"] == role:
                a["username"] = username
                a["password"] = password
                break
        else:
            config["auth"].append(auth)
        self.cfg.save(config)

    def get_auth(self, host: str, db: str, role: str, as_uri=False):
        """Get auth credentials for role on host db.

        Args:
            host (str): Host name, e.g. "my.server.com", "my.server.com:27018".
                Port 27017 is assumed unless otherwise specified. Can also pass
                a host alias.
            db (str): Database name on host. Can also pass a db alias.
            role (str): one of {"read", "readWrite"} or aliases {"ro", "rw"}.
            as_uri (bool): format return value as MongoDB URI string.

        Returns:
            dict: of {host,db,role,user,password}, or MongoDB URI of type str,
                if auth entry exists. Returns None otherwise.
        """
        config = self.cfg.load()
        hosts, dbs = self.aliases("host"), self.aliases("db")
        if host in hosts:
            host = hosts[host]
        if db in dbs:
            db = dbs[db]
        if role == "ro":
            role = "read"
        elif role == "rw":
            role = "readWrite"
        elif role not in {"read", "readWrite"}:
            raise ValueError("role not in {'read', 'readWrite'}")
        for a in config["auth"]:
            if a["host"] == host and a["db"] == db and a["role"] == role:
                if as_uri:
                    return ("mongodb://{username}:{password}@{host}/{db}"
                            .format(**a))
                else:
                    return a
        print("No credentials for {}:{}/{} found in local config"
              .format(role, host, db))
        for remote in self.remotes():
            print("Requesting credentials from {}".format(remote["endpoint"]))
            url = "{endpoint}/grant/{token}".format(**remote)
            rv = requests.post(url, dict(host=host, db=db, role=role))
            if rv.status_code == 200:
                d = rv.json()
                print("Found credentials. Saving to local config...")
                self.set_auth(host, db, role, d["username"], d["password"],
                              check=True)
                return self.get_auth(host, db, role)
            else:
                print("{}".format(rv.json()))
        return None

    def db(self, spec: str, **mongoclient_kwargs):
        """Get a pymongo Database object from a spec "<role>:<host>/<db>."

        Args:
            spec (str): of the format <role>:<host>/<db>, where: role is one of
                {"read", "readWrite"} or aliases {"ro", "rw"}; host is a db host
                (w/ optional port) or alias; and db is a db on that host,
                or alias.
            mongoclient_kwargs (dict): Extra keyword arguments to pass to
                invocation of MongoClient.

        Returns:
            pymongo.database.Database: from spec

        Raises:
            AuthError: If no valid auth credentials are available from local
                config or via remotes to connect to database.
        """
        auth = self.get_db_auth_from_spec(spec)
        return MongoClient(**dict(**auth, **mongoclient_kwargs))[auth["authSource"]]

    def get_db_auth_from_spec(self, spec: str):
        """Read the Mongo authentication information from a spec "<role>:<host>/<db>."
        Args:
            spec (str): of the format <role>:<host>/<db>, where: role is one of
                {"read", "readWrite"} or aliases {"ro", "rw"}; host is a db host
                (w/ optional port) or alias; and db is a db on that host,
                or alias.
        Returns:
            dict: authentication information from spec

        """
        role, host_db = spec.split(':', 1)
        host, dbname_or_alias = host_db.split('/', 1)
        auth = self.get_auth(host, dbname_or_alias, role)
        if auth is None:
            raise AuthError("No valid auth credentials are accessible, either from "
                            "local config or via remotes, to connect to "
                            "database.")
        auth = auth.copy()
        dbname = auth["db"]
        auth["authSource"] = dbname
        auth.pop("db")
        auth.pop("role")
        return auth

class AuthError(Exception):
    pass
