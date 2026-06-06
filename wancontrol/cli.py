"""
wancontrol/cli.py
~~~~~~~~~~~~~~~~~
CLI management tool for WANControl v2. Provides service control (start/stop/restart)
and an interactive configuration wizard for network interfaces.
"""

import os
import sys
import time
import argparse
import getpass
import subprocess
import yaml
from pathlib import Path
from typing import NoReturn, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from wancontrol.auth import Auth
    from wancontrol.database import Database

def _run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=check)
    except subprocess.CalledProcessError as e:
        print(f"Error: Command failed with exit code {e.returncode}")
        sys.exit(e.returncode)

def stop() -> None:
    print("Stopping WANControl service...")
    _run_cmd(["sudo", "systemctl", "stop", "wancontrol"])

def start() -> None:
    print("Starting WANControl service...")
    _run_cmd(["sudo", "systemctl", "start", "wancontrol"])

def restart() -> None:
    print("Restarting WANControl service...")
    _run_cmd(["sudo", "systemctl", "restart", "wancontrol"])

def status() -> None:
    _run_cmd(["sudo", "systemctl", "status", "wancontrol"], check=False)

def help_msg() -> None:
    print("""
WANControl v2 CLI
Usage: wancontrol <command> [args]

Commands:
  start      Start the WANControl service
  stop       Stop the WANControl service
  restart    Restart the WANControl service
  status     Check the status of the WANControl service
  configure  Interactive wizard to add a new WAN interface
  discover   Discover available network interfaces
  logs       View service logs (tail)
  user       Manage local users (add/passwd/list/role/deactivate)
  help       Show this help message

User management:
  user add <name> [--role admin|operator|viewer]   Create a user (prompts for password)
  user passwd <name>                                Reset a user's password (prompts)
  user list                                         List all users
  user role <name> <admin|operator|viewer>          Change a user's role
  user deactivate <name>                            Deactivate a user account
""")

def logs() -> None:
    _run_cmd(["sudo", "journalctl", "-u", "wancontrol", "-f"])

def discover() -> None:
    # Assuming discover_interfaces.py is in the root
    project_root = Path(__file__).parent.parent
    script_path = project_root / "discover_interfaces.py"
    if script_path.exists():
        _run_cmd(["python3", str(script_path)])
    else:
        print(f"Error: {script_path} not found.")

from wancontrol.network_discovery import discover_interfaces, check_prerequisites as discover_prereq

def configure() -> None:
    print("=== WANControl Interface Configuration Wizard ===")
    config_path = Path(os.environ.get("WANCONTROL_CONFIG", "/etc/wancontrol/config.yaml"))
    
    if not config_path.exists():
        print(f"Error: Config file not found at {config_path}")
        return

    # Check prerequisites for discovery
    missing = discover_prereq()
    if missing:
        print(f"Error: Missing discovery tools ({', '.join(missing)}). Please install iproute2.")
        return

    print("Scanning for network interfaces...")
    interfaces = discover_interfaces()
    candidates = [i for i in interfaces if i.is_wan_candidate]

    if not candidates:
        print("No suitable WAN candidates found automatically.")
        print("Check if your interfaces have IP addresses and default gateways.")
        choice = input("Would you like to manually configure an interface? (y/N): ").strip().lower()
        if choice != 'y':
            return
    else:
        print(f"\nFound {len(candidates)} potential WAN interface(s):")
        for idx, iface in enumerate(candidates):
            print(f"  [{idx + 1}] {iface.name} - IP: {iface.ip}, Gateway: {iface.gateway}, Speed: {iface.speed_mbps}Mbps")
        
        print(f"  [{len(candidates) + 1}] Manual configuration")
        
        try:
            sel = input(f"\nSelect an interface [1-{len(candidates) + 1}]: ").strip()
            sel_idx = int(sel) - 1
        except ValueError:
            print("Invalid selection.")
            return

        if sel_idx < len(candidates):
            selected = candidates[sel_idx]
            name = selected.name
            gateway = selected.gateway
            speed = selected.speed_mbps if selected.speed_mbps > 0 else 100
            label = f"WAN-{selected.name}"
        else:
            name = input("Interface name (e.g., eth1): ").strip()
            gateway = input("Gateway IP: ").strip()
            try:
                speed = int(input("Expected speed in Mbps: ").strip())
            except ValueError:
                speed = 100
            label = input("Label: ").strip()

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading config: {e}")
        return

    if "interfaces" not in config:
        config["interfaces"] = []

    if any(i["name"] == name for i in config["interfaces"]):
        print(f"Error: Interface {name} is already in the configuration.")
        return

    # Auto-assign unique table ID
    existing_ids = {i["routing_table_id"] for i in config["interfaces"]}
    table_id = 100
    while table_id in existing_ids:
        table_id += 1
    
    new_interface = {
        "name": name,
        "label": label,
        "expected_speed_mbps": speed,
        "gateway": gateway,
        "routing_table_id": table_id
    }

    config["interfaces"].append(new_interface)

    print("\nProposed Configuration:")
    print(yaml.dump({"interface": new_interface}, sort_keys=False))

    confirm = input("Save changes to config? (y/N): ").strip().lower()
    if confirm == 'y':
        try:
            # We use sudo to write to /etc
            temp_file = Path("/tmp/wancontrol_config.yaml")
            with open(temp_file, "w") as f:
                yaml.dump(config, f, sort_keys=False)
            
            _run_cmd(["sudo", "cp", str(temp_file), str(config_path)])
            print(f"Config saved to {config_path}")
            
            restart_needed = input("Restart WANControl service to apply changes? (y/N): ").strip().lower()
            if restart_needed == 'y':
                restart()
        except Exception as e:
            print(f"Error saving config: {e}")
    else:
        print("Cancelled.")

