import os

from flask import Flask, jsonify, request

from mongogrant.config import Config
from mongogrant.server import Server, check, path

app = Flask(__name__)

default_settings = dict(
    DEBUG=False,
    TESTING=False,
    SERVER_CONFIG_PATH=path,
    SERVER_CONFIG_SEED=None,
    SERVER_CONFIG_CHECK=check,
)

app.config.from_object(default_settings)
app.config.from_envvar("MONGOGRANT_SETTINGS")
server = Server(Config(check=app.config["SERVER_CONFIG_CHECK"],
                       path=app.config["SERVER_CONFIG_PATH"],
                       seed=app.config["SERVER_CONFIG_SEED"]))


@app.route('/gettoken/<email>')
def get_token(email: str):
    """Send one-time link to email to retrieve token. Return status.

    Args:
        email (str): user email address

    Returns:
        str: Status of request (email sent, or error)
    """
    result = server.send_link_token_mail(
        email, secure=request.is_secure, host=request.host)
    if result == "OK":
        return jsonify(msg="Sent link to {} to retrieve token.".format(email))
    elif "not allowed by server" in result:
        return jsonify(result, status=403)
    else:
        return jsonify(result, status=418)


@app.route('/verifytoken/<token>')
def verify_token(token: str):
    """Verify link token and show message with fetch token, or error message.

    Args:
        token (str): link token

    Returns:
        str: show fetch token if link token is valid, or error message.
    """
    return server.fetch_token_from_link(token)


@app.route('/grant/<token>', methods=['POST'])
def grant_credentials(token: str):
    """Grant user/pass for role on host db given token.

    Pass role, host, and db as POST params

    Args:
        token (str): fetch token

    Returns:
        dict: user/pass if granted, None o/w.
    """
    host = request.form.get("host")
    db = request.form.get("db")
    role = request.form.get("role")
    if not host or not db or role not in ("read", "readWrite"):
        return jsonify("Missing valid host, db, and/or role"), 400

    grant = server.grant_with_token(token, host, db, role)
    if not grant:
        return jsonify("Cannot grant. Try getting new token, "
                       "or contact server admin."), 403

    return jsonify(grant)


if __name__ == '__main__':
    app.run()
