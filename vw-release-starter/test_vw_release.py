"""离线验证边界；使用模拟 Docker 响应，不连接任何服务器。"""
import contextlib
import io
import json
import subprocess
import unittest
from unittest.mock import patch

import vw_release


class StatusTests(unittest.TestCase):
    def run_status(self, responses):
        output = io.StringIO()
        with patch("vw_release.subprocess.run", side_effect=responses) as run:
            with contextlib.redirect_stdout(output):
                code = vw_release.main(["status"])
        return code, json.loads(output.getvalue()), run.call_args_list

    def response(self, stdout="", code=0, stderr=""):
        return subprocess.CompletedProcess([], code, stdout, stderr)

    def test_stopped_container_is_not_compatibility_pass_and_secrets_are_omitted(self):
        info = {
            "image_ref": "example/vaultwarden:latest",
            "image_id": "sha256:" + "a" * 64,
            "state": "exited", "health": None, "ports_configured": {},
            "mounts": [
                {"Type": "bind", "Source": "/test/data", "Destination": "/data", "RW": True},
                {"Type": "bind", "Source": "/private-config", "Destination": "/config", "RW": False},
            ],
            "unexpected_environment": {"ADMIN_TOKEN": "DO_NOT_PRINT_THIS"},
        }
        code, report, calls = self.run_status([
            self.response("vaultwarden\n"), self.response(json.dumps(info)),
        ])
        self.assertEqual(code, 0)  # 仅表示采集成功，停止状态照实输出。
        self.assertEqual(report["production"]["state"], "exited")
        self.assertEqual(report["compatibility"], "NOT_TESTED")
        self.assertIsNone(report["production"]["health"])
        self.assertFalse(report["production"]["image_reference_uses_digest"])
        self.assertFalse(report["candidate"]["exists"])
        self.assertEqual(len(report["production"]["data_mounts"]), 1)
        self.assertNotIn("DO_NOT_PRINT_THIS", json.dumps(report))
        self.assertNotIn("/private-config", json.dumps(report))
        for call in calls:
            argv = call.args[0]
            self.assertEqual(argv[:3], vw_release.DOCKER)
            self.assertIn(argv[3:5], [["container", "ls"], ["container", "inspect"]])
            self.assertNotIn(".Config.Env", " ".join(argv))

    def test_docker_failure_is_not_reported_as_missing_container(self):
        code, report, _ = self.run_status([
            self.response(code=1, stderr="AUTH_SECRET_SHOULD_NOT_BE_PRINTED"),
        ])
        self.assertEqual(code, 1)
        self.assertFalse(report["read_ok"])
        self.assertNotIn("production", report)
        self.assertNotIn("AUTH_SECRET", json.dumps(report))

    def test_missing_production_is_an_error(self):
        code, report, _ = self.run_status([self.response("")])
        self.assertEqual(code, 1)
        self.assertFalse(report["production"]["exists"])

    def test_invalid_response_fails_closed(self):
        for body in ["not JSON", "{}", "[]"]:
            with self.subTest(body=body):
                code, report, _ = self.run_status([
                    self.response("vaultwarden\n"), self.response(body),
                ])
                self.assertEqual(code, 1)
                self.assertEqual(report["compatibility"], "NOT_TESTED")

    def test_missing_cli_and_timeout_are_handled(self):
        for failure in [FileNotFoundError(), subprocess.TimeoutExpired("docker", 15)]:
            with self.subTest(failure=type(failure).__name__):
                code, report, _ = self.run_status([failure])
                self.assertEqual(code, 1)
                self.assertFalse(report["read_ok"])

    def test_unimplemented_deploy_never_calls_docker(self):
        with patch("vw_release.subprocess.run") as run:
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exc:
                    vw_release.main(["deploy", "example-release"])
            self.assertEqual(exc.exception.code, 2)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
