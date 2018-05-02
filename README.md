Mongogrant is a utility to grant username and password
credentials for read and readWrite roles on various databases
on various hosts to owners of email addresses.

A server administrator has fine-grained control via
allow/deny rules for granting tokens and credentials.
People request an email that contains a one-time link. That
link gives a user a fetch token. All tokens expire and
expiration time is customizable. People then use the
mongogrant client to make requests like

```python
from mongogrant.client import Client

# config file on disk has tokens and host/db aliases
# `Client()` with no args looks to
# ~/.mongogrant.json for config
client = Client()
# pymongo.database.Database with read role
source_db = client.db("ro:dev/core")
# readWrite role. config stores "staging" host alias
# and "core" db alias
target_db = client.db("rw:staging/core")

# ...Do database stuff!
```

You can run a "server" on your laptop in a Jupyer notebook
and manage allow/deny rules, grant / revoke grants of
credentials, etc. A small Flask app (**untested** so far)
is included as an example for deploying a server to which
clients can connect to obtain tokens and credentials. 

## Set up a server

```python
from mongogrant.config import Config
from mongogrant.server import Server, check, path, seed, Mailgun

server = Server(Config(check=check, path=path, seed=seed()))
server.set_mgdb("mongodb://mgserver:mgserverpass@my.host.com/mongogrant")
server.set_mailer(Mailgun, dict(
    api_key="YOUR_KEY",
    base_url="https://api.mailgun.net/v3/YOUR_DOMAIN",
    from_addr="mongogrant@YOUR_DOMAIN"))
server.set_admin_client(
    host="other1.host.com",
    username="mongoadmin",
    password="mongoadminpass")
server.set_admin_client(
    host="other2.host.com",
    username="mongoadmin",
    password="mongoadminpass")
```
