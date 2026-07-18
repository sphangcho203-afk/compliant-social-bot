import pytest
from social_bot.content.persona import sanitize_caption


def test_rejects_coercive_outro():
    with pytest.raises(ValueError):
        sanitize_caption("follow us otherwise you'll never see us again")


def test_accepts_normal_caption():
    assert sanitize_caption("bro is cooked 💀") == "bro is cooked 💀"
