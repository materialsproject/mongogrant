from abc import ABCMeta, abstractmethod
from copy import deepcopy
from datetime import datetime, timedelta
import functools
import os
import random
import typing

import re
from uuid import uuid4

import pymongo
import requests
from pymongo import MongoClient, DeleteOne, ReplaceOne
from pymongo.errors import DuplicateKeyError, OperationFailure

from mongogrant.config import ConfigError, Config


path = os.path.join(
    os.path.expanduser("~") or os.path.expanduser("~"), ".mongogrant.server.json"
)


def seed():
    """Initial config."""
    return {
        "mgdb_uri": "",
        "mailer": {
            "class": "",
            "kwargs": {},
        },
        "auth": {},
    }


def check(config: dict):
    """Verify config is properly formatted.

    Args:
        config (dict): config spec

    Raises:
        ConfigError: if config is improperly formatted.
    """
    if not set(config.keys()) >= {"mgdb_uri", "mailer", "auth"}:
        raise ConfigError("config missing one of "
                          "{mgdb_uri,mailer,auth} keys")
    if not (isinstance(config["mgdb_uri"], str) and
            isinstance(config["mailer"], dict) and
            isinstance(config["auth"], dict)):
        raise ConfigError("config field of wrong type")
    if not set(config["mailer"].keys()) >= {"class", "kwargs"}:
        raise ConfigError("mailer config missing fields")
    if config["mgdb_uri"]:
        if not re.match("mongodb://[^:]+:[^@]+@[^/]+/.+", config["mgdb_uri"]):
            raise ConfigError("mgdb_uri must be of form "
                              "mongodb://{username}:{password}@{host}/{db}")


