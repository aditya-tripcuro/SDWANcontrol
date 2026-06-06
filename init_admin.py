import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append('/opt/wancontrol')

try:
    from wancontrol.database import Database
    from wancontrol.auth import Auth
    from wancontrol.config import ServerConfig, Config
except ImportError:
    # Fallback for local run
    sys.path.append(str(Path(__file__).parent))
    from wancontrol.database import Database
    from wancontrol.auth import Auth
    from wancontrol.config import ServerConfig, Config

def main():
    # Honor WANCONTROL_CONFIG / WANCONTROL_DB_PATH so this script can run against
    # a non-default location, matching wancontrol/__main__.py and network.py.
    config_path = os.environ.get("WANCONTROL_CONFIG", "/etc/wancontrol/config.yaml")

    if not os.path.exists(config_path):
        # Use default if not exists yet
        config_path = str(Path(__file__).parent / "config.yaml")

    try:
        cfg_loader = Config(config_path)
        app_cfg = cfg_loader.load()
        # WANCONTROL_DB_PATH wins, then the config's db_path, then the default —
        # mirroring the override order in wancontrol/__main__.py and network.py.
        db_path = os.environ.get("WANCONTROL_DB_PATH") or app_cfg.db_path or "/var/lib/wancontrol/wan.db"
        db = Database(db_path)
        db.initialize()
        auth = Auth(db, app_cfg.server)
        
        admin_user = db.get_user_by_username("admin")

        # Only emit credentials on GENUINE first creation, i.e. when the admin
        # user does not exist yet. We must NOT re-generate / re-emit a password on
        # subsequent runs just because the admin has not logged in or still has
        # requires_password_change set — those conditions are true immediately
        # after first creation, so re-emitting would rotate the password on every
        # install/restart and invalidate the credentials the operator already has.
        # The forced first-login password change still happens because we create
        # the user with requires_password_change=True.
        if not admin_user:
            import secrets
            password = secrets.token_urlsafe(12)
            auth.create_user("admin", password, "admin", requires_password_change=True)

            print("INITIAL_SETUP_SUCCESS")
            print(f"ADMIN_USER: admin")
            print(f"ADMIN_PWD: {password}")
        else:
            print("SETUP_ALREADY_DONE")
    except Exception as e:
        print(f"ERROR: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
