"""A rate limiter states how long to wait, and the retry has to honour it."""

from olite.substrate.http import MAX_RETRY_AFTER, retry_after

GEMINI_429 = [
    {
        "error": {
            "code": 429,
            "message": "You exceeded your current quota",
            "details": [
                {"@type": "type.googleapis.com/google.rpc.Help", "links": []},
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "14s"},
            ],
        }
    }
]


def test_the_standard_header_wins():
    assert retry_after({"Retry-After": "30"}, None) == 30.0


def test_google_states_the_delay_in_the_body_not_a_header():
    """Measured against the live API: Gemini sends no Retry-After, only RetryInfo."""
    assert retry_after(None, GEMINI_429) == 14.0


def test_the_body_is_read_whether_parsed_or_raw():
    import json

    assert retry_after(None, json.dumps(GEMINI_429)) == 14.0


def test_an_absent_delay_is_none_so_the_caller_backs_off_itself():
    assert retry_after(None, None) is None
    assert retry_after({}, "not json") is None
    assert retry_after(None, [{"error": {"details": []}}]) is None


def test_a_wild_delay_cannot_hang_the_turn():
    assert retry_after({"Retry-After": "99999"}, None) == MAX_RETRY_AFTER


def test_a_malformed_header_falls_through_rather_than_raising():
    assert retry_after({"Retry-After": "soon"}, GEMINI_429) == 14.0
    assert retry_after({"Retry-After": "soon"}, None) is None


def test_the_delay_the_old_code_would_have_used_was_too_short():
    """The bug this closes: 3s of backoff against a server asking for 14."""
    from olite.substrate.http import INITIAL_BACKOFF, MAX_RETRIES

    guessed = sum(INITIAL_BACKOFF * (2**a) for a in range(MAX_RETRIES - 1))
    assert guessed < retry_after(None, GEMINI_429)