class Server:
    def __init__(self, config: typing.Optional[Config] = None):
        """Grant host db role credentials to users by email verification.

        A server gets requests for auth tokens from clients. First, a client
        sends an email address to the server endpoint. Then, the server
        generates a one-time link and sends the link to the email address. Next,
        the client opens the link and stored the revealed auth token to its
        config. Finally, the client uses the server endpoint and token to
        request credentials.

        A server config stores (1) readWrite credentials for a db where it can
        manage tokens, credential grants to clients, and allow/deny rules; (2)
        config for sending mail; and (3) host admin credentials to manage
        user creation/deletion for dbs on those hosts.

        Args:
            config (Config): server configuration
        """
        self.cfg = config
        if config is None:
            try:
                self.cfg = Config(check=check, path=path)
            except ConfigError:
                self.cfg = Config(check=check, path=path, seed=seed())
        # XXX Tried combining @property and @lru_cache decorators for mgdb
        # et al., but couldn't call e.g. self.mgdb.cache_clear(), so using
        # private props for caching.
        self._mgdb = None
        self._mailer = None
        self._admin_client = {}

    def set_mgdb(self, uri):
        """Set mongogrant database URI.

        Args:
            uri (str): MongoDB URI string
        """
        config = self.cfg.load()
        config["mgdb_uri"] = uri
        self.cfg.save(config)
        self._mgdb = None

    @property
    def mgdb(self):
        """mongogrant database.

        Returns:
            pymongo.database.Database: server database
        """
        if self._mgdb is None:
            config = self.cfg.load()
            uri = config["mgdb_uri"]
            dbname = uri.split('/')[-1]
            self._mgdb = MongoClient(config["mgdb_uri"], connect=False)[dbname]
        return self._mgdb

    def set_mailer(self, cls, kwargs):
        """Set class with send(message) method and kwargs to init class.

        Class cls will be instantiated as cls(**kwargs). cls instance must have
        `send` method that takes {to,subject,text} args and sends an
        email to `to` with subject `subject` and body text `text`.

        Args:
            cls: mailer class
            kwargs: kwargs passed to created an instance of cls
        """
        config = self.cfg.load()
        config["mailer"]["class"] = "{}.{}".format(cls.__module__, cls.__name__)
        config["mailer"]["kwargs"] = kwargs
        self.cfg.save(config)
        self._mailer = None

    @property
    def mailer(self):
        """Mailer for email verification and delivering links to tokens.

        Returns:
            Mailer: something that can `send(to,subject,text)`
        """
        if self._mailer is None:
            mailconf = self.cfg.load()["mailer"]
            modname = ".".join(mailconf["class"].split('.')[:-1])
            clsname = mailconf["class"].split('.')[-1]
            cls = getattr(
                __import__(modname, globals(), locals(), [clsname], 0),
                clsname)
            self._mailer = cls(**mailconf["kwargs"])
        return self._mailer

    def set_admin_client(self, host: str, username: str, password: str):
        """Sets admin client auth info in config.

        Args:
            host (str): MongoDB host
            username (str): admin username
            password (str): admin password
        """
        config = self.cfg.load()
        config["auth"][host] = (
            "mongodb://{u}:{p}@{h}/{d}"
            .format(u=username, p=password, h=host, d="admin"))
        self.cfg.save(config)
        self._admin_client.pop(host, None)

    def admin_client(self, host):
        """Return host MongoClient authenticated as admin.

        Args:
            host (str): MongoDB host

        Returns:
            pymongo.mongo_client.MongoClient: host MongoClient as admin

        Raises:
            ConfigError: if authentication fails or cannot connect to host.
        """
        if host not in self._admin_client:
            config = self.cfg.load()
            try:
                client = MongoClient(config["auth"][host], connect=False,
                                     serverSelectionTimeoutMS=5000)
                client.server_info()
                self._admin_client[host] = client
            except pymongo.errors.OperationFailure as e:
                raise ConfigError("Auth error: {}".format(e))
            except pymongo.errors.ServerSelectionTimeoutError as e:
                return ConfigError("Cannot connect: {}".format(e))
        return self._admin_client[host]

    def set_rule(self, email: str, host: str, db: str, role: str,
                 which="allow"):
        """Allow/deny granting credentials for role on host db to email owner.

        Args:
            email (str): email address
            host (str): host name
            db (str): database name
            role (str): "read" or "readWrite"
            which (str): "allow" or "deny"
        """
        if role not in ("read", "readWrite"):
            raise ValueError("role must be one of {'read','readWrite'}")
        if which not in ("allow", "deny"):
            raise ValueError("which must be one of {'allow','deny'}")
        self.mgdb[which].update_one(dict(email=email, host=host, role=role),
                                    {"$addToSet": {"dbs": db}}, upsert=True)

    def get_ruler(self, token: str):
        """Get the spec for which allow/deny rules this token's owner can set.

        Args:
            token (str): fetch token

        Returns:
            bool: The ruler doc if the owner can set rules, None o/w
        """
        email = self.email_from_fetch_token(token)
        if email is None:
            return None
        return self.mgdb.rulers.find_one({"email": email})

    def can_grant(self, email: str, host: str, db: str, role: str):
        """Can the server grant credentials for role on host db to email owner?

        An email owner (with a token for that email) may obtain user/pass for
        role on host db if and only if both:
        (1) there is no deny rule that matches all of (email,host,db,role) or a
        subset, i.e. a deny rule for a "read" role also denies a "readWrite"
        role, and
        (2) there is an allow rule that matches all of (email,host,db,role) or a
        superset, i.e. an allow rule for a "readWrite" role also allows a "read"
        role.

        Args:
            email (str): email address
            host (str): host name
            db (str): database name
            role (str): "read" or "readWrite"

        Returns:
            bool: Whether server can grant requested credentials.
        """
        config = self.cfg.load()
        if host not in config["auth"]:
            return False

        base_filter = dict(email=email, host=host, dbs=db, role={"$in": [role]})
        allow_filter = deepcopy(base_filter)
        deny_filter = deepcopy(base_filter)
        if role == "read":
            allow_filter["role"]["$in"].append("readWrite")
        elif role == "readWrite":
            deny_filter["role"]["$in"].append("read")
        else:
            raise ValueError("role must be one of {'read','readWrite'}")
        return (not (self.mgdb.deny.count(deny_filter, limit=1) > 0) and
                self.mgdb.allow.count(allow_filter, limit=1) > 0)

    def grant(self, email: str, host: str, db: str, role: str):
        """Grant and return credentials for role on host db to email owner.

        Args:
            email (str): email address
            host (str): host name
            db (str): database name
            role (str): "read" or "readWrite"

        Returns:
            dict: {username,password} for role on host db if can grant, None
                otherwise.
        """
        if not self.can_grant(email, host, db, role):
            return None
        grant_filter = dict(email=email, host=host, db=db, role=role)
        command = ("updateUser" if self.mgdb.grants.count(grant_filter)
                   else "createUser")
        d = self.admin_client(host)[db]
        username = "{}_{}".format("_".join(email.split('@')), role)
        password = passphrase()
        try:
            d.command(command, username, pwd=password, roles=[role])
        except OperationFailure as e:
            if str(e) == "User {}@{} not found".format(username, db):
                # User erroneously in self.mgdb.grants collection
                command = "createUser"
                d.command(command, username, pwd=password, roles=[role])
        except DuplicateKeyError as e:
            # Trying to create user that already exists on db
            # and is not known to mongogrant. Leave alone.
            print(str(e))
            return None
        self.mgdb.grants.update_one(
            grant_filter, {"$set": dict(username=username)}, upsert=True)
        return dict(username=username, password=password)

    def revoke_grants(self, email: str,
                      host: str = "*", db: str = "*", role: str = "*"):
        """Revoke credential grants to email owner. Drop user(s) on host db(s).

        Any of host,db,role can be "*", i.e. a wildcard. For example, if host is
        "hostname" and db is "*" and role is "readWrite", revoke any readWrite
        credential grants for any db on "hostname".

        Args:
            email (str): email address
            host (str): host name, or "*" for all hosts
            db (str): database name, or "*" for all dbs
            role (str): "read", "readWrite" or "*" for all roles
        """
        grant_filter = dict(email=email, host=host, db=db, role=role)
        for field in ("host", "db", "role"):
            if grant_filter[field] == "*":
                grant_filter.pop(field)
        for doc in self.mgdb.grants.find(grant_filter):
            db = self.admin_client(doc["host"])[doc["db"]]
            db.command("dropUser", doc["username"])
        self.mgdb.grants.delete_many(grant_filter)

    def generate_tokens(self, email: str,
                        link_expires: str = "3 d", fetch_expires: str = "30 d"):
        """Generate link (to confirm email) and fetch (to grant auth) tokens.

        Generate tokens if there is at least one allow rule for email.

        Args:
            email (str): email address.
            link_expires (str): When, from now, link token expires. Format is
                "<n> <u>", where <u> is one of "s", "m", "h", or "d" for
                seconds, minutes, hours, or days, respectively. <n> is a number
                that will be cast to a float, so it can be e.g. "0.5".
            fetch_expires (str): When, from link_expires, fetch token expires.
                Format is same as link_expires.

        Returns:
            bool: True if tokens generated, False o/w.
        """
        if self.mgdb.allow.count(dict(email=email), limit=1) == 0:
            return False
        unit = dict(s="seconds", m="minutes", h="hours", d="days")
        n, u = link_expires.split(" ")
        link_expires = datetime.utcnow() + timedelta(**{unit[u]: float(n)})
        n, u = fetch_expires.split(" ")
        fetch_expires = link_expires + timedelta(**{unit[u]: float(n)})
        self.mgdb.tokens.update_one(
            dict(email=email),
            {"$push": {"fetch": dict(token=uuid4().hex, expires=fetch_expires),
                       "link": dict(token=uuid4().hex, expires=link_expires)}},
            upsert=True)
        self.delete_expired_tokens()
        return True

    def delete_expired_tokens(self):
        """Delete expired tokens. Also, remove docs with no tokens."""
        now = datetime.utcnow()
        bulk_requests = []
        docs = list(self.mgdb.tokens.find(
            {"$or": [{"link.expires": {"$lte": now}},
                     {"fetch.expires": {"$lte": now}},
                     {"link": [], "fetch": []}]}))
        for d in docs:
            if not d["link"] and not d["fetch"]:
                bulk_requests.append(DeleteOne(dict(_id=d["_id"])))
                continue
            link = []
            for t in d["link"]:
                if t["expires"] > now:
                    link.append(t)
            fetch = []
            for t in d["fetch"]:
                if t["expires"] > now:
                    fetch.append(t)
            if not link and not fetch:
                bulk_requests.append(DeleteOne(dict(_id=d["_id"])))
            else:
                bulk_requests.append(ReplaceOne(
                    dict(_id=d["_id"]),
                    dict(email=d["email"], link=link, fetch=fetch)
                ))
        if bulk_requests:
            self.mgdb.tokens.bulk_write(bulk_requests)

    def email_from_fetch_token(self, token: str, expired_okay: bool = False):
        """Retrieve email given fetch token.

        Args:
            token (str): fetch token
            expired_okay (bool): return email address even if user's token is expired.

        Returns:
            str: email address if fetch token not expired, None o/w.
        """
        when = datetime.min if expired_okay else datetime.utcnow()
        doc = self.mgdb.tokens.find_one({
            "fetch": {"$elemMatch": {"token": token,
                                     "expires": {"$gte": when}}}
        }, ["email"])
        if not doc:
            return None
        return doc["email"]

    def send_link_token_mail(self, email: str, secure: bool = False,
                             host: str = "localhost", dry_run: bool = False):
        """Send email to deliver fetch token via one-time link.

        Args:
            email (str): email address.
            secure (bool): whether link should use https or not.
            host (str): server host including port if not :80.
            dry_run (bool): whether to send mail or to return message text.

        Returns:
            str: "OK" if email sent, message text if dry_run, error message o/w.
        """
        generated = self.generate_tokens(email)
        if not generated:
            return ("Email {} not allowed by server. Contact server admin."
                    .format(email))
        doc = self.mgdb.tokens.find_one(dict(email=email), ["link"])
        if not doc:
            return ("Email {} allowed by server, but "
                    "error in generating token. Contact server admin")
        doc["link"].sort(key=lambda t: t["expires"])
        link_token = doc["link"][-1]["token"]
        link = "{}://{}/verifytoken/{}".format(
            "https" if secure else "http", host, link_token)
        text = ("Retrieve your mongogrant fetch token by opening this "
                "one-time link: {}".format(link))
        subject = "Mongogrant fetch token from {}".format(host)
        if not dry_run:
            self.mailer.send(to=email, subject=subject, text=text)
            return "OK"
        else:
            return text

    def fetch_token_from_link(self, link_token: str):
        """Retrieve fetch token given link token, and remove link token.

        Args:
            link_token (str): received via email link

        Returns:
            str: message with fetch token if link token is valid,
                error message o/w.
        """
        now  = datetime.utcnow()
        doc = self.mgdb.tokens.find_one({
            "link": {"$elemMatch": {"token": link_token,
                                    "expires": {"$gte": now}}}
        }, ["fetch"])
        if not doc:
            return "Link tokens expire. Request again."

        fetch = sorted(doc["fetch"], key=lambda t: t["expires"])[-1]
        self.mgdb.tokens.update_one(
            dict(_id=doc["_id"]), {"$pull": {"link": {"token": link_token}}})
        return "Fetch token: {} (expires {} UTC)".format(
            fetch["token"], fetch["expires"])

    def grant_with_token(self, token: str, host: str, db: str, role: str):
        """Attempt to grant user/pass for role on host db given token.

        Args:
            token (str): fetch token
            host (str): host name
            db (str): database name
            role (str): "read" or "readWrite"

        Returns:
            dict: {username,password} for role on host db if can grant, None
                otherwise.
        """
        email = self.email_from_fetch_token(token)
        if not email:
            return None
        return self.grant(email, host, db, role)


