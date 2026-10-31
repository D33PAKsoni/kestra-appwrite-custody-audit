"""Exercise authentication and cleanup without making any network requests."""

import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_export import fetch_export, NoRedirect


class Response:
    def __init__(self, payload):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.payload[:limit]


class FakeOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("Unexpected network request.")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def config():
    return {
        "APPWRITE_ENDPOINT": "https://fictional.appwrite.invalid/v1",
        "APPWRITE_PROJECT_ID": "fictional-project",
        "APPWRITE_AUDIT_FUNCTION_ID": "fictional-audit",
        "APPWRITE_AUDIT_EMAIL": "automation@example.invalid",
        "APPWRITE_AUDIT_PASSWORD": "fictional-secret-password",
        "APPWRITE_API_KEY": "must-never-be-sent",
    }


def export_fixture():
    return json.loads((ROOT / "fixtures" / "clean-ready.json").read_text(encoding="utf-8"))


def execution(data=None, **updates):
    result = {"status": "completed", "responseStatusCode": 200,
              "responseBody": json.dumps(export_fixture() if data is None else data)}
    result.update(updates)
    return result


def success_opener(data=None):
    return FakeOpener(Response({"$id": "fictional-session"}),
                      Response({"jwt": "fictional-jwt"}),
                      Response(execution(data)), Response(None))


def header(request, name):
    return {key.lower(): value for key, value in request.header_items()}.get(name.lower())


