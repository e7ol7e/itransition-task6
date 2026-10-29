"""Capture the actual Nominal browser window, silently, using portable OBS.

Run `uv run python record_demo.py`. Pauses capture while a benchmark is pending.
No desktop capture, presentation frames, subtitles, microphones or audio track.
"""

from __future__ import annotations

import base64
import ctypes
import io
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx

os.environ["OPENBLAS_NUM_THREADS"] = "1"
sys.stdout.reconfigure(encoding="utf8")
import obsws_python as obs
from PIL import Image, ImageStat
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "video"
OBS = Path("D:/Run/OBS-Studio-32.1.2-Windows-x64")
FFMPEG = Path("D:/Run/ffmpeg/ffmpeg-7.1.1-essentials_build/bin/ffmpeg.exe")
URL = "https://task6.evgeniy.win/"
NAME = "Task 6 Nominal SQL Contact Lab"


class Recorder:
    def __init__(self):
        self.client = None
        self.process = None
        self.config_path = (
            OBS / "config/obs-studio/plugin_config/obs-websocket/config.json"
        )
        self.original = self.config_path.read_bytes()
        self.recording = False

    def start(self):
        if (
            "obs64.exe"
            in subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq obs64.exe"], text=True
            ).lower()
        ):
            raise RuntimeError(
                "OBS is already running. Close it before the dedicated demonstration capture."
            )
        config = json.loads(self.original.decode("utf-8-sig"))
        password = secrets.token_urlsafe(24)
        config.update(
            server_enabled=True,
            server_port=4458,
            auth_required=True,
            server_password=password,
        )
        self.config_path.write_text(json.dumps(config), encoding="utf8")
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        self.process = subprocess.Popen(
            [
                str(OBS / "bin/64bit/obs64.exe"),
                "--portable",
                "--minimize-to-tray",
                "--disable-updater",
                "--disable-shutdown-check",
            ],
            cwd=OBS / "bin/64bit",
            startupinfo=startup,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(30):
            try:
                self.client = obs.ReqClient(
                    host="127.0.0.1", port=4458, password=password, timeout=5
                )
                self.client.send("GetVersion", raw=True)
                break
            except Exception:  # noqa: BLE001 -- OBS can fail before its socket is ready.
                time.sleep(1)
        if self.client is None:
            raise RuntimeError("Portable OBS did not start")
        c = self.client
        profiles = c.send("GetProfileList", raw=True)
        self.old_profile = profiles["currentProfileName"]
        if self.old_profile == NAME and "Task 3.5 VS Code" in profiles["profiles"]:
            self.old_profile = "Task 3.5 VS Code"
        if NAME not in profiles["profiles"]:
            c.send("CreateProfile", {"profileName": NAME})
            # OBS updates the profile menu asynchronously after CreateProfile.
            time.sleep(1)
        c.send("SetCurrentProfile", {"profileName": NAME})
        for category, key, value in [
            ("Output", "Mode", "Simple"),
            ("SimpleOutput", "FilePath", str(OUT)),
            ("SimpleOutput", "RecFormat2", "mkv"),
            ("SimpleOutput", "RecQuality", "HQ"),
            ("SimpleOutput", "RecEncoder", "x264"),
        ]:
            c.send(
                "SetProfileParameter",
                {
                    "parameterCategory": category,
                    "parameterName": key,
                    "parameterValue": value,
                },
            )
        alternate = next(p for p in profiles["profiles"] if p != NAME)
        c.send("SetCurrentProfile", {"profileName": alternate})
        c.send("SetCurrentProfile", {"profileName": NAME})
        c.send(
            "SetVideoSettings",
            {
                "baseWidth": 1920,
                "baseHeight": 1080,
                "outputWidth": 1920,
                "outputHeight": 1080,
                "fpsNumerator": 30,
                "fpsDenominator": 1,
            },
        )
        collections = c.send("GetSceneCollectionList", raw=True)
        self.old_collection = collections["currentSceneCollectionName"]
        if (
            self.old_collection == NAME
            and "Task 3.5 VS Code" in collections["sceneCollections"]
        ):
            self.old_collection = "Task 3.5 VS Code"
        if NAME not in collections["sceneCollections"]:
            c.send("CreateSceneCollection", {"sceneCollectionName": NAME})
        else:
            c.send("SetCurrentSceneCollection", {"sceneCollectionName": NAME})
        if not any(
            s["sceneName"] == NAME for s in c.send("GetSceneList", raw=True)["scenes"]
        ):
            c.send("CreateScene", {"sceneName": NAME})
        source = "Actual Task 6 Chrome window"
        if not any(
            i["inputName"] == source for i in c.send("GetInputList", raw=True)["inputs"]
        ):
            c.send(
                "CreateInput",
                {
                    "sceneName": NAME,
                    "inputName": source,
                    "inputKind": "window_capture",
                    "inputSettings": {},
                    "sceneItemEnabled": True,
                },
            )
        windows = c.send(
            "GetInputPropertiesListPropertyItems",
            {"inputName": source, "propertyName": "window"},
            raw=True,
        )["propertyItems"]
        window = next(
            w["itemValue"]
            for w in windows
            if w["itemEnabled"]
            and "Nominal" in w["itemName"]
            and "chrome.exe" in w["itemValue"].lower()
        )
        c.send(
            "SetInputSettings",
            {
                "inputName": source,
                "inputSettings": {
                    "window": window,
                    "priority": 1,
                    "method": 2,
                    "cursor": False,
                    "client_area": True,
                },
                "overlay": True,
            },
        )
        c.send("SetCurrentProgramScene", {"sceneName": NAME})
        item = c.send(
            "GetSceneItemId", {"sceneName": NAME, "sourceName": source}, raw=True
        )["sceneItemId"]
        c.send(
            "SetSceneItemTransform",
            {
                "sceneName": NAME,
                "sceneItemId": item,
                "sceneItemTransform": {
                    "positionX": 0,
                    "positionY": 0,
                    "boundsType": "OBS_BOUNDS_SCALE_INNER",
                    "boundsWidth": 1920,
                    "boundsHeight": 1080,
                },
            },
        )
        # Only one window-capture source, no microphones or desktop audio.
        for source_info in c.send("GetInputList", raw=True)["inputs"]:
            if source_info["inputKind"] in {
                "wasapi_input_capture",
                "wasapi_output_capture",
            }:
                c.send(
                    "SetInputMute",
                    {"inputName": source_info["inputName"], "inputMuted": True},
                )
        time.sleep(3)
        shot = c.send(
            "GetSourceScreenshot",
            {
                "sourceName": NAME,
                "imageFormat": "png",
                "imageWidth": 1920,
                "imageHeight": 1080,
            },
            raw=True,
        )
        data = base64.b64decode(shot["imageData"].split(",", 1)[1])
        (OUT / "capture-preview.png").write_bytes(data)
        if max(ImageStat.Stat(Image.open(io.BytesIO(data))).stddev) < 2:
            raise RuntimeError("OBS preview is blank; refusing to record it")
        c.send("StartRecord")
        self.recording = True
        print("RECORDING STARTED", flush=True)

    def stop(self):
        if not self.recording:
            return None
        response = self.client.send("StopRecord", raw=True)
        self.recording = False
        filename = Path(response["outputPath"])
        print("Recording saved:", filename, flush=True)
        return filename

    def close(self):
        try:
            self.stop()
            if self.client:
                if getattr(self, "old_collection", None):
                    self.client.send(
                        "SetCurrentSceneCollection",
                        {"sceneCollectionName": self.old_collection},
                    )
                if getattr(self, "old_profile", None):
                    self.client.send(
                        "SetCurrentProfile", {"profileName": self.old_profile}
                    )
        finally:
            if self.process:
                # WM_CLOSE requests a normal exit for this specific helper process.
                user32 = ctypes.windll.user32
                callback = ctypes.WINFUNCTYPE(
                    ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
                )

                def close_window(hwnd, _):
                    pid = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid.value == self.process.pid:
                        user32.PostMessageW(hwnd, 0x0010, 0, 0)
                    return True

                user32.EnumWindows(callback(close_window), 0)
                try:
                    self.process.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    self.process.wait(timeout=8)
            self.config_path.write_bytes(self.original)


def main():
    OUT.mkdir(exist_ok=True)
    recorder = Recorder()
    raw = None
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            args=[
                "--window-size=1920,1080",
                "--start-fullscreen",
                "--disable-session-crashed-bubble",
            ],
            ignore_default_args=["--enable-automation"],
        )
        context = browser.new_context(no_viewport=True, accept_downloads=True)
        page = context.new_page()

        def hold(seconds):
            time.sleep(seconds)

        def top():
            page.evaluate('scrollTo({top:0,behavior:"smooth"})')
            hold(1.2)

        def table_top():
            page.locator(".panel-heading").evaluate(
                'e=>window.scrollTo({top:e.getBoundingClientRect().top+scrollY-30,behavior:"smooth"})'
            )
            hold(1.2)

        def bottom():
            page.locator(".pagination").scroll_into_view_if_needed()
            hold(0.7)

        try:
            page.goto(URL, wait_until="networkidle")
            page.bring_to_front()
            window = context.new_cdp_session(page)
            window_id = window.send('Browser.getWindowForTarget')['windowId']
            window.send('Browser.setWindowBounds', {'windowId':window_id, 'bounds':{'windowState':'fullscreen'}})
            page.wait_for_function('Math.abs(innerHeight-screen.height)<=2 && Math.abs(innerWidth-screen.width)<=2')
            window.detach()
            hold(3)
            recorder.start()
            hold(5)
            page.locator("#theme-toggle").click()
            hold(3)
            page.locator("#theme-toggle").click()
            hold(3)
            page.locator('[data-index="0"] .person-name').click()
            hold(7)
            page.keyboard.press("Escape")
            table_top()
            hold(5)
            bottom()
            page.locator("#next").click()
            expect(page.locator('[data-index="0"] .position')).to_have_text("0011")
            table_top()
            hold(5)
            bottom()
            page.locator("#previous").click()
            expect(page.locator('[data-index="0"] .position')).to_have_text("0001")
            table_top()
            hold(4)
            top()
            page.locator("#locale").select_option("de_DE")
            expect(page.locator('[data-index="0"]')).to_contain_text("Harro Holt")
            hold(3)
            table_top()
            hold(5)
            page.locator('[data-index="0"] .person-name').click()
            hold(6)
            page.keyboard.press("Escape")
            top()
            page.locator("#seed").fill("2026")
            page.locator("#generate").click()
            page.wait_for_function(
                "JSON.parse(document.querySelector('#batch-data').textContent).seed==='2026'"
            )
            hold(3)
            table_top()
            hold(4)
            top()
            page.locator("#seed").fill("42")
            page.locator("#generate").click()
            expect(page.locator('[data-index="0"]')).to_contain_text("Harro Holt")
            table_top()
            hold(4)
            bottom()
            page.locator("#page-number").fill("100000")
            page.locator("#page-number").press("Enter")
            expect(page.locator('[data-index="9"] .position')).to_have_text("1000000")
            table_top()
            hold(4)
            page.locator('[data-index="9"]').scroll_into_view_if_needed()
            page.locator('[data-index="9"] .person-name').click()
            hold(6)
            page.keyboard.press("Escape")
            table_top()
            page.locator("#export-toggle").click()
            hold(2)
            with page.expect_download() as download:
                page.locator("#exports a").first.click()
            download.value.save_as(OUT / "demonstrated-batch.csv")
            page.mouse.click(35, 90)
            hold(2)
            top()
            page.get_by_role("link", name="SQL library", exact=True).click()
            page.wait_for_load_state("networkidle")
            hold(5)
            page.locator("#quick-start").evaluate(
                'e=>e.scrollIntoView({block:"start",behavior:"smooth"})'
            )
            hold(8)
            page.locator("#word").evaluate(
                'e=>e.scrollIntoView({block:"start",behavior:"smooth"})'
            )
            hold(7)
            page.locator("#coordinates").evaluate(
                'e=>e.scrollIntoView({block:"start",behavior:"smooth"})'
            )
            hold(8)
            # Capture only the final complete benchmark; no waiting footage.
            with httpx.Client(trust_env=False, timeout=15) as client:
                result = client.get(URL + "api/benchmark").json()
                if len(result.get("runs", [])) < 6:
                    recorder.client.send("PauseRecord")
                    print(
                        "CAPTURE PAUSED: waiting for six measured benchmark runs",
                        flush=True,
                    )
                    deadline = time.monotonic() + 2400
                    while len(result.get("runs", [])) < 6:
                        if time.monotonic() > deadline:
                            raise RuntimeError("Benchmark did not complete in time")
                        time.sleep(15)
                        result = client.get(URL + "api/benchmark").json()
                    recorder.client.send("ResumeRecord")
                    print("CAPTURE RESUMED: full benchmark available", flush=True)
            page.locator('nav a[href="/benchmark"]').click()
            page.wait_for_load_state("networkidle")
            hold(9)
            page.locator(".doc-body h2").first.evaluate(
                'e=>e.scrollIntoView({block:"start",behavior:"smooth"})'
            )
            hold(9)
            page.locator(".doc-body h2").nth(1).evaluate(
                'e=>e.scrollIntoView({block:"start",behavior:"smooth"})'
            )
            hold(7)
            page.get_by_role("link", name="Generator", exact=True).click()
            page.wait_for_load_state("networkidle")
            hold(4)
            raw = recorder.stop()
        finally:
            try:
                recorder.close()
            finally:
                browser.close()
    if raw:
        target = ROOT / "artifacts/demo.mp4"
        subprocess.run(
            [
                str(FFMPEG),
                "-y",
                "-i",
                str(raw),
                "-map",
                "0:v:0",
                "-c:v",
                "copy",
                "-an",
                "-movflags",
                "+faststart",
                str(target),
            ],
            check=True,
            capture_output=True,
        )
        print("Silent demonstration ready:", target, flush=True)


if __name__ == "__main__":
    main()