def passphrase(n=5, sep="-", wordspath="/usr/share/dict/words"):
    """Generate a passphrase: concatenate n random words with sep.

    Args:
        n (int): Number of words
        sep (str): word separator
        wordspath (str): path to file with one word per line.

    Returns:
        str: A passphrase
    """
    with open(wordspath) as f:
        lines = f.readlines()

    words = set(line.strip().lower() for line in lines)
    joined_words = sep.join(random.sample(words, n))
    # Strip single quote 
    joined_words = joined_words.replace("'", "")
    return joined_words


class Mailer(metaclass=ABCMeta):
    @abstractmethod
    def send(self, to, subject, text):
        """Email message.

        Args:
            to (str): email recipient
            subject (str): email subject line
            text (str): email body text

        Returns:
            bool: True if no client or server error, False o/w.
        """
        pass


class Mailgun(Mailer):
    def __init__(self, api_key, base_url, from_addr):
        """Use https://www.mailgun.com/ API to send mail.

        As of 2018-04-27, they give you a free sandbox domain to test sending
        mail (and any recipients must opt in), and the first 10k emails per
        month are free for registered domains.

        Args:
            api_key (str): Mailgun API key
            base_url (str): Base URL for Mailgun API for sender domain
            from_addr (str): sender email (should be @ sender domain)
        """
        self.api_key = api_key
        self.base_url = base_url
        self.from_addr = from_addr

    def send(self, to, subject, text):
        """Email message.

        Args:
            to (str): email recipient
            subject (str): email subject line
            text (str): email body text

        Returns:
            bool: True if no client or server error, False o/w.
        """
        response = requests.post(
            self.base_url + "/messages",
            auth=("api", self.api_key),
            data={"text": text,
                  "from": self.from_addr,
                  "to": to,
                  "subject": subject})
        return response.ok
