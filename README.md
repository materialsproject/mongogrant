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

# No config yet? Set one up with at least one remote for fetching credentials
# See below for how to obtain <FETCH_TOKEN> for a given <ENDPOINT>.
client.set_remote("https://grantmedb.materialsproject.org", "<FETCH_TOKEN>")

# Set some aliases if you'd like:
client.set_alias("dev", "mongodb03.nersc.gov", "host")
client.set_alias("prod", "mongodb04.nersc.gov", "host")
client.set_alias("fireworks", "fw_dw_phonons", "db")

# pymongo.database.Database with read role
source_db = client.db("ro:dev/fireworks")
# readWrite role: config stores "prod" host alias and "fireworks" db alias
target_db = client.db("rw:prod/fireworks")

# ...Do database stuff!
```

One can also go entirely through a running app's API:

```bash
> # Using the HTTPie command line HTTP client (https://httpie.org/)
> # Install via `{brew,apt-get,pip,...} install httpie`
> http GET https://grantmedb.materialsproject.org/gettoken/<YOUR_EMAIL>
HTTP/1.1 200 OK
Connection: keep-alive
Content-Length: 59
Content-Type: application/json
Date: Thu, 17 May 2018 18:05:30 GMT
Server: nginx/1.10.3

{
    "msg": "Sent link to <YOUR_EMAIL> to retrieve token."
}

> http GET https://grantmedb.materialsproject.org/verifytoken/<VERIFY_TOKEN>
HTTP/1.1 200 OK
Connection: keep-alive
Content-Encoding: gzip
Content-Type: text/html; charset=utf-8
Date: Thu, 17 May 2018 18:06:17 GMT
Server: nginx/1.10.3
Transfer-Encoding: chunked

Fetch token: <FETCH_TOKEN> (expires 2018-06-19 18:05:30.508000 UTC)

> # end-of-line "\" below only necessary if command spans two lines.
> http --form POST https://grantmedb.materialsproject.org/grant/<FETCH_TOKEN> \
>   role=readWrite host=mongodb03.nersc.gov db=dw_phonons
HTTP/1.1 200 OK
Connection: keep-alive
Content-Length: 108
Content-Type: application/json
Date: Thu, 17 May 2018 18:11:22 GMT
Server: nginx/1.10.3

{
    "password": "<PASSWORD>",
    "username": "dwinston_lbl.gov_readWrite"
}

>
```

You can run a "server" on your laptop in a Jupyer notebook
and manage allow/deny rules, grant / revoke grants of
credentials, etc. A small Flask app
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
