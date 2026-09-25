import hashlib
import json
import os
import re
import time
import uuid
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_from_directory
import firebase_admin
from firebase_admin import credentials, db

# ============================================================
# BUILDIFY SERVER CONFIG
# ============================================================
APP_NAME = "Buildify Template"
PACKAGE_NAME = "com.buildify.template"
MIN_SECRET_LENGTH = 12
MAX_TITLE = 120
MAX_MESSAGE = 5000
MAX_URL = 2048

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(BASE_DIR, "index.html")

# Recommended: set these as hosting environment variables.
FIREBASE_DATABASE_URL = os.environ.get("FIREBASE_DATABASE_URL", "").strip()
FIREBASE_CREDENTIALS_JSON = os.environ.get("FIREBASE_CREDENTIALS_JSON", "").strip()
SERVICE_ACCOUNT_FILE = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(BASE_DIR, "serviceAccountKey.json"),
).strip()

app = Flask(__name__)


def initialize_firebase():
    """Initialize Firebase Admin SDK once."""
    if firebase_admin._apps:
        return

    if not FIREBASE_DATABASE_URL:
        raise RuntimeError(
            "FIREBASE_DATABASE_URL is missing. Example: "
            "https://your-project-default-rtdb.firebaseio.com"
        )

    cred = None

    # Hosting-friendly option: the full service-account JSON in an env var.
    if FIREBASE_CREDENTIALS_JSON:
        try:
            service_account = json.loads(FIREBASE_CREDENTIALS_JSON)
            cred = credentials.Certificate(service_account)
        except Exception as exc:
            raise RuntimeError(
                "FIREBASE_CREDENTIALS_JSON is not valid service-account JSON: %s" % exc
            )

    # Local / simple hosting option: serviceAccountKey.json next to server.py.
    elif os.path.isfile(SERVICE_ACCOUNT_FILE):
        cred = credentials.Certificate(SERVICE_ACCOUNT_FILE)

    # Google-managed environments can use ADC.
    else:
        try:
            cred = credentials.ApplicationDefault()
        except Exception as exc:
            raise RuntimeError(
                "Firebase credentials not found. Set FIREBASE_CREDENTIALS_JSON or "
                "GOOGLE_APPLICATION_CREDENTIALS. Details: %s" % exc
            )

    firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DATABASE_URL})


try:
    initialize_firebase()
    FIREBASE_READY = True
    FIREBASE_ERROR = ""
except Exception as exc:
    FIREBASE_READY = False
    FIREBASE_ERROR = str(exc)


def now_ms():
    return int(time.time() * 1000)


def clean_text(value, max_len):
    value = "" if value is None else str(value).strip()
    return value[:max_len]


def valid_http_url(value, max_len=MAX_URL):
    value = clean_text(value, max_len)
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("URL must start with http:// or https://")
    return value


def secret_hash(secret_code):
    value = clean_text(secret_code, 512)
    if len(value) < MIN_SECRET_LENGTH:
        raise ValueError(
            "Secret code must be at least %d characters." % MIN_SECRET_LENGTH
        )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def valid_hash(value):
    return bool(re.fullmatch(r"[0-9a-f]{64}", value or ""))


def require_firebase():
    if not FIREBASE_READY:
        raise RuntimeError("Firebase is not configured: " + FIREBASE_ERROR)


def app_ref(code_hash):
    require_firebase()
    return db.reference("apps").child(code_hash)


def get_app(code_hash):
    return app_ref(code_hash).get()


def create_app_from_hash(code_hash, package_name=PACKAGE_NAME, app_name=APP_NAME):
    """Create a new app record without ever storing the plaintext secret code."""
    data = {
        "appName": clean_text(app_name, 120) or APP_NAME,
        "packageName": clean_text(package_name, 200) or PACKAGE_NAME,
        "createdAt": now_ms(),
        "versionCode": 1,
        "versionName": "1.0.0",
        "notification": None,
        "update": None,
    }
    app_ref(code_hash).set(data)
    return data


def get_or_create_app(code_hash, package_name=PACKAGE_NAME, app_name=APP_NAME):
    data = get_app(code_hash)
    if isinstance(data, dict):
        return data
    return create_app_from_hash(code_hash, package_name, app_name)


def json_error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/index.html")
def index_html():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/health")
def health():
    return jsonify(
        {
            "ok": FIREBASE_READY,
            "firebaseConfigured": FIREBASE_READY,
            "app": APP_NAME,
            "packageName": PACKAGE_NAME,
            "error": FIREBASE_ERROR if not FIREBASE_READY else None,
        }
    )


@app.post("/api/app/register")
def api_register():
    """Called by the Android APK on startup."""
    try:
        body = request.get_json(silent=True) or {}
        code_hash = clean_text(body.get("codeHash"), 128)
        package_name = clean_text(body.get("packageName"), 200) or PACKAGE_NAME
        app_name = clean_text(body.get("appName"), 120) or APP_NAME
        version_name = clean_text(body.get("versionName"), 80) or "1.0.0"

        if not valid_hash(code_hash):
            return json_error("Invalid code hash", 400)

        try:
            version_code = int(body.get("versionCode", 1))
        except (TypeError, ValueError):
            return json_error("versionCode must be an integer", 400)

        if version_code < 1:
            return json_error("versionCode must be >= 1", 400)

        current = get_app(code_hash)
        if not isinstance(current, dict):
            current = create_app_from_hash(code_hash, package_name, app_name)

        # Registration updates only app identity/version metadata.
        current["appName"] = app_name
        current["packageName"] = package_name
        current["versionCode"] = version_code
        current["versionName"] = version_name
        current.setdefault("notification", None)
        current.setdefault("update", None)
        app_ref(code_hash).set(current)

        return jsonify({"ok": True, "app": current})
    except Exception as exc:
        return json_error(str(exc), 500)