class ExportTransportTests(unittest.TestCase):
    def test_default_execution_uses_separate_cookie_free_jwt_transport(self):
        jwt_transport = FakeOpener(Response(execution()))
        session_transport = FakeOpener(Response({'$id':'fictional-session'}),
                                       Response({'jwt':'fictional-jwt'}), Response(None))
        handlers_seen = []
        def factory(*handlers):
            handlers_seen.append(handlers)
            return session_transport if any(isinstance(h, urllib.request.HTTPCookieProcessor) for h in handlers) else jwt_transport
        with patch('fetch_export.urllib.request.build_opener', side_effect=factory):
            self.assertTrue(fetch_export(config())['complete'])
        self.assertEqual(len(jwt_transport.requests),1)
        self.assertEqual(header(jwt_transport.requests[0],'X-Appwrite-JWT'),'fictional-jwt')
        self.assertEqual(len(session_transport.requests),3)
        self.assertTrue(all(header(r,'X-Appwrite-JWT') is None for r in session_transport.requests))
        self.assertFalse(any(isinstance(h,urllib.request.HTTPCookieProcessor) for h in handlers_seen[0]))

    def test_login_jwt_execution_and_cleanup_use_correct_authentication(self):
        opener = success_opener()
        result = fetch_export(config(), opener)
        self.assertEqual(result["samples"][0]["id"], "water-001")
        self.assertEqual([request.method for request in opener.requests], ["POST", "POST", "POST", "DELETE"])
        self.assertEqual([request.full_url.rsplit("/v1", 1)[1] for request in opener.requests], [
            "/account/sessions/email", "/account/jwts", "/functions/fictional-audit/executions",
            "/account/sessions/current"])
        login = json.loads(opener.requests[0].data)
        self.assertEqual(login, {"email": config()["APPWRITE_AUDIT_EMAIL"],
                                 "password": config()["APPWRITE_AUDIT_PASSWORD"]})
        execute = opener.requests[2]
        self.assertEqual(header(execute, "X-Appwrite-JWT"), "fictional-jwt")
        self.assertEqual(json.loads(execute.data), {
            "body": "", "async": False, "path": "/export", "method": "GET", "headers": {}})
        for request in opener.requests:
            self.assertEqual(header(request, "X-Appwrite-Project"), "fictional-project")
            self.assertIsNone(header(request, "X-Appwrite-Key"))
            self.assertNotIn(b"must-never-be-sent", request.data or b"")
            if request is not execute:
                self.assertIsNone(header(request, "X-Appwrite-JWT"))
        self.assertEqual(opener.responses, [])

    def test_incomplete_export_is_returned_without_upgrading_completeness(self):
        data = export_fixture()
        data.update(complete=False, issues=[{"code": "CONCURRENT_CHANGE", "message": "Fictional change."}])
        result = fetch_export(config(), success_opener(data))
        self.assertIs(result["complete"], False)
        self.assertEqual(result["issues"], data["issues"])

    def test_non_https_remote_endpoints_are_rejected_before_login(self):
        for endpoint in ("http://remote.invalid/v1", "ftp://remote.invalid/v1", "http://127.0.0.1/v1"):
            with self.subTest(endpoint=endpoint):
                cfg = config()
                cfg["APPWRITE_ENDPOINT"] = endpoint
                opener = FakeOpener()
                with self.assertRaises(ValueError):
                    fetch_export(cfg, opener)
                self.assertEqual(opener.requests, [])

    def test_local_http_requires_explicit_loopback_override(self):
        cfg = config()
        cfg.update(APPWRITE_ENDPOINT="http://127.0.0.1:8080/v1", ALLOW_LOCAL_HTTP="true")
        opener = success_opener()
        self.assertTrue(fetch_export(cfg, opener)["complete"])
        self.assertTrue(all(request.full_url.startswith("http://127.0.0.1:8080/v1/") for request in opener.requests))
        cfg["APPWRITE_ENDPOINT"] = "http://remote.invalid/v1"
        with self.assertRaises(ValueError):
            fetch_export(cfg, FakeOpener())

    def test_endpoint_credentials_and_query_parameters_are_rejected(self):
        for endpoint in ("https://user:secret@remote.invalid/v1", "https://remote.invalid/v1?token=secret",
                         "https://remote.invalid/v1#secret"):
            with self.subTest(endpoint=endpoint):
                cfg = config()
                cfg["APPWRITE_ENDPOINT"] = endpoint
                with self.assertRaises(ValueError):
                    fetch_export(cfg, FakeOpener())

    def test_invalid_function_id_is_rejected_before_login(self):
        for function_id in ("../labrelay_api", "valid/execute", "", ".invalid", "a" * 37):
            with self.subTest(function_id=function_id):
                cfg = config()
                cfg["APPWRITE_AUDIT_FUNCTION_ID"] = function_id
                opener = FakeOpener()
                with self.assertRaises(ValueError):
                    fetch_export(cfg, opener)
                self.assertEqual(opener.requests, [])

    def test_failed_execution_still_deletes_login_session(self):
        opener = FakeOpener(Response({}), Response({"jwt": "fictional-jwt"}),
                            Response(execution(status="failed", responseStatusCode=403)), Response(None))
        with self.assertRaisesRegex(RuntimeError, "Audit Function failed"):
            fetch_export(config(), opener)
        self.assertEqual(opener.requests[-1].method, "DELETE")
        self.assertEqual(opener.responses, [])

    def test_failed_jwt_request_is_redacted_and_cleans_up_session(self):
        error = urllib.error.HTTPError("https://fictional.invalid", 401, "password=fictional-secret-password",
                                       {}, io.BytesIO(b"private response fictional-secret-password"))
        opener = FakeOpener(Response({}), error, Response(None))
        with self.assertRaises(RuntimeError) as captured:
            fetch_export(config(), opener)
        self.assertIn("HTTP 401", str(captured.exception))
        self.assertNotIn("fictional-secret-password", str(captured.exception))
        self.assertNotIn("private response", str(captured.exception))
        self.assertEqual(opener.requests[-1].method, "DELETE")

    def test_network_failure_is_redacted_and_cleans_up_session(self):
        opener = FakeOpener(Response({}), Response({"jwt": "fictional-jwt"}),
                            urllib.error.URLError("fictional-secret-password"), Response(None))
        with self.assertRaisesRegex(RuntimeError, "connection failed") as captured:
            fetch_export(config(), opener)
        self.assertNotIn("fictional-secret-password", str(captured.exception))
        self.assertEqual(opener.requests[-1].method, "DELETE")

    def test_cleanup_failure_is_reported_instead_of_claiming_success(self):
        opener = FakeOpener(Response({}), Response({"jwt": "fictional-jwt"}), Response(execution()),
                            urllib.error.URLError("private cleanup details"))
        with self.assertRaisesRegex(RuntimeError, "session cleanup failed") as captured:
            fetch_export(config(), opener)
        self.assertNotIn("private cleanup details", str(captured.exception))

    def test_bad_export_envelope_fails_and_deletes_session(self):
        cases = []
        data = export_fixture()
        data["schemaVersion"] = 99
        cases.append(data)
        data = export_fixture()
        data["complete"] = "true"
        cases.append(data)
        data = export_fixture()
        data["samples"] = {}
        cases.append(data)
        data = export_fixture()
        del data["orgId"]
        cases.append(data)
        for data in cases:
            with self.subTest(changed=data):
                opener = success_opener(data)
                with self.assertRaises(ValueError):
                    fetch_export(config(), opener)
                self.assertEqual(opener.requests[-1].method, "DELETE")
                self.assertEqual(opener.responses, [])

    def test_failed_login_does_not_attempt_to_delete_an_uncreated_session(self):
        opener = FakeOpener(urllib.error.HTTPError("https://fictional.invalid", 401, "Denied", {}, io.BytesIO()))
        with self.assertRaises(RuntimeError):
            fetch_export(config(), opener)
        self.assertEqual(len(opener.requests), 1)

    def test_oversized_export_response_fails_and_still_cleans_up(self):
        opener = FakeOpener(Response({}), Response({"jwt": "fictional-jwt"}),
                            Response(b"x" * 8_000_001), Response(None))
        with self.assertRaisesRegex(RuntimeError, "8 MB safety limit"):
            fetch_export(config(), opener)
        self.assertEqual(opener.requests[-1].method, "DELETE")

    def test_redirect_handler_does_not_forward_credentials(self):
        with self.assertRaisesRegex(RuntimeError, "redirects are disabled"):
            NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://unrelated.invalid")


if __name__ == "__main__":
    unittest.main()
