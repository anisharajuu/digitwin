#!/usr/bin/env python3
"""Capture console screenshots for the docs, headlessly and reproducibly.

Drives a headless Chrome over the DevTools protocol rather than using
``--screenshot``, because that flag fires as soon as the load event does. This
console paints from a WebSocket frame and renders its plant view on an
animation frame, so a load-event screenshot catches an empty shell and a blank
canvas. Here we navigate, wait for the twin to connect, confirm the WebGL
canvas has actually drawn something, and only then capture.

Usage:
    python scripts/screenshots.py [--url http://localhost:5173] [--out docs/images]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

import websockets

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "chromium",
]

# Software WebGL: the machine running this in CI has no GPU, and a blank
# plant view is worse than no screenshot at all.
CHROME_FLAGS = [
    "--headless=new",
    "--disable-gpu",
    "--enable-unsafe-swiftshader",
    "--use-gl=angle",
    "--use-angle=swiftshader",
    "--hide-scrollbars",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--force-device-scale-factor=2",
]

VIEWS = [
    ("overview", "Overview", 1680, 1000),
    ("assets", "Assets", 1680, 1060),
    ("reliability", "Reliability", 1680, 1000),
    ("scenarios", "What-if", 1680, 1000),
]


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    sys.exit("Could not find Chrome or Chromium.")


def debugger_url(port: int, timeout: float = 20.0) -> str:
    """WebSocket endpoint for a *page* target.

    ``/json/version`` returns the browser-level endpoint, which does not carry
    the Page or Runtime domains - attaching there fails with
    "'Page.enable' wasn't found". The page targets are listed at ``/json``.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        with contextlib.suppress(Exception):
            raw = urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1).read()
            for target in json.loads(raw):
                if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                    return target["webSocketDebuggerUrl"]
        time.sleep(0.25)
    sys.exit("Chrome did not expose a page debugger endpoint in time.")


class Session:
    """Minimal CDP client: enough to navigate, evaluate and capture."""

    def __init__(self, socket) -> None:
        self.socket = socket
        self._next_id = 0

    async def call(self, method: str, **params):
        self._next_id += 1
        message_id = self._next_id
        await self.socket.send(json.dumps({"id": message_id, "method": method, "params": params}))
        while True:
            payload = json.loads(await self.socket.recv())
            if payload.get("id") != message_id:
                continue  # an event, not our reply
            if "error" in payload:
                raise RuntimeError(f"{method}: {payload['error']}")
            return payload.get("result", {})

    async def evaluate(self, expression: str):
        result = await self.call(
            "Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True
        )
        return result.get("result", {}).get("value")


async def wait_for(session: Session, expression: str, what: str, limit_s: float = 45.0) -> bool:
    deadline = time.time() + limit_s
    while time.time() < deadline:
        if await session.evaluate(expression) is True:
            return True
        await asyncio.sleep(0.4)
    print(f"  ! timed out waiting for {what}", file=sys.stderr)
    return False


#: True once the plant canvas holds more than one distinct colour, i.e. three.js
#: has actually drawn a frame rather than just clearing to the background.
CANVAS_DREW = """
(() => {
  const canvas = document.querySelector('canvas');
  if (!canvas || !canvas.width) return false;
  try {
    const probe = document.createElement('canvas');
    probe.width = 80; probe.height = 50;
    const ctx = probe.getContext('2d');
    ctx.drawImage(canvas, 0, 0, probe.width, probe.height);
    const { data } = ctx.getImageData(0, 0, probe.width, probe.height);
    const seen = new Set();
    for (let i = 0; i < data.length; i += 4) {
      seen.add((data[i] << 16) | (data[i + 1] << 8) | data[i + 2]);
      if (seen.size > 6) return true;
    }
    return false;
  } catch { return false; }
})()
"""


#: Clicking a button by its visible label, the way a person would.
CLICK_TEXT = """
(() => {{
  const button = [...document.querySelectorAll('button')]
    .find(el => el.textContent.trim().startsWith({text!r}));
  if (!button) return false;
  button.click();
  return true;
}})()
"""

