"""Fetch the separate Appwrite companion export; never use a database API key."""
import http.cookiejar
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Appwrite redirects are disabled; configure its exact API endpoint.")


def fetch_export(config, opener=None):
    endpoint = config["APPWRITE_ENDPOINT"].rstrip("/")
    parsed = urllib.parse.urlsplit(endpoint)
    local_test = config.get("ALLOW_LOCAL_HTTP") == "true" and parsed.hostname in ("127.0.0.1", "localhost")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
        raise ValueError("Configure an Appwrite API endpoint without embedded credentials or query parameters.")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local_test):
        raise ValueError("Appwrite HTTPS is required (loopback HTTP is only for explicit local tests).")
    function_id = config["APPWRITE_AUDIT_FUNCTION_ID"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,35}", function_id):
        raise ValueError("Invalid audit Function ID.")
    project_id = config["APPWRITE_PROJECT_ID"]
    # Appwrite rejects requests carrying both JWT and session cookie. Keep the
    # JWT execution transport separate from the login/session-cleanup jar.
    jwt_opener = opener or urllib.request.build_opener(NoRedirect())
    opener = opener or urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), NoRedirect())

    logged_in = False

    def request(method, path, body=None, jwt=None):
        nonlocal logged_in
        headers = {"X-Appwrite-Project": project_id, "Content-Type": "application/json"}
        if jwt:
            headers["X-Appwrite-JWT"] = jwt
        req = urllib.request.Request(endpoint + path,
            data=None if body is None else json.dumps(body).encode(), headers=headers, method=method)
        try:
            with (jwt_opener if jwt else opener).open(req, timeout=180) as response:
                if path == "/account/sessions/email":
                    # Revoke a successful login even when its response body is malformed.
                    logged_in = True
                raw = response.read(8_000_001)
        except urllib.error.HTTPError as error:
            try:
                error_type = json.loads(error.read(65536)).get('type', 'unknown')
                if not isinstance(error_type, str) or not re.fullmatch(r'[a-zA-Z0-9_]{1,100}', error_type):
                    error_type = 'unknown'
            except Exception:
                error_type = 'unknown'
            raise RuntimeError(f"Appwrite {method} {path} request failed (HTTP {error.code}, type {error_type}); check configuration and permissions.") from None
        except urllib.error.URLError:
            raise RuntimeError("Appwrite connection failed; check endpoint and network access.") from None
        if len(raw) > 8_000_000:
            raise RuntimeError("Export response exceeded the 8 MB safety limit; reduce the audit scope.")
        return json.loads(raw) if raw else None

    try:
        request("POST", "/account/sessions/email", {
            "email": config["APPWRITE_AUDIT_EMAIL"], "password": config["APPWRITE_AUDIT_PASSWORD"]})
        logged_in = True
        jwt = request("POST", "/account/jwts", {})["jwt"]
        if not isinstance(jwt, str) or not jwt:
            raise ValueError("Appwrite returned an invalid JWT envelope.")
        execution = request("POST", f"/functions/{function_id}/executions", {
            "body": "", "async": False, "path": "/export", "method": "GET", "headers": {}}, jwt=jwt)
        if execution.get("status") != "completed" or execution.get("responseStatusCode") != 200:
            raise RuntimeError("Audit Function failed; inspect its private execution in Appwrite.")
        export = json.loads(execution["responseBody"])
        if not isinstance(export, dict) or type(export.get("schemaVersion")) is not int or export["schemaVersion"] != 1 or \
                type(export.get("complete")) is not bool or not isinstance(export.get("orgId"), str) or not export["orgId"]:
            raise ValueError("Unsupported or incomplete audit export envelope.")
        for key in ("samples", "events", "handoffs", "receipts", "batches", "issues"):
            if not isinstance(export.get(key), list):
                raise ValueError(f"Audit export requires a {key} array.")
        return export
    finally:
        if logged_in:
            try:
                request("DELETE", "/account/sessions/current")
            except Exception:
                raise RuntimeError("Audit session cleanup failed; revoke the automation account's remaining session in Appwrite.") from None


def main():
    from kestra import Kestra
    data = fetch_export(os.environ)
    Path("export.json").write_text(json.dumps(data), encoding="utf-8")
    Kestra.outputs({"complete": data["complete"], "sampleCount": len(data["samples"])})


if __name__ == "__main__":
    main()
