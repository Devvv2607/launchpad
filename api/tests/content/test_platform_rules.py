from __future__ import annotations

from launchpad.content.platform_rules import normalize_hashtags, validate, x_weighted_length
from launchpad.domain.enums import Channel


def rules(channel: Channel, content: dict[str, object]) -> set[tuple[str, str]]:
    return {(v.rule, v.severity) for v in validate(channel, content)}


def test_x_weighting_counts_urls_as_23_and_emoji_as_2() -> None:
    assert x_weighted_length("hello") == 5
    assert x_weighted_length("see https://example.com/a/very/long/path?x=1") == 4 + 23
    assert x_weighted_length("chai ☕") == 5 + 2
    assert x_weighted_length("नमस्ते") == 6  # Devanagari counts as 1 per code point


def test_instagram_limits_and_norms() -> None:
    ok = {
        "caption": "Rainy day? Cutting chai is on us.\nCome by.",
        "hashtags": ["#a1", "#b2", "#c3"],
    }
    assert rules(Channel.INSTAGRAM_POST, ok) == set()
    long = {**ok, "caption": "x" * 2300}
    assert ("max_chars", "error") in rules(Channel.INSTAGRAM_POST, long)
    link = {**ok, "caption": "Order at https://chai.example now, lovely chai for everyone today"}
    assert ("no_links", "warning") in rules(Channel.INSTAGRAM_POST, link)
    many = {**ok, "hashtags": [f"#t{i}" for i in range(31)]}
    assert ("hashtag_count", "error") in rules(Channel.INSTAGRAM_POST, many)
    some = {**ok, "hashtags": [f"#t{i}" for i in range(12)]}
    assert rules(Channel.INSTAGRAM_POST, some) == {("hashtag_count", "warning")}
    spam = {**ok, "hashtags": ["#follow4follow", "#a1", "#b2"]}
    assert ("hashtag_format", "error") in rules(Channel.INSTAGRAM_POST, spam)


def test_hook_before_fold_warning() -> None:
    caption = "Hi\n" + "We have a very long story to tell about chai. " * 10
    assert ("hook_before_fold", "warning") in rules(
        Channel.LINKEDIN_POST, {"text": caption, "hashtags": ["#a", "#b", "#c"]}
    )


def test_carousel_slide_rules() -> None:
    slide = {"headline": "Chai", "body": "Charcoal-brewed."}
    base = {"caption": "Swipe for our monsoon menu.", "hashtags": ["#a", "#b", "#c"]}
    assert ("slide_count", "error") in rules(
        Channel.INSTAGRAM_CAROUSEL, {**base, "slides": [slide] * 3}
    )
    assert rules(Channel.INSTAGRAM_CAROUSEL, {**base, "slides": [slide] * 6}) == set()
    long_headline = [{**slide, "headline": "H" * 61}] + [slide] * 5
    assert ("max_chars", "error") in rules(
        Channel.INSTAGRAM_CAROUSEL, {**base, "slides": long_headline}
    )


def test_x_single_and_thread() -> None:
    assert (
        rules(Channel.X_POST, {"mode": "single", "posts": ["Chai time."], "hashtags": []}) == set()
    )
    assert ("max_chars", "error") in rules(
        Channel.X_POST, {"mode": "single", "posts": ["x" * 281], "hashtags": []}
    )
    assert ("thread_length", "error") in rules(
        Channel.X_POST, {"mode": "thread", "posts": ["one"], "hashtags": []}
    )
    # Hashtags on the last post count toward its limit.
    near = {"mode": "single", "posts": ["x" * 270], "hashtags": ["#monsoonchai"]}
    assert ("max_chars", "error") in rules(Channel.X_POST, near)


def test_email_rules() -> None:
    email = {
        "subject_variants": ["Monsoon chai is here", "x" * 70, "y" * 101],
        "preheader": "short",
        "sections": [{"type": "hero", "heading": "Hi"}],
    }
    got = rules(Channel.EMAIL, email)
    assert ("subject_length", "warning") in got and ("subject_length", "error") in got
    assert ("preheader_length", "warning") in got and ("cta_missing", "error") in got


def test_normalize_hashtags() -> None:
    assert normalize_hashtags(
        ["# Mumbai Rains", "#mumbairains", "chai!", "#f4f", "#", "#बारिश"]
    ) == [
        "#MumbaiRains",
        "#chai",
        "#बारिश",
    ]
