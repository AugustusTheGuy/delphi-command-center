from pathlib import Path

from components.splash import SPLASH_MARKUP, SPLASH_SECONDS


def test_splash_runs_the_cross_then_the_four_marks():
    marks = ["✖️", "➗", "➕", "➖"]
    positions = [SPLASH_MARKUP.index(mark) for mark in marks]
    assert positions == sorted(positions)
    assert "dhc-arm-h" in SPLASH_MARKUP
    assert "dhc-arm-v" in SPLASH_MARKUP
    assert SPLASH_MARKUP.index("dhc-arm-h") < SPLASH_MARKUP.index("dhc-arm-v")
    assert SPLASH_MARKUP.index("@keyframes dhc-h") < SPLASH_MARKUP.index("@keyframes dhc-v")
    assert SPLASH_MARKUP.index("@keyframes dhc-v") < SPLASH_MARKUP.index("@keyframes dhc-x")
    assert SPLASH_MARKUP.index("@keyframes dhc-x") < SPLASH_MARKUP.index("@keyframes dhc-d")
    assert SPLASH_MARKUP.index("@keyframes dhc-d") < SPLASH_MARKUP.index("@keyframes dhc-p")
    assert SPLASH_MARKUP.index("@keyframes dhc-p") < SPLASH_MARKUP.index("@keyframes dhc-m")
    assert "@keyframes dhc-flash" in SPLASH_MARKUP
    assert "brightness(10)" in SPLASH_MARKUP
    assert "prefers-reduced-motion" in SPLASH_MARKUP
    assert "<script" not in SPLASH_MARKUP.lower()
    assert SPLASH_SECONDS == 6.7


def test_launch_does_not_block_on_a_sleep():
    text = (Path(__file__).resolve().parents[2] / "delphi_command_center.py").read_text()
    assert "time.sleep" not in text
    assert "render_splash" in text
    assert "nav_page" in text
    assert "st.tabs(" not in text
