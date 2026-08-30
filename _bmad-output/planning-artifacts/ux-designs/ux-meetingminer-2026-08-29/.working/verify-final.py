#!/usr/bin/env python3
"""Hash, render, and measure the final Story 6.1 standalone HTML artifacts."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import signal
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen


CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MEASURE = r"""(() => {
  const viewport = document.documentElement.clientWidth;
  const visible = (element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  };
  const offenders = [...document.body.querySelectorAll('*')].filter((element) => {
    if (!visible(element) || element.closest('.timeline-scroll')) return false;
    const rect = element.getBoundingClientRect();
    return rect.left < -1 || rect.right > viewport + 1;
  }).map((element) => {
    const rect = element.getBoundingClientRect();
    return {tag: element.tagName.toLowerCase(), className: String(element.className).slice(0, 80), left: Math.round(rect.left), right: Math.round(rect.right)};
  }).slice(0, 30);
  const scrollports = [...document.querySelectorAll('.timeline-scroll')].map((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
    overflowX: getComputedStyle(element).overflowX,
    label: element.getAttribute('aria-label')
  }));
  const controlsInsideScrollport = [...document.querySelectorAll('.timeline-controls')].some((element) => element.closest('.timeline-scroll'));
  return {
    viewport,
    documentScrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
    offenders,
    scrollports,
    controlsInsideScrollport
  };
})()"""


class Cdp:
    def __init__(self, websocket_url: str) -> None:
        parsed = urlparse(websocket_url)
        self.socket = socket.create_connection((parsed.hostname, parsed.port), timeout=5)
        self.identifier = 0
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {parsed.path} HTTP/1.1\r\nHost: {parsed.hostname}:{parsed.port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
            "Origin: http://localhost\r\n\r\n"
        )
        self.socket.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.socket.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"WebSocket upgrade failed: {response[:300]!r}")

    def _exact(self, length: int) -> bytes:
        value = b""
        while len(value) < length:
            value += self.socket.recv(length - len(value))
        return value

    def _receive(self) -> dict:
        while True:
            header = self._exact(2)
            opcode = header[0] & 15
            length = header[1] & 127
            if length == 126:
                length = struct.unpack("!H", self._exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._exact(8))[0]
            body = self._exact(length)
            if opcode == 1:
                return json.loads(body)

    def call(self, method: str, params: dict | None = None) -> dict:
        self.identifier += 1
        identifier = self.identifier
        raw = json.dumps({"id": identifier, "method": method, "params": params or {}}).encode()
        mask = os.urandom(4)
        length = len(raw)
        if length < 126:
            header = bytes([129, 128 | length])
        elif length < 65536:
            header = bytes([129, 254]) + struct.pack("!H", length)
        else:
            header = bytes([129, 255]) + struct.pack("!Q", length)
        self.socket.sendall(header + mask + bytes(byte ^ mask[index % 4] for index, byte in enumerate(raw)))
        while True:
            message = self._receive()
            if message.get("id") == identifier:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message.get("result", {})

    def close(self) -> None:
        self.socket.close()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def launch(path: Path) -> tuple[subprocess.Popen, Path, Cdp]:
    profile = Path(tempfile.mkdtemp(prefix="meetingminer-ux-chrome-"))
    process = subprocess.Popen(
        [
            CHROME,
            "--headless=new",
            "--disable-gpu",
            "--disable-background-networking",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-debugging-port=0",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile}",
            path.as_uri(),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    active = profile / "DevToolsActivePort"
    deadline = time.time() + 10
    while time.time() < deadline and not active.exists():
        time.sleep(0.05)
    port = int(active.read_text().splitlines()[0])
    pages: list[dict] = []
    while time.time() < deadline:
        pages = [target for target in json.load(urlopen(f"http://127.0.0.1:{port}/json/list")) if target.get("type") == "page"]
        if pages:
            break
        time.sleep(0.05)
    return process, profile, Cdp(pages[0]["webSocketDebuggerUrl"])


def stop(process: subprocess.Popen, cdp: Cdp) -> None:
    cdp.close()
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def render(path: Path, evidence_dir: Path, widths: tuple[int, ...]) -> dict:
    digest = sha256(path)
    process, _profile, cdp = launch(path)
    captures: dict[str, dict] = {}
    try:
        for width in widths:
            cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 800, "deviceScaleFactor": 1, "mobile": False, "screenWidth": width, "screenHeight": 800})
            cdp.call("Runtime.evaluate", {"expression": "new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))", "awaitPromise": True})
            metrics = cdp.call("Runtime.evaluate", {"expression": MEASURE, "returnByValue": True})["result"]["value"]
            screenshot = cdp.call("Page.captureScreenshot", {"format": "png", "fromSurface": True, "captureBeyondViewport": False})["data"]
            name = f"{path.stem}-{digest[:12]}-{width}.png"
            (evidence_dir / name).write_bytes(base64.b64decode(screenshot))
            if metrics["documentScrollWidth"] != metrics["viewport"] or metrics["bodyScrollWidth"] != metrics["viewport"] or metrics["offenders"]:
                raise AssertionError(f"{path.name} at {width}px has non-timeline overflow: {metrics}")
            if metrics["controlsInsideScrollport"]:
                raise AssertionError(f"{path.name}: timeline controls are inside the data scrollport")
            captures[str(width)] = {"screenshot": name, "metrics": metrics}
    finally:
        stop(process, cdp)
    return {"path": str(path), "sha256": digest, "captures": captures}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--study", type=Path)
    args = parser.parse_args()
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    records = [render(path, args.evidence_dir, (1280, 320)) for path in sorted((args.source_root / "mockups").glob("*.html"))]
    if args.study:
        records.append(render(args.study.resolve(), args.evidence_dir, (1280,)))
    manifest = {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "artifacts": records}
    manifest_path = args.evidence_dir / "final-verification-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(manifest_path)


if __name__ == "__main__":
    main()
