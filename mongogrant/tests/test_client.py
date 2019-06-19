import tempfile
from unittest import TestCase

import os
from uuid import uuid4

import pymongo
from pymongo import MongoClient

from mongogrant.client import Client, check, seed
from mongogrant.config import Config
from mongogrant.tests.utils import MongodWithAuth


class TestClient(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mongod_with_auth = MongodWithAuth(port=27020)
        cls.mongod_with_auth.ensure()
        _, cls.config_path = tempfile.mkstemp()
        cls.dbname = "test_" + uuid4().hex
        cls.db = MongoClient(
            "mongodb://mongoadmin:mongoadminpass@localhost:27020/admin")[cls.dbname]
        cls.db.command("createUser", "reader", pwd="readerpass", roles=["read"])
        cls.db.command("createUser", "writer",
                       pwd="writerpass", roles=["readWrite"])

    @classmethod
    def tearDownClass(cls):
        os.remove(cls.config_path)
        cls.db.command("dropDatabase")
        cls.db.client.close()
        cls.mongod_with_auth.destroy()

    def setUp(self):
        config = Config(check=check, path=self.config_path, seed=seed())
        self.client = Client(config)

    def test_empty_init(self):
        os.environ["HOME"] = os.path.split(self.config_path)[0]
        self.assertTrue(Client().cfg is not None)

    def test_remotes(self):
        self.assertEqual(len(self.client.remotes()), 0)
        self.client.set_remote("ep1", "tk1")
        self.assertIn(dict(endpoint="ep1", token="tk1"), self.client.remotes())
        self.client.set_remote("ep1", "tk0")
        self.client.set_remote("ep2", "tk2")
        remotes = self.client.remotes()
        self.assertIn(dict(endpoint="ep1", token="tk0"), remotes)
        self.assertIn(dict(endpoint="ep2", token="tk2"), remotes)
        self.assertNotIn(dict(endpoint="ep1", token="tk1"), remotes)

    def test_aliases(self):
        self.assertEqual(len(self.client.aliases()), 0)
        h_alias = "dev"
        h_actual = "my.example.com"
        self.client.set_alias(h_alias, h_actual)
        self.assertIn(h_alias, self.client.aliases())
        self.assertTrue(h_actual, self.client.aliases()[h_alias])
        self.client.set_alias("h_alt_alias", h_actual)
        self.assertTrue(h_actual, self.client.aliases()["h_alt_alias"])
        d_alias = "core"
        d_actual = "the_best_db"
        self.client.set_alias(d_alias, d_actual, which="db")
        self.assertIn(d_alias, self.client.aliases("db"))
        self.assertTrue(d_actual, self.client.aliases("db")[d_alias])

    def test_auth(self):
        host = "my.example.com"
        db = "the_best_db"
        user_ro, user_rw = "user_ro", "user_rw"
        pass_ro, pass_rw = "pass_ro", "pass_rw"
        self.client.set_auth(host, db, "read", user_ro, pass_ro)
        self.client.set_auth(host, db, "readWrite", user_rw, pass_rw)
        self.assertTrue(self.client.get_auth(host, db, "read"))
        self.assertTrue(self.client.get_auth(host, db, "readWrite"))
        self.client.set_alias("dev", host, "host")
        auth = self.client.get_auth("dev", db, "read")
        self.assertEqual(auth["host"], host)
        self.client.set_alias("core", "the_best_db", "db")
        auth = self.client.get_auth("dev", "core", "read")
        self.assertEqual(auth["host"], host)

    def test_db(self):
        self.client.set_auth("localhost:27020", self.dbname, "read", "reader",
                             "readerpass", check=True)
        self.client.set_auth("localhost:27020", self.dbname, "readWrite", "writer",
                             "writerpass", check=True)
        self.client.set_alias("dev", "localhost:27020", "host")
        self.client.set_alias("core", self.dbname, "db")
        self.assertTrue(self.client.get_auth("dev", "core", "ro"))
        db = self.client.db("ro:dev/core")
        self.assertIsInstance(db, pymongo.database.Database)
        self.assertRaises(pymongo.errors.OperationFailure,
                          db.collection.insert_one, {"a": 1})
        db = self.client.db("rw:dev/core")
        db.collection.insert_one({"a": 1})
        self.assertTrue(db.collection.find_one({"a": 1}))
