import unittest
from pathlib import Path
from unittest.mock import patch

from deploy import host_preflight


class DeploymentPreflightTests(unittest.TestCase):
    def test_opt_in_worker_unit_uses_systemd_credentials_and_explicit_send_mode(self):
        repo = Path(__file__).resolve().parents[2]
        unit_path = repo / "deploy" / "028-autofever-worker.service"
        unit = unit_path.read_text(encoding="utf-8")
        self.assertIn("LoadCredential=store-key:/etc/028-autofever/store-key", unit)
        self.assertIn("LoadCredential=smtp-password:/etc/028-autofever/smtp-password", unit)
        self.assertIn("LoadCredential=smtp-config:/etc/028-autofever/smtp.json", unit)
        self.assertIn("--store-key-file ${CREDENTIALS_DIRECTORY}/store-key", unit)
        self.assertIn("--smtp-password-file ${CREDENTIALS_DIRECTORY}/smtp-password", unit)
        self.assertIn("--smtp-config ${CREDENTIALS_DIRECTORY}/smtp-config", unit)
        self.assertIn("--send --continuous --poll-seconds 5", unit)
        self.assertIn("User=autofever", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("UMask=0077", unit)
        self.assertIn("ReadWritePaths=/var/lib/028-autofever", unit)
        self.assertNotIn("AUTOFEVER_SMTP_PASSWORD=", unit)
        self.assertNotIn("AUTOFEVER_STORE_KEY_HEX=", unit)

    def test_candidate_port_is_validated_without_running_commands(self):
        with patch.object(host_preflight, "_command") as command:
            with self.assertRaises(ValueError):
                host_preflight.collect_inventory(80)
        command.assert_not_called()

    def test_listener_query_reports_only_local_endpoints_and_snapshot_status(self):
        with patch.object(host_preflight, "_command", return_value=(0,
                "LISTEN 0 128 127.0.0.1:28028 0.0.0.0:*\n")) as command:
            result = host_preflight._listener_inventory(28028)
        command.assert_called_once_with(["ss", "-H", "-ltn", "sport = :28028"])
        self.assertEqual(result, {
            "candidate_port": 28028,
            "status": "listener_seen",
            "local_endpoints": ["127.0.0.1:28028"],
        })

    def test_missing_socket_inspection_is_unknown_not_available(self):
        with patch.object(host_preflight, "_command", return_value=(None, "")):
            result = host_preflight._listener_inventory(28028)
        self.assertEqual(result["status"], "unknown")

    def test_ipv6_listener_is_detected_and_unparseable_output_fails_closed(self):
        with patch.object(host_preflight, "_command", return_value=(0,
                "LISTEN 0 128 [::]:28028 [::]:*\n")):
            result = host_preflight._listener_inventory(28028)
        self.assertEqual(result["status"], "listener_seen")
        self.assertEqual(result["local_endpoints"], ["[::]:28028"])

        with patch.object(host_preflight, "_command", return_value=(0, "unexpected format\n")):
            result = host_preflight._listener_inventory(28028)
        self.assertEqual(result["status"], "unknown")

    def test_report_declares_read_only_scope_and_requires_operator_review(self):
        with patch.object(host_preflight, "_command", return_value=(None, "")), \
                patch.object(host_preflight, "_memory_bytes", return_value=None), \
                patch.object(host_preflight, "_disk_inventory", return_value=[]), \
                patch.object(host_preflight, "_managed_path_inventory", return_value=[]):
            result = host_preflight.collect_inventory()
        self.assertFalse(result["safety"]["configuration_contents_read"])
        self.assertFalse(result["safety"]["secret_values_read"])
        self.assertFalse(result["safety"]["files_or_services_modified"])
        self.assertTrue(result["safety"]["port_check_is_only_a_snapshot"])
        self.assertTrue(result["operator_review_required"])


if __name__ == "__main__":
    unittest.main()
