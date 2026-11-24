"""روابط المنصات المكتشفة في صفحة موقع: صفحات الجهة فقط، بلا فيديوهات ولا تكرار."""
from marsad.monitor.discover import profile_url


def test_youtube_videos_are_not_profiles():
    for h in ("https://www.youtube.com/watch?v=abc", "https://youtu.be/abc", "https://www.youtube.com/embed/abc",
              "https://www.youtube.com/shorts/abc", "https://www.youtube.com/"):
        assert profile_url(h) is None, h


def test_youtube_channel_forms():
    assert profile_url("https://www.youtube.com/@khaberni/videos") == ("youtube", "https://youtube.com/@khaberni")
    assert profile_url("https://m.youtube.com/channel/UCabcdefghijklmnopqrstuv") == (
        "youtube", "https://youtube.com/channel/UCabcdefghijklmnopqrstuv")
    assert profile_url("https://youtube.com/user/khaberni") == ("youtube", "https://youtube.com/user/khaberni")


def test_share_and_post_links_are_skipped():
    for h in ("https://twitter.com/intent/tweet?text=x", "https://x.com/khaberni/status/123",
              "https://www.facebook.com/sharer/sharer.php?u=x", "https://www.facebook.com/khaberni/posts/9",
              "https://t.me/share/url?url=x", "https://www.instagram.com/p/abc/"):
        assert profile_url(h) is None, h


def test_profiles_normalized():
    assert profile_url("https://twitter.com/Khaberni?ref=x") == ("x", "https://twitter.com/Khaberni")
    assert profile_url("https://t.me/s/khaberni") == ("telegram", "https://t.me/khaberni")
    assert profile_url("https://t.me/khaberni/1234") == ("telegram", "https://t.me/khaberni")
    assert profile_url("https://www.facebook.com/khaberni/") == ("facebook", "https://facebook.com/khaberni")