# ── User management (local, bcrypt, no HTTP) ───────────────────────────────────
#
# `wancontrol-cli user {add,passwd,list,role,deactivate}` operates directly on the
# SQLite database via the auth/database layer — it never touches the HTTP API.
# This is the supported on-box path for creating accounts and resetting passwords
# (audit item 1; passwd is the password-reset path for item 32).

VALID_ROLES: tuple[str, ...] = ("admin", "operator", "viewer")


def _load_auth() -> tuple["Database", "Auth"]:
    """
    Load Config + Database the same way ``wancontrol.network`` __main__ does and
    return an initialised ``(Database, Auth)`` pair.

    Honours ``WANCONTROL_CONFIG`` and ``WANCONTROL_DB_PATH`` so the CLI targets
    the same database the daemon uses.
    """
    # Imported lazily so service control commands (start/stop/...) don't pay the
    # cost of importing the database/auth/bcrypt stack.
    from wancontrol.config import Config
    from wancontrol.database import Database
    from wancontrol.auth import Auth

    cfg_path = os.environ.get("WANCONTROL_CONFIG", "/etc/wancontrol/config.yaml")
    cfg_loader = Config(cfg_path)
    try:
        app_cfg = cfg_loader.load()
    except Exception as exc:
        print(f"Error: failed to load config {cfg_path!r}: {exc}")
        sys.exit(1)

    db_path = os.environ.get("WANCONTROL_DB_PATH") or app_cfg.db_path
    db = Database(db_path)
    db.initialize()
    auth = Auth(db, app_cfg.server)
    return db, auth


def _prompt_new_password(username: str) -> str:
    """Prompt twice for a new password via getpass; exit on mismatch/empty."""
    pw1 = getpass.getpass(f"New password for {username!r}: ")
    if not pw1:
        print("Error: password must not be empty.")
        sys.exit(1)
    pw2 = getpass.getpass("Confirm new password: ")
    if pw1 != pw2:
        print("Error: passwords do not match.")
        sys.exit(1)
    return pw1


def user_add(username: str, role: str) -> None:
    from wancontrol.auth import AuthError

    if role not in VALID_ROLES:
        print(f"Error: invalid role {role!r}. Must be one of {', '.join(VALID_ROLES)}.")
        sys.exit(1)

    _db, auth = _load_auth()
    password = _prompt_new_password(username)
    try:
        # New CLI-created users must change their password on first login.
        user_id = auth.create_user(
            username, password, role, requires_password_change=True
        )
    except AuthError as exc:
        print(f"Error: {exc.message}")
        sys.exit(1)
    print(f"Created user {username!r} (id={user_id}, role={role}).")
    print("The user will be required to change this password on first login.")


