"""Tests for request-ID deduplication."""

from lucid_agent_core.core.handlers._dedup import _SeenRequestIds


def test_new_id_is_not_duplicate():
    seen = _SeenRequestIds()
    assert seen.check_and_add("abc") is False


def test_same_id_is_duplicate():
    seen = _SeenRequestIds()
    seen.check_and_add("abc")
    assert seen.check_and_add("abc") is True


def test_empty_id_is_never_duplicate():
    seen = _SeenRequestIds()
    assert seen.check_and_add("") is False
    assert seen.check_and_add("") is False


def test_oldest_evicted_at_capacity():
    seen = _SeenRequestIds(maxsize=3)
    seen.check_and_add("a")
    seen.check_and_add("b")
    seen.check_and_add("c")
    # Adding a 4th entry evicts "a"
    seen.check_and_add("d")
    # Inspect internal state directly — calling check_and_add("a") would
    # re-add it (and evict "b"), giving a misleading result.
    assert "a" not in seen._seen
    assert "b" in seen._seen
    assert "c" in seen._seen
    assert "d" in seen._seen


def test_size_stays_bounded():
    maxsize = 100
    seen = _SeenRequestIds(maxsize=maxsize)
    for i in range(maxsize * 3):
        seen.check_and_add(str(i))
    assert len(seen._queue) == maxsize
    assert len(seen._seen) == maxsize
