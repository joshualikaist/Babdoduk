"""The world cup's music and effects (owner 2026-10-14: "배경음악 ... 킬 수 있도록"): original, synthesized
in js/worldcup.js with the Web Audio API, off until the toggle is pressed. No audio file is shipped and
no audio is fetched from anywhere. The toggle's behaviour in a browser (one AudioContext, aria-pressed,
the remembered choice, never skipping a splash) is checked by scripts/check_site_ui.py (worldcup_sound)."""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac", ".opus", ".weba", ".mid", ".midi", ".webm")


def script():
    return (ROOT / "js/worldcup.js").read_text(encoding="utf-8")


def sound_section():
    return script().split("// ---- sound ----", 1)[1].split("// ---- start gacha", 1)[0]


def test_no_audio_file_is_tracked():
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    audio = [f for f in files if f.lower().endswith(AUDIO_EXTENSIONS)]
    assert not audio, audio


def test_no_audio_is_fetched_and_the_music_is_synthesized():
    page = (ROOT / "worldcup.html").read_text(encoding="utf-8")
    code = script()
    for text in (page, code, (ROOT / "css/worldcup.css").read_text(encoding="utf-8")):
        assert "<audio" not in text and "new Audio(" not in text and "decodeAudioData" not in text
        assert not re.search(r"""['"(][^'"()\s]*\.(mp3|wav|ogg|oga|m4a|aac|flac|opus|weba|midi?)\b""", text, re.I)
    section = sound_section()
    assert "fetch(" not in section and "http" not in section and "src" not in section
    assert "createOscillator()" in section and "createBuffer(" in section            # oscillators and generated noise
    assert "createDynamicsCompressor()" in section                                   # a compressor and a limiter on the mix


def test_the_music_is_an_original_loop_with_two_sections_on_a_look_ahead_clock():
    section = sound_section()
    lead = "".join(re.findall(r"'([1-9a-f.\-]{16})'", section.split("var LEAD =", 1)[1].split(";", 1)[0]))
    assert len(lead) == 256                                                           # 16 bars of 16ths
    assert lead[:128] != lead[128:]                                                   # A and B differ
    assert "var STEP = 60 / 124 / 4;" in section                                      # 124 BPM
    assert "'F Dm Bb C F Dm Bb C Bb C Am Dm Bb C F C'" in section
    # A look-ahead clock: notes are placed on the audio clock a little ahead, never on a repeating timer.
    assert "setInterval" not in section and "AHEAD = 0.12" in section and "timer = setTimeout(loop, WAKE);" in section
    assert "kit.step(pos, next);" in section


def test_the_toggle_is_off_by_default_remembered_and_never_skips_a_splash():
    page = (ROOT / "worldcup.html").read_text(encoding="utf-8")
    section = sound_section()
    dock = page.split('id="wcSoundDock"', 1)[1].split("</div>", 1)[0]
    assert '<div class="wc-sound-dock" id="wcSoundDock" popover="manual" hidden>' in page
    assert 'id="wcSound" aria-pressed="false" data-i18n-aria-key="wc.sound.aria"' in dock
    assert 'data-i18n="wc.sound">배경음악</span>' in dock
    # Outside the splash (aria-hidden decoration), so its clicks never reach the splash's skip.
    splash = page.split('<div class="wc-splash" id="wcSplash"', 1)[1].split("</div>", 1)[0]
    assert "wcSound" not in splash
    assert "var KEY = 'babdoduk-worldcup-sound'" in section
    assert "wanted = false;" in section and "if (supported && !reduced) {" in section   # off on a first visit; reduced motion: every visit
    assert "ctx = new AC();" in section and section.count("new AC(") == 1                # one context, made from a press
    assert "if (!live()) return;" in section                                           # effects only while it is on
    assert "if (document.hidden) {" in section and "ctx.suspend();" in section          # sleeps with the tab
    code = script()
    assert "if (sound.owns(e.target) && (e.key === 'Enter' || e.key === ' ')) return;   // the sound toggle never skips" in code
    assert code.count("sound.raise();") == 2                                           # above the splash and the gacha
    assert "sound.endScene(reason);" in code
    css = (ROOT / "css/worldcup.css").read_text(encoding="utf-8")
    assert ".wc-sound:focus-visible {" in css and "min-height: 44px;" in css.split(".wc-sound {", 1)[1].split("}", 1)[0]


def test_the_toggle_has_its_words_in_both_languages():
    ko = json.loads((ROOT / "i18n/ko.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "i18n/en.json").read_text(encoding="utf-8"))
    assert (ko["wc.sound"], ko["wc.sound.aria"]) == ("배경음악", "배경음악 켜기/끄기")
    assert (en["wc.sound"], en["wc.sound.aria"]) == ("Music", "Turn music on/off")
    # The visible word is part of the name (WCAG 2.5.3).
    assert ko["wc.sound"] in ko["wc.sound.aria"] and en["wc.sound"].lower() in en["wc.sound.aria"].lower()


def test_every_game_moment_has_its_effect():
    code = script()
    for effect in ("pop", "blip", "tick", "ding", "whoosh", "hit", "boom", "crank", "capsule", "tada", "fanfare"):
        assert re.search(r"\b" + effect + r": function \(t, o", sound_section()), effect
    assert "else { sound.fx('pop'); choose(cat, true); }" in code                 # a tile
    assert "sound.fx('tick');" in code and "sound.fx('ding');" in code             # 아무거나 spins and lands
    assert "sound.fx('blip', 0, game.winners.length" in code                       # a pick, higher through the round
    assert "sound.fx('fanfare', 150);" in code                                     # the winner
    assert "['boom', 1100]" in code and "['hit', 170]" in code                     # 결승's crash, 8강/4강's hit
    assert "plan.push(['crank', T0 + c * G.crank]);" in code and "['tada', tD + 200]" in code
