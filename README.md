# Buildify Template Server

This server matches the Android project `com.buildify.template`.

## Files

- `server.py` — Flask API + Firebase Admin SDK.
- `index.html` — browser user control panel.
- `requirements.txt` — Python packages.
- `Procfile` — Render/compatible Gunicorn start command.

## 1. Firebase setup

Create a Firebase project and enable Realtime Database.

From Firebase Console:

`Project settings -> Service accounts -> Generate new private key`

For a local machine you may put that JSON file next to `server.py` as:

`serviceAccountKey.json`

For hosted deployment, prefer environment variables instead of uploading the JSON file.

Required environment variables:

```text
FIREBASE_DATABASE_URL=https://YOUR-PROJECT-default-rtdb.firebaseio.com
FIREBASE_CREDENTIALS_JSON=<entire service account JSON as one value>
```

`GOOGLE_APPLICATION_CREDENTIALS` may be used instead when the host provides a file path.

## 2. Install and run locally

Python 3.10+ is recommended.

```bash
pip install -r requirements.txt
python server.py
```

Open:

`http://127.0.0.1:7860/`

Health check:

`http://127.0.0.1:7860/health`

## 3. Android AppConfig.java

In the Android project set only these values:

```java
public static final String SERVER_URL = "https://YOUR-SERVER.example.com";
public static final String APP_SECRET_CODE = "YOUR-OWN-SECRET-CODE-AT-LEAST-12-CHARS";
```

The server does NOT generate or store the plaintext app secret. The Android client sends only its SHA-256 hash for app registration/checks. The browser panel sends the plaintext code over HTTPS, and the server hashes it before using it as the Firebase app key.

## 4. First run

Build the Android APK with the server URL + secret code.

Start the APK once while it has internet access. It calls `/api/app/register` and creates/updates:

```text
apps/{sha256(secretCode)}
```

The database record contains app metadata, notification state, and update state. The plaintext secret is not written to Firebase.

## 5. User panel

Open:

`https://YOUR-SERVER/`

Enter the same secret code.

After login you can:

- publish a notification title
- publish a message
- attach an HTTPS image URL
- remove the active notification
- publish a new APK version
- choose mandatory/non-mandatory update
- remove the update

Anyone who knows the secret code can use these controls in this intentionally simple design.

## 6. Notification behavior

The current Android project uses scheduled/background polling, not FCM. When the app detects a new notification ID it shows the notification and image. The browser panel also displays the image URL.

This is therefore a remote notification system, not an instant Firebase Cloud Messaging channel.

## 7. APK update procedure

Every update MUST use the same Android package name:

`com.buildify.template`

Increase `versionCode` in the Android project, for example:

```gradle
defaultConfig {
    versionCode 2
    versionName "2.0.0"
}
```

Build the APK and upload the APK to a host that provides a direct HTTPS download URL.

In the Buildify panel enter:

- Version code: `2`
- Version name: `2.0.0`
- APK URL: direct HTTPS APK URL
- Mandatory update: enabled

The Android app checks:

`remote versionCode > installed versionCode`

and then shows the non-cancelable update dialog used by the supplied project.

## 8. Important Android update limitation

Android itself controls package installation. The app can force the user into the update flow, but it cannot silently install a normal APK without the OS installer/user approval. On Android 8+, the user may also need to allow installation of unknown apps for the current installer/source.

The update APK must also be signed with the same signing key as the installed app, otherwise Android will reject it as an incompatible update.

## 9. Firebase rules

Because this server uses the Firebase Admin SDK, it can administer Realtime Database data regardless of normal client Security Rules. For a server-only design, client read/write access can therefore be disabled and only the server service account should access the database.

Example:

```json
{
  "rules": {
    ".read": false,
    ".write": false
  }
}
```

Do not upload `serviceAccountKey.json` into a public Git repository.
