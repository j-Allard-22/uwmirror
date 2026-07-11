import pytest

from uwmirror.recovery import RetryPolicy


def make_policy(**kwargs):
    sleeps: list[float] = []
    policy = RetryPolicy(sleep=sleeps.append, **kwargs)
    return policy, sleeps


class TestRetryPolicy:
    def test_backoff_doubles_and_caps(self):
        policy, sleeps = make_policy(initial_delay=0.5, max_delay=5.0, factor=2.0)
        for _ in range(6):
            policy.wait()
        assert sleeps == [0.5, 1.0, 2.0, 4.0, 5.0, 5.0]

    def test_reset_restarts_from_initial_delay(self):
        policy, sleeps = make_policy(initial_delay=0.5, max_delay=5.0)
        policy.wait()
        policy.wait()
        policy.reset()
        policy.wait()
        assert sleeps == [0.5, 1.0, 0.5]

    def test_failure_counter(self):
        policy, _ = make_policy()
        assert policy.failures == 0
        policy.wait()
        policy.wait()
        assert policy.failures == 2
        policy.reset()
        assert policy.failures == 0

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"initial_delay": 0},
            {"initial_delay": 2.0, "max_delay": 1.0},
            {"factor": 0.5},
        ],
    )
    def test_invalid_parameters_raise(self, kwargs):
        with pytest.raises(ValueError):
            RetryPolicy(**kwargs)