@app.get("/api/app/check")
def api_check():
    """Called by the Android APK for notification/update polling."""
    code_hash = clean_text(request.args.get("codeHash"), 128)
    package_name = clean_text(request.args.get("packageName"), 200)

    if not valid_hash(code_hash):
        return json_error("Invalid code hash", 400)

    try:
        data = get_app(code_hash)
        if not isinstance(data, dict):
            return json_error("App not registered", 404)

        stored_package = clean_text(data.get("packageName"), 200)
        if package_name and stored_package and stored_package != package_name:
            return json_error("Package mismatch", 403)

        return jsonify(data)
    except Exception as exc:
        return json_error(str(exc), 500)


@app.post("/api/user/login")
def api_user_login():
    """Browser login. The secret code is used as the panel password."""
    try:
        body = request.get_json(silent=True) or {}
        code_hash = secret_hash(body.get("secretCode"))
        data = get_app(code_hash)
        if not isinstance(data, dict):
            return json_error("Invalid secret code or app not registered", 401)
        return jsonify({"ok": True, "app": data})
    except ValueError as exc:
        return json_error(str(exc), 400)
    except Exception as exc:
        return json_error(str(exc), 500)


def secret_app_from_body(body):
    code_hash = secret_hash(body.get("secretCode"))
    data = get_app(code_hash)
    if not isinstance(data, dict):
        raise PermissionError("Invalid secret code or app not registered")
    return code_hash, data


@app.post("/api/admin/notification")
def api_publish_notification():
    """Publish a notification to the APK and to the browser panel."""
    try:
        body = request.get_json(silent=True) or {}
        code_hash, data = secret_app_from_body(body)

        title = clean_text(body.get("title"), MAX_TITLE)
        message = clean_text(body.get("message"), MAX_MESSAGE)
        image_url = valid_http_url(body.get("imageUrl", ""))

        if not title and not message:
            return json_error("Title or message is required", 400)

        notification = {
            "id": str(uuid.uuid4()),
            "title": title or "Buildify Notification",
            "message": message,
            "imageUrl": image_url,
            "createdAt": now_ms(),
        }

        data["notification"] = notification
        app_ref(code_hash).set(data)
        return jsonify({"ok": True, "notification": notification})
    except PermissionError as exc:
        return json_error(str(exc), 401)
    except ValueError as exc:
        return json_error(str(exc), 400)
    except Exception as exc:
        return json_error(str(exc), 500)


@app.post("/api/admin/clear-notification")
def api_clear_notification():
    try:
        body = request.get_json(silent=True) or {}
        code_hash, data = secret_app_from_body(body)
        data["notification"] = None
        app_ref(code_hash).set(data)
        return jsonify({"ok": True})
    except PermissionError as exc:
        return json_error(str(exc), 401)
    except ValueError as exc:
        return json_error(str(exc), 400)
    except Exception as exc:
        return json_error(str(exc), 500)


@app.post("/api/admin/update")
def api_publish_update():
    """Publish an APK update. Android checks remote versionCode > local versionCode."""
    try:
        body = request.get_json(silent=True) or {}
        code_hash, data = secret_app_from_body(body)

        try:
            version_code = int(body.get("versionCode", 0))
        except (TypeError, ValueError):
            return json_error("versionCode must be an integer", 400)

        version_name = clean_text(body.get("versionName"), 80)
        apk_url = valid_http_url(body.get("apkUrl"))
        message = clean_text(body.get("message"), MAX_MESSAGE)

        if version_code < 1:
            return json_error("versionCode must be >= 1", 400)
        if not version_name:
            return json_error("versionName is required", 400)
        if not apk_url:
            return json_error("apkUrl is required", 400)

        current_version = int(data.get("versionCode", 1))
        if version_code <= current_version:
            return json_error(
                "Update versionCode must be greater than the installed/current app versionCode (%d)"
                % current_version,
                400,
            )

        mandatory_value = body.get("mandatory", True)
        if isinstance(mandatory_value, str):
            mandatory = mandatory_value.lower() in ("1", "true", "yes", "on")
        else:
            mandatory = bool(mandatory_value)

        update = {
            "versionCode": version_code,
            "versionName": version_name,
            "apkUrl": apk_url,
            "mandatory": mandatory,
            "message": message or "A newer version is required to continue.",
            "createdAt": now_ms(),
        }

        data["update"] = update
        app_ref(code_hash).set(data)
        return jsonify({"ok": True, "update": update})
    except PermissionError as exc:
        return json_error(str(exc), 401)
    except ValueError as exc:
        return json_error(str(exc), 400)
    except Exception as exc:
        return json_error(str(exc), 500)


@app.post("/api/admin/clear-update")
def api_clear_update():
    try:
        body = request.get_json(silent=True) or {}
        code_hash, data = secret_app_from_body(body)
        data["update"] = None
        app_ref(code_hash).set(data)
        return jsonify({"ok": True})
    except PermissionError as exc:
        return json_error(str(exc), 401)
    except ValueError as exc:
        return json_error(str(exc), 400)
    except Exception as exc:
        return json_error(str(exc), 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7860"))
    app.run(host="0.0.0.0", port=port, debug=False)