#: React tracks input state itself, so a bare `.value =` assignment is ignored.
#: Going through the native setter before dispatching is what makes it stick.
SET_SCENARIO_ASSET = """
(() => {
  const select = document.querySelector('select');
  if (!select) return false;
  const option = [...select.options].find(o => o.value === 'AGT-301');
  if (!option) return false;
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLSelectElement.prototype, 'value').set;
  setter.call(select, 'AGT-301');
  select.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
})()
"""


async def capture(session: Session, url: str, out_dir: Path) -> None:
    await session.call("Page.enable")
    await session.call("Runtime.enable")

    for slug, nav_label, width, height in VIEWS:
        await session.call(
            "Emulation.setDeviceMetricsOverride",
            width=width,
            height=height,
            deviceScaleFactor=2,
            mobile=False,
        )
        await session.call("Page.navigate", url=url)
        await wait_for(session, "document.readyState === 'complete'", "page load")

        # The shell paints from the first streamed frame.
        await wait_for(
            session,
            "!!document.querySelector('main') && "
            "!document.body.innerText.includes('Loading the plant registry')",
            "plant registry",
        )

        if nav_label != "Overview":
            clicked = await session.evaluate(
                "(() => { const b = [...document.querySelectorAll('nav button')]"
                f".find(el => el.textContent.trim().startsWith({nav_label!r}));"
                " if (!b) return false; b.click(); return true; })()"
            )
            if not clicked:
                print(f"  ! could not find the {nav_label} tab", file=sys.stderr)
            await asyncio.sleep(2.5)

        if slug == "assets":
            # Land on the asset carrying the injected fault, and give its
            # telemetry request time to come back.
            await session.evaluate(
                "(() => { const b = [...document.querySelectorAll('button')]"
                ".find(el => el.textContent.includes('P-101A'));"
                " if (b) b.click(); return true; })()"
            )
            await asyncio.sleep(3.5)

        if slug == "scenarios":
            # An empty builder is a poor advertisement for the one view that
            # answers "what is this worth?". Drive it and capture a result.
            await session.evaluate(SET_SCENARIO_ASSET)
            await asyncio.sleep(0.6)
            await session.evaluate(CLICK_TEXT.format(text="Add change"))
            await asyncio.sleep(0.6)
            await session.evaluate(CLICK_TEXT.format(text="Project"))
            # The verdict line is the last thing to render, so it is the
            # honest signal that the projection is complete.
            await wait_for(
                session,
                "/(Proceed|Marginal|Do not proceed)/.test(document.body.innerText)",
                "projection result",
                limit_s=60,
            )
            await asyncio.sleep(1.0)

        if slug == "overview":
            await wait_for(session, CANVAS_DREW, "plant view to render", limit_s=60)

        await asyncio.sleep(1.5)
        shot = await session.call(
            "Page.captureScreenshot", format="png", captureBeyondViewport=True
        )
        target = out_dir / f"{slug}.png"
        payload = base64.b64decode(shot["data"])
        await asyncio.to_thread(target.write_bytes, payload)
        print(f"  wrote {target} ({len(payload) // 1024} kB)")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:5173")
    parser.add_argument("--out", default="docs/images")
    parser.add_argument("--port", type=int, default=9333)
    args = parser.parse_args()

    out_dir = Path(args.out)
    await asyncio.to_thread(lambda: out_dir.mkdir(parents=True, exist_ok=True))

    chrome = await asyncio.create_subprocess_exec(
        find_chrome(),
        *CHROME_FLAGS,
        f"--remote-debugging-port={args.port}",
        "about:blank",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        endpoint = await asyncio.to_thread(debugger_url, args.port)
        async with websockets.connect(endpoint, max_size=64 * 1024 * 1024) as socket:
            await capture(Session(socket), args.url, out_dir)
    finally:
        chrome.terminate()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(chrome.wait(), timeout=10)


if __name__ == "__main__":
    asyncio.run(main())
