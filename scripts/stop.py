#!/usr/bin/env python3
"""
Anima Project Stop Script (Cross-platform)
Usage: python scripts/stop.py [options]
"""

import os
import sys
import time
import platform
import subprocess
import argparse
from pathlib import Path


# ===========================
# Colors and Output
# ===========================

class Colors:
    """ANSI color codes"""
    CYAN = '\033[0;36m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[0;33m'
    RED = '\033[0;31m'
    MAGENTA = '\033[0;35m'
    NC = '\033[0m'  # No Color

    @staticmethod
    def enabled():
        """Check if colors are supported"""
        return platform.system() != "Windows" or os.getenv('TERM')


def info(msg):
    print(f"{Colors.CYAN}[INFO]{Colors.NC} {msg}" if Colors.enabled() else f"[INFO] {msg}")

def success(msg):
    print(f"{Colors.GREEN}[SUCCESS]{Colors.NC} {msg}" if Colors.enabled() else f"[SUCCESS] {msg}")

def warn(msg):
    print(f"{Colors.YELLOW}[WARNING]{Colors.NC} {msg}" if Colors.enabled() else f"[WARNING] {msg}")

def error(msg):
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}" if Colors.enabled() else f"[ERROR] {msg}")


# ===========================
# Process Management
# ===========================

class ProcessManager:
    """Cross-platform process management"""

    def __init__(self):
        self.is_windows = platform.system() == "Windows"

    def find_processes_on_port(self, port):
        """Find process IDs listening on a port"""
        pids = []

        if self.is_windows:
            # Windows: use Get-NetTCPConnection
            try:
                ps_script = f"""
                Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue |
                    Where-Object {{ $_.State -eq "Listen" }} |
                    Select-Object -ExpandProperty OwningProcess
                """
                result = subprocess.run(
                    ['powershell', '-Command', ps_script],
                    capture_output=True,
                    text=True,
                    check=True
                )
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if line and line.isdigit():
                        pid = int(line)
                        if pid not in pids:
                            pids.append(pid)
            except (subprocess.CalledProcessError, FileNotFoundError):
                # Fallback to netstat
                try:
                    result = subprocess.run(
                        ['netstat', '-ano'],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    for line in result.stdout.split('\n'):
                        if f':{port}' in line and 'LISTENING' in line:
                            parts = line.split()
                            if len(parts) >= 5:
                                pid = int(parts[-1])
                                if pid not in pids:
                                    pids.append(pid)
                except subprocess.CalledProcessError:
                    pass
        else:
            # Unix: use lsof
            try:
                result = subprocess.run(
                    ['lsof', '-ti', f':{port}'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                pids = [int(pid.strip()) for pid in result.stdout.split('\n') if pid.strip()]
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

        return pids

    def stop_process(self, pid, service_name):
        """Stop a process by PID"""
        if not pid:
            return False

        try:
            if self.is_windows:
                # Try Stop-Process first
                try:
                    subprocess.run(
                        ['powershell', '-Command', f'Stop-Process -Id {pid} -Force'],
                        check=True,
                        capture_output=True
                    )
                except:
                    # Fallback to taskkill
                    subprocess.run(['taskkill', '/F', '/PID', str(pid)], check=True, capture_output=True)
            else:
                # Unix: try SIGTERM first, then SIGKILL
                try:
                    subprocess.run(['kill', str(pid)], check=True, capture_output=True)

                    # Wait for graceful shutdown
                    for _ in range(5):
                        time.sleep(1)
                        try:
                            os.kill(pid, 0)  # Check if process exists
                        except OSError:
                            success(f"{service_name} process closed gracefully (PID: {pid})")
                            return True

                    # Force kill if still running
                    subprocess.run(['kill', '-9', str(pid)], check=True, capture_output=True)
                except subprocess.CalledProcessError:
                    pass

            success(f"Stopped {service_name} process (PID: {pid})")
            return True

        except (subprocess.CalledProcessError, OSError) as e:
            warn(f"Could not stop process {pid}: {e}")
            return False

    def stop_service_on_port(self, port, service_name):
        """Stop all processes listening on a port"""
        info(f"Stopping {service_name} (port {port})...")

        pids = self.find_processes_on_port(port)

        if not pids:
            info(f"No process found on port {port}")
            return False

        pid_list = ', '.join(map(str, pids))
        info(f"Found process(es) on port {port}: PID {pid_list}")

        stopped = False
        for pid in pids:
            if self.stop_process(pid, service_name):
                stopped = True
            time.sleep(0.5)

        # Verify port is released
        if stopped:
            time.sleep(1)
            remaining = self.find_processes_on_port(port)
            if remaining:
                warn(f"Port {port} still has processes: {remaining}")
            else:
                success(f"Port {port} released")

        return stopped

    def cleanup_temp_files(self):
        """Clean up temporary files"""
        info("Cleaning up temporary files...")

        project_root = Path(__file__).parent.parent
        temp_patterns = [
            "*.tmp",
            ".~lock.*",
            "*.pyc",
            "__pycache__",
        ]

        cleaned = 0
        for pattern in temp_patterns:
            if "__pycache__" in pattern:
                dirs = project_root.rglob("__pycache__")
                for d in dirs:
                    try:
                        import shutil
                        shutil.rmtree(d)
                        cleaned += 1
                    except:
                        pass
            else:
                files = project_root.rglob(pattern)
                for f in files:
                    try:
                        f.unlink()
                        cleaned += 1
                    except:
                        pass

        if cleaned > 0:
            success(f"Cleaned {cleaned} temporary files")
        else:
            info("No temporary files to clean")


# ===========================
# Main
# ===========================

def main():
    parser = argparse.ArgumentParser(
        description='Anima Project Stop Script',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/stop.py                # Stop all services
  python scripts/stop.py --skip-backend  # Stop only frontend
        """
    )

    parser.add_argument('--skip-backend', action='store_true', help='Skip backend stop')
    parser.add_argument('--skip-frontend', action='store_true', help='Skip frontend stop')
    parser.add_argument('--cleanup', action='store_true', help='Clean up temporary files')

    args = parser.parse_args()

    # Print header
    print()
    if Colors.enabled():
        print(f"{Colors.MAGENTA}{'=' * 40}{Colors.NC}")
        print(f"{Colors.MAGENTA}  Anima Project Stop Script{Colors.NC}")
        print(f"{Colors.MAGENTA}{'=' * 40}{Colors.NC}")
    else:
        print('=' * 40)
        print('  Anima Project Stop Script')
        print('=' * 40)
    print()

    # Process manager
    pm = ProcessManager()

    # Stop services
    stopped_any = False

    if not args.skip_backend:
        if pm.stop_service_on_port(12394, "Backend"):
            stopped_any = True
        print()

    if not args.skip_frontend:
        if pm.stop_service_on_port(3000, "Frontend"):
            stopped_any = True
        print()

    # Cleanup
    if args.cleanup:
        pm.cleanup_temp_files()
        print()

    # Done
    if Colors.enabled():
        print(f"{Colors.GREEN}{'=' * 40}{Colors.NC}")
        print(f"{Colors.GREEN}  Stop Complete!{Colors.NC}")
        print(f"{Colors.GREEN}{'=' * 40}{Colors.NC}")
    else:
        print('=' * 40)
        print('  Stop Complete!')
        print('=' * 40)
    print()

    if not stopped_any:
        info("No services were running")
    else:
        success("All services stopped successfully")

    print()


if __name__ == "__main__":
    main()
