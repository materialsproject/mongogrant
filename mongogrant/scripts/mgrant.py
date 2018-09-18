import json

import click
import requests

from mongogrant.client import Client

DEFAULT_ENDPOINT = 'https://grantmedb.materialsproject.org'
DEFAULT_HOST = 'mongodb03.nersc.gov'


@click.group()
def cli():
    """Run `mgrant init --help` to get started."""
    pass


@click.command()
@click.option('--endpoint', default=DEFAULT_ENDPOINT,
              help='auth server. default: "{}"'.format(DEFAULT_ENDPOINT))
@click.argument('email')
def init(endpoint, email):
    """Request a token.

    EMAIL: Your email address registered with your mongogrant administrator.
    """
    rv = requests.get("{}/gettoken/{}".format(endpoint, email))
    print(rv.json())
    print("Copy the fetch token from the link and run `mgrant settoken`.")


@click.command()
@click.option('--endpoint', default=DEFAULT_ENDPOINT,
              help='auth server. default: "{}"'.format(DEFAULT_ENDPOINT))
@click.argument('token')
def settoken(endpoint, token):
    """Set token for a remote"""
    client = Client()
    client.set_remote(endpoint, token)
    print("Remember that tokens expire. Run `mgrant init` to request "
          "a fresh token for an endpoint.")
    print("Run `mgrant db` to get credentials for a database.")


@click.command()
@click.argument('db')
@click.option('--role', default='read', help='"read" or "readWrite"')
@click.option('--host', default=DEFAULT_HOST, help='MongoDB host')
@click.option('--atomate_starters', is_flag=True, default=True,
              help='Print db.json and my_launchpad.yaml files')
def db(db, role, host, atomate_starters):
    """
    Get credentials for a database.

    Args:
        db: Database name. Ask your mongogrant administrator
    """
    if atomate_starters and role == 'read':
        print("Need '--role readWrite' for atomate credentials.")
        return
    client = Client()
    if atomate_starters:
        db_rw = client.db("{}:{}/{}".format(role, host, db))
        admin = client.get_auth(host, db, role)
        db_ro = client.db("{}:{}/{}".format("read", host, db))
        readonly = client.get_auth(host, db, "read")
        db_json = dict(
            host=host,
            database=db,
            collection="tasks",
            admin_user=admin['username'],
            admin_password=admin['password'],
            readonly_user=readonly['username'],
            readonly_password=readonly['password'],
            aliases={}
        )
        print(json.dumps(db_json, indent=2))
        my_launchpad = my_launchpad_template.format(
            host, db, admin['username'], admin['password'])
        print(my_launchpad)
    else:
        db_we = client.db("{}:{}/{}".format(role, host, db))
        print("Wrote credentials to ~/.mongogrant.json")


my_launchpad_template = """
host: {}
name: {}
username: {}
password: {}
ssl_ca_file: null
logdir: null
strm_lvl: INFO
user_indices: []
wf_user_indices: []
"""

cli.add_command(init)
cli.add_command(settoken)
cli.add_command(db)