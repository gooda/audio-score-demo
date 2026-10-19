"""E2E: .venv/bin/python e2e_test.py  (server on :8765). Fake mic + real uploads + screenshots."""
import json
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8765"
HUM = "/home/box/agent-data/agents/f63b6a42-3b6a-43f9-9f29-d381c182acf8/attachments/834fa8ef513227032c5a289d47bb434d85fd5bda1e6fa8448225e57fd8292dbb.m4a"
ES = "/home/box/agent-data/agents/f63b6a42-3b6a-43f9-9f29-d381c182acf8/attachments/5a9f21281b5e9cf09c7025e1a509809800a0858ca590ecc521415f9d75894835.m4a"
out = {}

def wait_result(pg):
    pg.evaluate("window.__r = result"); pg.wait_for_function("(typeof result!=='undefined' && result && result!==window.__r) || document.querySelector('#status').textContent.includes('❌')", timeout=60000)
    st = pg.inner_text('#status')
    if st: print('STATUS', st)
    pg.wait_for_selector("#results:not(.hidden)"); pg.wait_for_timeout(1600)

def score_info(pg):
    return pg.evaluate("({overall: result.overall, passed: result.passed, ac: result.anti_cheat.pass, ms: result.elapsed_ms, dims: Object.fromEntries(Object.entries(result.dims).map(([k,d])=>[k,d.score]))})")

with sync_playwright() as p:
    for fake, lvl in [("samples/a_near_perfect_user.wav", "hum_melody"), ("/workspace/fake_es.wav", "es_hola")]:
        b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                    f"--use-file-for-fake-audio-capture={fake}", "--autoplay-policy=no-user-gesture-required"])
        for tag, vp in [("desktop", {"width": 1280, "height": 800}), ("mobile", {"width": 390, "height": 844})]:
            pg = b.new_page(viewport=vp, device_scale_factor=2 if tag == "mobile" else 1)
            pg.on("console", lambda m: m.type == "error" and print("console:", m.text))
            pg.goto(f"{BASE}/?level={lvl}"); pg.wait_for_timeout(2000)
            if lvl == "hum_melody":
                pg.screenshot(path=f"screenshots/{tag}_1_level.png", full_page=True)
            pg.click("#btnRec"); pg.wait_for_timeout(1500 if lvl == "es_hola" else 2000)
            if lvl == "hum_melody":
                pg.locator("#recCard").screenshot(path=f"screenshots/{tag}_2_recording.png")
            pg.click("#btnRec"); wait_result(pg)
            out[f"{tag}_fakemic_{lvl}"] = score_info(pg)
            if lvl == "es_hola":
                pg.close(); continue
            # meme result with the user's real hum take; expand secondary panels
            pg.set_input_files("#fileIn", HUM); wait_result(pg)
            out[f"{tag}_real_hum"] = score_info(pg)
            pg.click("#pitchCard summary"); pg.click("#rhythmCard summary"); pg.wait_for_timeout(400)
            pg.locator("#mainCmp").click(position={"x": 120, "y": 60}); pg.wait_for_timeout(500)
            pg.locator("#results").screenshot(path=f"screenshots/{tag}_4_meme_results.png")
            # foreign result with the real Spanish take
            pg.goto(BASE + "/?level=es_hola"); pg.wait_for_timeout(2000)
            pg.set_input_files("#fileIn", ES); wait_result(pg)
            out[f"{tag}_real_es"] = score_info(pg)
            pg.locator("#diffStrip").click(position={"x": 30, "y": 10}); pg.wait_for_timeout(600)
            pg.locator("#results").screenshot(path=f"screenshots/{tag}_3_foreign_results.png")
            pg.locator("#mainCard").screenshot(path=f"screenshots/{tag}_5_main_wave.png")
            pg.click("#vSpec"); pg.wait_for_timeout(300)
            pg.locator("#mainCard").screenshot(path=f"screenshots/{tag}_6_main_spectrogram.png")
            pg.close()
        b.close()
print(json.dumps(out, ensure_ascii=False, indent=1))
