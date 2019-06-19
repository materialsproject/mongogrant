import os
import re
import tempfile
from unittest import TestCase

from mongogrant.config import Config
from mongogrant.server import Mailgun, Server
from mongogrant.tests.test_server import TestServer


class TestApp(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.testserver = TestServer()
        cls.testserver.setUpClass()

    @classmethod
    def tearDownClass(cls):
        cls.testserver.tearDownClass()

    def setUp(self):
        self.testserver.setUp()
        _, self.settings_path = tempfile.mkstemp()
        settings = (
            "from mongogrant.server import check, seed\n" +
            "SERVER_CONFIG_CHECK = check\n" +
            "SERVER_CONFIG_PATH = '{}'\n".format(self.testserver.config_path) +
            "SERVER_CONFIG_SEED = seed()\n"
        )
        with open(self.settings_path, 'w') as f:
            f.write(settings)
        os.environ['MONGOGRANT_SETTINGS'] = self.settings_path
        from mongogrant import app # XXX Import after MONGOGRANT_SETTINGS set
        app.app.config.from_envvar("MONGOGRANT_SETTINGS")
        app.server = Server(Config(check=app.app.config["SERVER_CONFIG_CHECK"],
                               path=app.app.config["SERVER_CONFIG_PATH"],
                               seed=app.app.config["SERVER_CONFIG_SEED"]))
        app.app.config['TESTING'] = True
        self.app = app
        app.server.set_mgdb(self.testserver.mgdb_uri)
        app.server.set_mailer(Mailgun, self.testserver.config_mailer["kwargs"])
        app.server.set_rule(
            self.testserver.test_email,
            "localhost:27020", self.testserver.test_dbname, "read")
        self.client = app.app.test_client()

    def tearDown(self):
        self.testserver.tearDown()

    def test_get_token(self):
        email_no = "nope." + self.testserver.test_email
        email_yes = self.testserver.test_email
        rv = self.client.get('/gettoken/{}'.format(email_no))
        self.assertIn("not allowed by server", str(rv.data))
        rv = self.client.get('/gettoken/{}'.format(email_yes))
        self.assertIn("Sent link to", str(rv.data))

    def test_verify_token(self):
        text = self.app.server.send_link_token_mail(
            self.testserver.test_email, dry_run=True)
        url = re.search(r"(/verifytoken/[^\s]+)", text).group(1)
        rv = self.client.get(url)
        self.assertIn("Fetch token: ", str(rv.data))

    def test_grant_credentials(self):
        self.app.server.set_admin_client(**self.testserver.admin_client_args)
        self.app.server.generate_tokens(self.testserver.test_email)
        doc = self.app.server.mgdb.tokens.find_one({"email": self.testserver.test_email})
        fetch_token = doc["fetch"][0]["token"]
        rv = self.client.post(
            "/grant/shadytoken",
            data=dict(host="localhost:27020",
                      db=self.testserver.test_dbname,
                      role="read"))
        self.assertIn("Cannot grant", str(rv.data))
        rv = self.client.post(
            "/grant/{}".format(fetch_token),
            data=dict(host="localhost:27020",
                      db=self.testserver.test_dbname,
                      role="read"))
        print(rv)
        self.assertIn("username", rv.get_json())
        self.assertIn("password", rv.get_json())
        rv = self.client.post(
            "/grant/{}".format(fetch_token),
            data=dict(host="localhost:27020",
                      db=self.testserver.test_dbname,
                      role="readWrite"))
        self.assertIn("Cannot grant", str(rv.data))
