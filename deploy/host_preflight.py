"""Collect a read-only inventory before installing Autofever on a shared host."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
import stat
import subprocess
from pathlib import Path


def _command(argv: list[str]) -> tuple[int | None, str]:
    """Run a bounded read-only inventory command; never expose raw errors."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None, ""
    return result.returncode, (result.stdout + "\n" + result.stderr).strip()


def _version(argv: list[str]) -> str | None:
    code, output = _command(argv)
    if code != 0 or not output:
        return None
    return output.splitlines()[0][:160]


def _memory_bytes() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _disk_inventory() -> list[dict[str, int | str | None]]:
    rows = []
    for path in ("/", "/opt", "/var/lib", "/etc"):
        try:
            usage = shutil.disk_usage(path)
            rows.append({"path": path, "total_bytes": usage.total,
                         "used_bytes": usage.used, "free_bytes": usage.free})
        except OSError:
            rows.append({"path": path, "total_bytes": None,
                         "used_bytes": None, "free_bytes": None})
    return rows


def _managed_path_inventory() -> list[dict[str, int | str | bool | None]]:
    rows = []
    for raw_path in (
        "/opt/028-autofever", "/var/lib/028-autofever", "/etc/028-autofever",
    ):
        path = Path(raw_path)
        try:
            info = path.stat(follow_symlinks=False)
            rows.append({"path": raw_path, "exists": True,
                         "directory": stat.S_ISDIR(info.st_mode),
                         "symlink": stat.S_ISLNK(info.st_mode),
                         "mode": oct(info.st_mode & 0o777),
                         "uid": info.st_uid, "gid": info.st_gid})
        except FileNotFoundError:
            rows.append({"path": raw_path, "exists": False, "directory": None,
                         "symlink": None,
                         "mode": None, "uid": None, "gid": None})
        except OSError:
            rows.append({"path": raw_path, "exists": None, "directory": None,
                         "symlink": None,
                         "mode": None, "uid": None, "gid": None})
    return rows


def _listener_inventory(port: int) -> dict[str, object]:
    code, output = _command(["ss", "-H", "-ltn", f"sport = :{port}"])
    if code is None or code != 0:
        return {"candidate_port": port, "status": "unknown", "local_endpoints": []}
    endpoints = []
    lines = output.splitlines()
    for line in lines:
        fields = line.split()
        if len(fields) >= 4:
            endpoint = fields[3]
            if (len(endpoint) <= 255 and endpoint.endswith(f":{port}")
                    and re.fullmatch(r"[\w.*:%\[\]-]+", endpoint)):
                endpoints.append(endpoint)
    return {
        "candidate_port": port,
        "status": ("listener_seen" if endpoints else
                   "unknown" if lines else "no_listener_seen_at_snapshot"),
        "local_endpoints": sorted(set(endpoints)),
    }


def _active_relevant_units() -> list[str] | None:
    code, output = _command([
        "systemctl", "list-units", "--type=service", "--state=running",
        "--no-legend", "--no-pager",
    ])
    if code is None or code != 0:
        return None
    relevant = re.compile(r"(?:013|hire|autofever|caddy|nginx|traefik|haproxy)", re.I)
    return sorted({line.split()[0] for line in output.splitlines()
                   if line.split() and relevant.search(line.split()[0])})


def collect_inventory(port: int = 28028) -> dict[str, object]:
    if not 1024 <= port <= 65535:
        raise ValueError("candidate port must be between 1024 and 65535")

    try:
        os_release = platform.freedesktop_os_release()
        operating_system = os_release.get("PRETTY_NAME", "Linux")
    except (AttributeError, OSError):
        operating_system = platform.system() or "unknown"

    proxy_versions = {}
    for name, argv in (
        ("caddy", ["caddy", "version"]),
        ("nginx", ["nginx", "-v"]),
        ("traefik", ["traefik", "version"]),
        ("haproxy", ["haproxy", "-v"]),
    ):
        proxy_versions[name] = _version(argv)

    return {
        "report_type": "read-only shared-host inventory",
        "purpose": "Preparation only; this is not deployment or host acceptance.",
        "host": {
            "hostname": socket.gethostname(),
            "operating_system": operating_system,
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "cpu_count": os.cpu_count(),
            "memory_bytes": _memory_bytes(),
        },
        "runtime": {
            "systemd": _version(["systemctl", "--version"]),
            "candidate_reverse_proxy_versions": proxy_versions,
            "relevant_running_service_units": _active_relevant_units(),
        },
        "storage": {
            "filesystems": _disk_inventory(),
            "autofever_paths": _managed_path_inventory(),
        },
        "network": _listener_inventory(port),
        "safety": {
            "configuration_contents_read": False,
            "secret_values_read": False,
            "files_or_services_modified": False,
            "external_connections_made": False,
            "port_check_is_only_a_snapshot": True,
        },
        "operator_review_required": [
            "Confirm this is the existing 013-hire-ai host using the provider console.",
            "Verify the actual Hire.ai service, proxy routes, DNS, firewall and health baseline.",
            "Resolve port, path, domain, ownership and capacity choices before any installation.",
            "Validate the complete existing proxy configuration before adding an Autofever site.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=28028,
                        help="candidate loopback port to inspect (default: 28028)")
    args = parser.parse_args()
    try:
        report = collect_inventory(args.port)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
