import os

from flask import Flask, jsonify, request, Response

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
        return Response(result, status=403, content_type="application/json")
    else:
        return Response(result, status=418, content_type="application/json")


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
        user_email = server.email_from_fetch_token(token, expired_okay=True)
        if server.can_grant(user_email, host, db, role):
            return jsonify("Cannot grant. You are allowed to obtain auth credentials for this database, "
                           "but it looks like your token has expired. "
                           "Use `mgrant init` to refresh your token."), 403
        else:
            return jsonify("Cannot grant. Try getting new token, "
                           "or contact server admin."), 403

    return jsonify(grant)


@app.route('/setrule/<token>', methods=['POST'])
def set_rule(token: str):
    """Set allow/deny rule for user role on host db.

    Pass user email, host, db, role, and which as POST params.

    Args:
        token (str): fetch token of admin with ability to set allow/deny rules.

    Returns:
        dict: {"success": True} if successful, {"success": False} if not.
    """
    email = request.form.get("email")
    host = request.form.get("host")
    db = request.form.get("db")
    role = request.form.get("role")
    which = request.form.get("which")
    if (not email or not host or not db or role not in ("read", "readWrite")
            or which not in ("allow", "deny")):
        return jsonify("Missing valid user, host, db, role, and/or which"), 400

    ruler = server.get_ruler(token)
    if ruler is None:
        user_email = server.email_from_fetch_token(token, expired_okay=True)
        print(user_email)
        ruler_token_expired = (
            (user_email is not None) and
            (server.mgdb.rulers.count_documents({"email": email}) > 0)
        )
        if ruler_token_expired:
            return jsonify({
                "success": False,
                "error": ("Your are registered for admin rights, but your token has expired. "
                          "Use `mgrant init` to refresh your token.")
            })
        else:
            return jsonify({
                "success": False,
                "error": "Your token is not registered for admin rights."
            })
    if not (set(ruler.keys()) >= {"hosts", "dbs", "emails", "which"}):
        return jsonify({
            "success": False,
            "error": "Ruler doc malformed. Contact admin.",
        })
    if not (ruler["hosts"] == "all" or host in ruler["hosts"]):
        return jsonify({
            "success": False,
            "error": "Not allowed to set rules for {}".format(host),
        })
    if not (ruler["dbs"] == "all" or
            any(db.startswith(prefix) for prefix in ruler["dbs"])):
        return jsonify({
            "success": False,
            "error": "Not allowed to set rules for {}/{}".format(host, db),
        })
    if not (ruler["emails"] == "all" or
            any(email.endswith(suffix) for suffix in ruler["emails"])):
        return jsonify({
            "success": False,
            "error": "Not allowed to set rules for {} for {}/{}".format(
                email, host, db),
        })
    if not (ruler["which"] == "all" or which in ruler["which"]):
        return jsonify({
            "success": False,
            "error": "Not allowed to set {} rules for {} for {}/{}".format(
                which, email, host, db),
        })
    try:
        server.set_rule(email, host, db, role, which=which)
        return jsonify({"success": True})
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        })


if __name__ == '__main__':
    app.run(debug=True)
