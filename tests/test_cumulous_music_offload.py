"""Music dual-mirror classification + free gates (playlists untouched)."""

from __future__ import annotations

from cumulous.music_offload import (
    classify_music_path,
    dual_mirror_music_bytes,
    free_music_on_device_usb,
    freeable_music_items,
    is_freeable_class,
    load_prefs,
    save_prefs,
)


def test_classify_cache_and_playlists():
    assert classify_music_path("/Music/Cache/foo.m4a") == "cache"
    assert classify_music_path("/Music/Cache_LoFi/x.m4a") == "cache"
    assert classify_music_path("/Music/Playlists/MyList.m3u") == "playlist"
    assert classify_music_path("/iTunes_Control/iTunes/Playlists/x.plist") == "playlist"
    assert classify_music_path("/Podcasts/Show/ep1.mp3") == "podcast_media"


def test_downloads_cloud_eligible_when_apple_music(cumulous_home):
    p = load_prefs()
    p["apple_music_subscription_active"] = True
    save_prefs(p)
    assert classify_music_path("/Music/Downloads/abc.m4a") == "cloud_eligible"
    assert classify_music_path("/Music/Downloads/rip.wav") == "local_only"


def test_playlists_and_local_only_never_freeable(cumulous_home):
    assert is_freeable_class("playlist") is False
    assert is_freeable_class("local_only") is False
    assert is_freeable_class("cache") is True
    assert is_freeable_class("cloud_eligible") is True
    assert is_freeable_class("podcast_media") is True


def test_dual_mirror_playlist_not_safe_to_delete(cumulous_home, monkeypatch):
    monkeypatch.setattr(
        "cumulous.nextcloud_client.nextcloud_reachable",
        lambda cfg=None: {"ok": True},
    )
    monkeypatch.setattr(
        "cumulous.nextcloud_client.upload_bytes",
        lambda remote_rel, data, cfg=None: {"ok": True, "status": 201, "url": "mock"},
    )
    res = dual_mirror_music_bytes(
        b"playlist-body",
        device_id="dev1",
        rel_name="Favs.m3u",
        apple_account_id="user@test",
        afc_path="/Music/Playlists/Favs.m3u",
    )
    assert res["ok"] is True
    assert res["dual_ok"] is True
    assert res["class"] == "playlist"
    assert res["safe_to_delete_on_device"] is False
    freeable = freeable_music_items()
    assert not any(i.get("digest") == res["digest"] for i in freeable)


def test_dual_mirror_cache_freeable(cumulous_home, monkeypatch):
    monkeypatch.setattr(
        "cumulous.nextcloud_client.nextcloud_reachable",
        lambda cfg=None: {"ok": True},
    )
    monkeypatch.setattr(
        "cumulous.nextcloud_client.upload_bytes",
        lambda remote_rel, data, cfg=None: {"ok": True, "status": 201, "url": "mock"},
    )
    res = dual_mirror_music_bytes(
        b"cache-audio-bytes",
        device_id="dev1",
        rel_name="c1.m4a",
        apple_account_id="user@test",
        afc_path="/Music/Cache/c1.m4a",
    )
    assert res["class"] == "cache"
    assert res["safe_to_delete_on_device"] is True
    freeable = freeable_music_items()
    assert any(i.get("digest") == res["digest"] for i in freeable)


def test_free_refuses_without_usb_and_never_playlist(cumulous_home, monkeypatch):
    monkeypatch.setattr(
        "cumulous.photo_offload.usb_device_present",
        lambda: {"ok": False, "usb": False, "udid": ""},
    )
    res = free_music_on_device_usb(dry_run=False)
    assert res.get("ok") is False
    assert res.get("error") == "usb_required"
    assert res.get("playlists_untouched") is True
