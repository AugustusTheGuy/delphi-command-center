from core.theme import get_theme_css


def test_three_colors_are_in_the_css():
    css = get_theme_css("dark", {"primary": "#112233", "secondary": "#445566", "tertiary": "#0E0A14"})
    assert "#112233" in css and "#445566" in css and "#0E0A14" in css


def test_rejects_css_injection():
    css = get_theme_css("dark", {"primary": "#112233;background:url(https://evil.example)"})
    assert "evil.example" not in css
    assert "#6A0DAD" in css
