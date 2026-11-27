"""Explicit interactive OAuth setup; the MCP process never launches consent."""
import argparse
import json
import os
from pathlib import Path
import tempfile

BASE = "https://www.googleapis.com/auth/"
READ_SCOPES = [BASE + "youtube.readonly", BASE + "yt-analytics.readonly"]
WRITE_SCOPES = READ_SCOPES + [BASE + "youtube.force-ssl"]


def token_path(write=False):
    key = "YOUTUBE_MCP_WRITE_TOKEN" if write else "YOUTUBE_MCP_TOKEN"
    default = Path.home() / ".config/youtube-channel-mcp" / ("write-token.json" if write else "read-token.json")
    path = Path(os.environ.get(key, str(default))).expanduser().resolve()
    if path.name in ("token.json", "client_secrets.json"):
        raise ValueError("Use a dedicated read-token.json or write-token.json; legacy credentials are protected.")
    if write and path == token_path(False):
        raise ValueError("Read and write token paths must be different.")
    return path


def save_token(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".oauth-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def credentials(write=False):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    path = token_path(write)
    scopes = WRITE_SCOPES if write else READ_SCOPES
    if not path.is_file():
        raise ValueError("OAuth is not connected. Run youtube-channel-auth" + (" --write" if write else "") + " first; see setup guide.")
    try:
        stored = json.loads(path.read_text())
        # Do not pass scopes to the loader: doing so can falsely label an upload-only token.
        if not set(scopes).issubset(stored.get("scopes", [])):
            raise ValueError("Missing scopes")
        creds = Credentials.from_authorized_user_info(stored)
        if not creds.valid:
            if not creds.refresh_token:
                raise ValueError("Missing refresh token")
            creds.refresh(Request())
            save_token(path, creds.to_json())
        return creds
    except Exception:
        raise ValueError("OAuth token needs reauthorization. Run youtube-channel-auth" + (" --write" if write else "") + ".") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-secrets", default=os.environ.get("YOUTUBE_MCP_CLIENT_SECRETS"), required=not os.environ.get("YOUTUBE_MCP_CLIENT_SECRETS"))
    parser.add_argument("--write", action="store_true", help="Authorize separate optional scheduling credentials")
    args = parser.parse_args()
    from google_auth_oauthlib.flow import InstalledAppFlow
    path = Path(args.client_secrets).expanduser().resolve()
    destination = token_path(args.write)
    # Never allow accidental replacement of the legacy uploader's token.
    if destination == path or destination.name == "token.json":
        parser.error("Use a dedicated MCP token filename, never client secrets or token.json.")
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(path), WRITE_SCOPES if args.write else READ_SCOPES)
        creds = flow.run_local_server(host="localhost", port=0, access_type="offline", prompt="consent", timeout_seconds=300)
        if not creds.has_scopes(WRITE_SCOPES if args.write else READ_SCOPES):
            raise ValueError("Required scopes were not granted")
        save_token(destination, creds.to_json())
    except Exception:
        parser.exit(1, "Google authorization did not complete. Check Desktop OAuth client, consent users, and requested permissions; retry. No credentials were printed.\n")
    print("Dedicated MCP credentials saved. Restart the MCP server and ask for connection_status, then authorized_channel.")


if __name__ == "__main__":
    main()
