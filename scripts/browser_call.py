"""Print a browser link to call the agent on the self-hosted server.

    uv run python scripts/browser_call.py

Prerequisites, each in its own terminal:
    ./tools/livekit-server.exe --dev                     # the WebRTC server
    uv run python -m channels.livekit_agent dev          # the agent worker
    uv run python scripts/run_radicale.py                # the calendar

Open the printed link in Chrome, allow the microphone, and talk.
LiveKit Meet is only the browser client; audio flows through YOUR
local server (ws://127.0.0.1:7880), which is why the link only works
on this machine.
"""

from __future__ import annotations

import os
import time
from urllib.parse import quote

from dotenv import load_dotenv
from livekit.api import AccessToken, VideoGrants


def main() -> None:
    load_dotenv()
    url = os.environ.get("LIVEKIT_URL", "ws://127.0.0.1:7880")
    key = os.environ.get("LIVEKIT_API_KEY", "devkey")
    secret = os.environ.get("LIVEKIT_API_SECRET", "secret")

    room = f"reception-{int(time.time())}"  # a fresh room per call
    token = (
        AccessToken(key, secret)
        .with_identity("caller")
        .with_name("Caller")
        .with_grants(VideoGrants(room_join=True, room=room))
        .to_jwt()
    )
    print(f"room:  {room}")
    print("open this in Chrome:\n")
    print(f"https://meet.livekit.io/custom?liveKitUrl={quote(url)}&token={token}")


if __name__ == "__main__":
    main()
