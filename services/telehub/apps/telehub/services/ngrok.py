"""
Auto-detects the current public ngrok tunnel so a Process Agent's webhook URL is
always correct, without manually running `curl 127.0.0.1:4040/api/tunnels` and
eyeballing it (that was the previous orchestrator's workflow — see
docs/superpowers/plans/gpt_ai_hub_impl_plan.md "Automatic Webhook Generation").
Assumes `ngrok http 8000` (TeleHub's dev port) is running locally. Never raises:
if ngrok isn't running or reachable, callers fall back to a relative path.

When deployed (no ngrok), set PUBLIC_BASE_URL (e.g. https://telehub-api.onrender.com)
and it is returned as-is instead of querying ngrok.
"""
import json
import os
import urllib.error
import urllib.request

NGROK_API_URL = os.environ.get("NGROK_API_URL", "http://127.0.0.1:4040/api/tunnels")


def get_public_base_url() -> str | None:
    """
    Returns the https public URL of the running ngrok tunnel (prefers an https
    tunnel, falls back to whatever's there), or None if ngrok isn't running.
    PUBLIC_BASE_URL, when set, takes precedence over ngrok.
    """
    configured = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured

    try:
        with urllib.request.urlopen(NGROK_API_URL, timeout=1) as response:
            data = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None

    tunnels = data.get("tunnels", [])
    for tunnel in tunnels:
        if tunnel.get("proto") == "https" and tunnel.get("public_url"):
            return tunnel["public_url"]
    for tunnel in tunnels:
        if tunnel.get("public_url"):
            return tunnel["public_url"]
    return None