def user_passwd(username: str) -> None:
    """Password-reset path (audit item 32) — admins reset any user's password."""
    db, auth = _load_auth()
    user = db.get_user_by_username(username)
    if user is None:
        print(f"Error: user {username!r} not found.")
        sys.exit(1)

    password = _prompt_new_password(username)
    if len(password) < auth._MIN_PASSWORD_LEN:
        print(
            f"Error: password must be at least {auth._MIN_PASSWORD_LEN} characters."
        )
        sys.exit(1)

    db.update_user_password(user.id, auth._hash_password(password))
    # Force a change on next login so an admin-set password is not kept long-term.
    db.set_requires_password_change(user.id, True)
    db.log_event(
        level="WARNING",
        component="auth",
        message=f"Password reset for user {username!r} (id={user.id}) via CLI.",
    )
    print(f"Password reset for user {username!r}.")
    print("The user will be required to change it on next login.")


def user_list() -> None:
    db, _auth = _load_auth()
    users = db.list_users()
    if not users:
        print("No users found.")
        return

    header = f"{'ID':>3}  {'USERNAME':<20} {'ROLE':<9} {'ACTIVE':<7} {'PWCHG':<6} LAST LOGIN"
    print(header)
    print("-" * len(header))
    for u in users:
        if u.last_login is None:
            last = "never"
        else:
            last = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(u.last_login))
        print(
            f"{u.id:>3}  {u.username:<20} {u.role:<9} "
            f"{'yes' if u.is_active else 'no':<7} "
            f"{'yes' if u.requires_password_change else 'no':<6} {last}"
        )


def user_role(username: str, role: str) -> None:
    if role not in VALID_ROLES:
        print(f"Error: invalid role {role!r}. Must be one of {', '.join(VALID_ROLES)}.")
        sys.exit(1)

    db, _auth = _load_auth()
    user = db.get_user_by_username(username)
    if user is None:
        print(f"Error: user {username!r} not found.")
        sys.exit(1)

    db.update_user_role(user.id, role)
    db.log_event(
        level="INFO",
        component="auth",
        message=f"Role for user {username!r} (id={user.id}) changed to {role!r} via CLI.",
    )
    print(f"Role for user {username!r} changed to {role!r}.")


def user_deactivate(username: str) -> None:
    db, _auth = _load_auth()
    user = db.get_user_by_username(username)
    if user is None:
        print(f"Error: user {username!r} not found.")
        sys.exit(1)

    if not user.is_active:
        print(f"User {username!r} is already deactivated.")
        return

    db.deactivate_user(user.id)
    db.log_event(
        level="WARNING",
        component="auth",
        message=f"User {username!r} (id={user.id}) deactivated via CLI.",
    )
    print(f"User {username!r} deactivated.")


def _build_user_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wancontrol-cli user",
        description="Local user management (operates directly on the database).",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    p_add = sub.add_parser("add", help="Create a new user (prompts for password).")
    p_add.add_argument("username")
    p_add.add_argument(
        "--role", choices=VALID_ROLES, default="viewer",
        help="Role for the new user (default: viewer).",
    )

    p_passwd = sub.add_parser("passwd", help="Reset a user's password (prompts).")
    p_passwd.add_argument("username")

    sub.add_parser("list", help="List all users.")

    p_role = sub.add_parser("role", help="Change a user's role.")
    p_role.add_argument("username")
    p_role.add_argument("role", choices=VALID_ROLES)

    p_deact = sub.add_parser("deactivate", help="Deactivate a user account.")
    p_deact.add_argument("username")

    return parser


def user(argv: list[str]) -> None:
    """Dispatch ``wancontrol-cli user <action> ...``."""
    parser = _build_user_parser()
    args = parser.parse_args(argv)

    if args.action == "add":
        user_add(args.username, args.role)
    elif args.action == "passwd":
        user_passwd(args.username)
    elif args.action == "list":
        user_list()
    elif args.action == "role":
        user_role(args.username, args.role)
    elif args.action == "deactivate":
        user_deactivate(args.username)
    else:  # pragma: no cover - argparse enforces a valid action
        parser.print_help()
        sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        help_msg()
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "start":
        start()
    elif cmd == "stop":
        stop()
    elif cmd == "restart":
        restart()
    elif cmd == "status":
        status()
    elif cmd == "configure":
        configure()
    elif cmd == "discover":
        discover()
    elif cmd == "logs":
        logs()
    elif cmd == "user":
        user(sys.argv[2:])
    elif cmd == "help":
        help_msg()
    else:
        print(f"Unknown command: {cmd}")
        help_msg()
        sys.exit(1)

if __name__ == "__main__":
    main()
