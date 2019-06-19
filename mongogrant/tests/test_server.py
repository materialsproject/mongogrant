import itertools
import os
import re
import tempfile
import time
from unittest import TestCase
from uuid import uuid4

import pymongo
from pymongo import MongoClient

from mongogrant.config import Config
from mongogrant.server import passphrase, check, seed, Server, Mailgun, Mailer
from mongogrant.tests.utils import MongodWithAuth


class TestServer(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mongod_with_auth = MongodWithAuth(port=27020)
        cls.mongod_with_auth.ensure()
        cls.mgdbname = "test_mgdb_" + uuid4().hex
        cls.admin_client_args = dict(
            host="localhost:27020", username="mongoadmin", password="mongoadminpass")
        cls.admin_client_uri = ("mongodb://{username}:{password}@{host}/admin"
                                .format(**cls.admin_client_args))
        cls.mgdb = MongoClient(cls.admin_client_uri)[cls.mgdbname]
        cls.mgdb.command("createUser", "mgserver",
                         pwd="mgserverpass", roles=["readWrite"])
        cls.mgdb_uri = ("mongodb://mgserver:mgserverpass@localhost:27020/{}"
                        .format(cls.mgdbname))
        mailer_domain = "sandboxb188bd08055c4a63be1b70bfe31a2a3c.mailgun.org"
        cls.config_mailer = {
            "class": "mongogrant.server.Mailgun",
            "kwargs": dict(
                api_key="key-a03a2f01918fd4132cc7ee09ccc941c3",
                base_url="https://api.mailgun.net/v3/{}".format(mailer_domain),
                from_addr="mongogrant@{}".format(mailer_domain)
            )}
        cls.test_email = "test-mongogrant@materialsproject.org"
        cls.test_dbname = "test_" + uuid4().hex

    @classmethod
    def tearDownClass(cls):
        cls.mgdb.command("dropDatabase")
        cls.mgdb.client.close()
        cls.mongod_with_auth.destroy()

    def setUp(self):
        _, self.config_path = tempfile.mkstemp()
        config = Config(check=check, path=self.config_path, seed=seed())
        self.server = Server(config)

    def tearDown(self):
        self.server.set_mgdb(self.mgdb_uri)
        for c in ("allow", "deny", "tokens", "grants"):
            self.server.mgdb.drop_collection(c)
        self.server.set_admin_client(**self.admin_client_args)
        self.server.admin_client("localhost:27020")[self.test_dbname].command(
            "dropAllUsersFromDatabase")
        self.server.admin_client("localhost:27020")[self.test_dbname].command(
            "dropDatabase")
        os.remove(self.config_path)

    def test_empty_init(self):
        os.environ["HOME"] = os.path.split(self.config_path)[0]
        self.assertTrue(Server().cfg is not None)

    def test_set_mgdb(self):
        self.server.set_mgdb(self.mgdb_uri)
        self.assertEqual(self.server.cfg.load()["mgdb_uri"], self.mgdb_uri)

    def test_mgdb(self):
        self.server.set_mgdb(self.mgdb_uri)
        self.assertIsInstance(self.mgdb, pymongo.database.Database)

    def test_set_mailer(self):
        self.server.set_mailer(Mailgun, self.config_mailer["kwargs"])
        self.assertIsInstance(self.server.mailer, Mailer)

    def test_mailer(self):
        self.server.set_mailer(Mailgun, self.config_mailer["kwargs"])
        self.assertTrue(
            self.server.mailer.send(
                to=self.test_email,
                subject="mongogrant test",
                text="Thank you for helping with the test."))

    def test_set_admin_client(self):
        host = self.admin_client_args["host"]
        self.server.set_admin_client(**self.admin_client_args)
        self.assertIsInstance(self.server.admin_client(host), MongoClient)

    def test_admin_client(self):
        host = self.admin_client_args["host"]
        username = self.admin_client_args["username"]
        self.server.set_admin_client(**self.admin_client_args)
        info = self.server.admin_client(host).admin.command(
            "usersInfo", dict(user=username, db="admin"))
        self.assertTrue(
            len([u for u in info["users"] if u["user"] == username and
                "root" in {r["role"] for r in u["roles"]}]))

    def test_set_rule(self):
        self.server.set_mgdb(self.mgdb_uri)
        self.assertRaises(
            ValueError, self.server.set_rule,
            self.test_email, "localhost:27020", self.test_dbname, "destroy")
        self.assertRaises(
            ValueError, self.server.set_rule,
            self.test_email, "localhost:27020", self.test_dbname, "read", "consider")
        self.server.set_rule(
            self.test_email, "localhost:27020", self.test_dbname, "read")
        self.assertTrue(
            self.server.mgdb.allow.count(dict(email=self.test_email)))

    def test_can_grant(self):
        self.server.set_mgdb(self.mgdb_uri)
        self.server.set_admin_client(**self.admin_client_args)
        self.server.set_rule(
            self.test_email, "localhost:27020", self.test_dbname, "read")
        self.assertTrue(self.server.can_grant(
            self.test_email, "localhost:27020", self.test_dbname, "read"))
        self.assertFalse(self.server.can_grant(
            self.test_email, "localhost:27020", self.test_dbname, "readWrite"))
        self.server.mgdb.allow.drop()
        self.server.set_rule(
            self.test_email, "localhost:27020", self.test_dbname, "readWrite")
        self.assertTrue(self.server.can_grant(
            self.test_email, "localhost:27020", self.test_dbname, "read"))

    def test_grant(self):
        self.server.set_mgdb(self.mgdb_uri)
        self.server.set_admin_client(**self.admin_client_args)
        self.server.set_rule(
            self.test_email, "localhost:27020", self.test_dbname, "read")
        self.assertTrue(self.server.grant(
            self.test_email, "localhost:27020", self.test_dbname, "read"))
        self.assertFalse(self.server.grant(
            self.test_email, "localhost:27020", self.test_dbname, "readWrite"))
        self.server.set_rule(
            self.test_email, "localhost:27020", self.test_dbname, "readWrite")
        self.assertTrue(self.server.grant(
            self.test_email, "localhost:27020", self.test_dbname, "readWrite"))
        self.server.set_rule(
            self.test_email, "localhost:27020", self.test_dbname, "readWrite", "deny")
        self.assertTrue(self.server.grant(
            self.test_email, "localhost:27020", self.test_dbname, "read"))
        self.assertFalse(self.server.grant(
            self.test_email, "localhost:27020", self.test_dbname, "readWrite"))

    def test_revoke_grants(self):
        self.server.set_mgdb(self.mgdb_uri)
        self.server.set_admin_client(**self.admin_client_args)
        self.server.set_rule(
            self.test_email, "localhost:27020", self.test_dbname, "read")
        granted = self.server.grant(
            self.test_email, "localhost:27020", self.test_dbname, "read")
        client = MongoClient("mongodb://{username}:{password}@localhost:27020/{db}"
                             .format(db=self.test_dbname, **granted))
        self.assertTrue(client.server_info())
        client.close()
        self.server.revoke_grants(self.test_email)
        client = MongoClient("mongodb://{username}:{password}@localhost:27020/{db}"
                             .format(db=self.test_dbname, **granted))
        self.assertRaises(pymongo.errors.OperationFailure, client.server_info)
        client.close()

    def test_generate_tokens(self):
        self.server.set_mgdb(self.mgdb_uri)
        self.assertFalse(self.server.generate_tokens(self.test_email))
        self.server.set_rule(
            self.test_email, "localhost:27020", self.test_dbname, "read")
        self.assertTrue(self.server.generate_tokens(self.test_email))

    def test_delete_expired_tokens(self):
        self.server.set_mgdb(self.mgdb_uri)
        self.server.set_rule(
            self.test_email, "localhost:27020", self.test_dbname, "read")
        self.server.generate_tokens(
            self.test_email, link_expires="0.1 s", fetch_expires="0.1 s")
        self.assertTrue(self.server.mgdb.tokens.count())
        time.sleep(0.2)
        self.server.delete_expired_tokens()
        self.assertFalse(self.server.mgdb.tokens.count())

    def test_email_from_fetch_token(self):
        self.server.set_mgdb(self.mgdb_uri)
        self.server.set_rule(
            self.test_email, "localhost:27020", self.test_dbname, "read")
        self.server.generate_tokens(self.test_email)
        doc = self.server.mgdb.tokens.find_one()
        fetch_token = doc["fetch"][0]["token"]
        self.assertEqual(
            self.server.email_from_fetch_token(fetch_token), self.test_email)

    def test_send_link_token_mail(self):
        self.server.set_mgdb(self.mgdb_uri)
        self.server.set_mailer(Mailgun, self.config_mailer["kwargs"])
        errmsg = self.server.send_link_token_mail(self.test_email)
        self.assertIn(self.test_email, errmsg)
        self.assertIn("not allowed by server", errmsg)
        self.server.set_rule(
            self.test_email, "localhost:27020", self.test_dbname, "read")
        self.assertEqual(self.server.send_link_token_mail(self.test_email),
                         "OK")

    def test_fetch_token_from_link(self):
        self.server.set_mgdb(self.mgdb_uri)
        self.server.set_rule(
            self.test_email, "localhost:27020", self.test_dbname, "read")
        self.server.generate_tokens(self.test_email)
        doc = self.server.mgdb.tokens.find_one()
        link_token = doc["link"][0]["token"]
        fetch_token = doc["fetch"][0]["token"]
        self.assertIn(
            fetch_token, self.server.fetch_token_from_link(link_token))
        self.assertNotIn(
            fetch_token, self.server.fetch_token_from_link(link_token))

    def test_grant_with_token(self):
        self.server.set_admin_client(**self.admin_client_args)
        self.server.set_mgdb(self.mgdb_uri)
        self.server.set_rule(
            self.test_email, "localhost:27020", self.test_dbname, "read")
        self.server.generate_tokens(self.test_email)
        doc = self.server.mgdb.tokens.find_one()
        fetch_token = doc["fetch"][0]["token"]
        self.assertFalse(self.server.grant_with_token(
            "shadytoken", "localhost:27020", self.test_dbname, "read"))
        self.assertTrue(self.server.grant_with_token(
            fetch_token, "localhost:27020", self.test_dbname, "read"))
        self.assertFalse(self.server.grant_with_token(
            fetch_token, "localhost:27020", self.test_dbname, "readWrite"))

    def test_passphrase(self):
        for (n, sep) in itertools.product((6, 5), ("-", " ", ".", ",", "_")):
            self.assertTrue(re.match("(\w+\{}){{{}}}\w+".format(sep, n - 1),
                                     passphrase(n, sep)))
