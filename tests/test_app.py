import itertools

import pytest
from fakes import FakeCapture, FakePresenter, FakeScreen, ScriptedCommands

from uwmirror.app import AppState, Command, LoopDeps, reduce_state, run_loop
from uwmirror.capture import CaptureLost
from uwmirror.recovery import RetryPolicy

SIXTEEN_NINE = 16 / 9


class TestReduceState:
    def test_no_commands_is_identity(self):
        state = AppState()
        assert reduce_state(state, []) == state

    def test_quit(self):
        assert reduce_state(AppState(), [Command.QUIT]).running is False

    def test_pause_toggles(self):
        state = reduce_state(AppState(), [Command.TOGGLE_PAUSE])
        assert state.paused is True
        assert reduce_state(state, [Command.TOGGLE_PAUSE]).paused is False

    def test_blank_toggles_independently_of_pause(self):
        state = reduce_state(AppState(paused=True), [Command.TOGGLE_BLANK])
        assert state == AppState(running=True, paused=True, blanked=True)

    def test_multiple_commands_fold_in_order(self):
        state = reduce_state(AppState(), [Command.TOGGLE_PAUSE, Command.QUIT])
        assert state.paused is True
        assert state.running is False


def make_deps(
    script: list[list[Command]],
    captures: list[FakeCapture],
    presenter: FakePresenter | None = None,
) -> tuple[LoopDeps, FakePresenter, list[int]]:
    presenter = presenter or FakePresenter()
    ticks: list[int] = []
    pool = list(captures)

    def factory():
        if not pool:
            raise AssertionError("backend factory called more times than expected")
        return pool.pop(0)

    deps = LoopDeps(
        backend_factory=factory,
        presenter=presenter,
        screen=FakeScreen(),
        make_overlay=lambda backend, region: None,
        get_commands=ScriptedCommands(script),
        policy=RetryPolicy(sleep=lambda _s: None),
        tick=ticks.append,
        fps=60,
        target_aspect=SIXTEEN_NINE,
    )
    return deps, presenter, ticks


class TestRunLoop:
    def test_presents_frames_until_quit(self):
        capture = FakeCapture()
        deps, presenter, ticks = make_deps([[], [], []], [capture])
        run_loop(deps)
        assert presenter.presented == [(2560, 1440)] * 3
        assert presenter.flips == 3
        assert capture.stopped
        assert len(ticks) == 3

    def test_backend_started_with_center_crop_region(self):
        capture = FakeCapture(width=5120, height=1440)
        deps, _, _ = make_deps([[]], [capture])
        run_loop(deps)
        assert capture.started_region is not None
        assert capture.started_region.as_tuple() == (1280, 0, 3840, 1440)
        assert capture.started_fps == 60

    def test_pause_freezes_presentation(self):
        capture = FakeCapture()
        script = [[], [Command.TOGGLE_PAUSE], [], [], [Command.TOGGLE_PAUSE], []]
        deps, presenter, _ = make_deps(script, [capture])
        run_loop(deps)
        assert len(presenter.presented) == 3  # before pause, on unpause tick, after
        assert capture.frame_calls == 3

    def test_blank_paints_black_once_and_recovers(self):
        capture = FakeCapture()
        script = [[], [Command.TOGGLE_BLANK], [], [], [Command.TOGGLE_BLANK], []]
        deps, presenter, _ = make_deps(script, [capture])
        run_loop(deps)
        assert presenter.blanks == 1  # painted once on entry, then idle
        assert len(presenter.presented) == 3

    def test_capture_lost_recreates_backend(self):
        first = FakeCapture(fail_on_frames={2})
        second = FakeCapture()
        deps, presenter, _ = make_deps([[], [], [], []], [first, second])
        run_loop(deps)
        assert first.stopped
        assert second.stopped
        assert len(presenter.presented) == 3  # tick 2 lost to the failure
        assert deps.policy.failures == 0  # reset after successful frame

    def test_factory_failure_retries_with_backoff(self):
        sleeps: list[float] = []

        calls = {"n": 0}
        good = FakeCapture()

        def flaky_factory():
            calls["n"] += 1
            if calls["n"] == 1:
                raise CaptureLost("monitor asleep")
            return good

        deps, presenter, _ = make_deps([[], []], [])
        deps.backend_factory = flaky_factory
        deps.policy = RetryPolicy(sleep=sleeps.append)
        run_loop(deps)
        assert calls["n"] == 2
        assert sleeps == [0.5]
        assert len(presenter.presented) == 1

    def test_quit_before_first_frame_never_creates_backend(self):
        deps, presenter, _ = make_deps([[Command.QUIT]], [])
        run_loop(deps)  # factory pool is empty; creating a backend would assert
        assert presenter.presented == []

    def test_on_state_fires_initially_and_on_change_only(self):
        capture = FakeCapture()
        seen: list[AppState] = []
        script = [[], [Command.TOGGLE_PAUSE], [], [Command.TOGGLE_PAUSE]]
        deps, _, _ = make_deps(script, [capture])
        deps.on_state = seen.append
        run_loop(deps)
        # initial(unpaused) + toggle to paused + toggle back + final QUIT state
        assert seen[0] == AppState()
        assert AppState(paused=True) in seen
        assert seen[-1].running is False
        # no consecutive duplicates (fires only when state changes)
        assert all(a != b for a, b in itertools.pairwise(seen))

    def test_overlay_drawn_on_screen_after_present(self):
        drawn: list[object] = []

        class Overlay:
            def draw(self, screen):
                drawn.append(screen)

        capture = FakeCapture()
        deps, _, _ = make_deps([[], []], [capture])
        deps.make_overlay = lambda backend, region: Overlay()
        run_loop(deps)
        assert len(drawn) == 2
        assert all(s is deps.screen for s in drawn)


class TestRunWiring:
    """Exercise app.run() end-to-end under the dummy SDL driver."""

    def test_quit_event_exits_cleanly(self, monkeypatch: pytest.MonkeyPatch):
        import pygame

        from uwmirror import app, capture

        monkeypatch.setattr(
            capture,
            "output_info_text",
            lambda backend="dxcam": "Device[0] Output[0]: Res:(5120, 1440) Rot:0 Primary:True\n",
        )
        from uwmirror.config import Settings

        pygame.init()
        pygame.event.post(pygame.event.Event(pygame.QUIT))
        settings = Settings(target=0, windowed=True, hotkeys=False, cursor=False, tray=False)
        assert app.run(settings) == 0

    def test_bad_target_index_raises_detection_error(self, monkeypatch: pytest.MonkeyPatch):
        from uwmirror import app, capture
        from uwmirror.config import Settings
        from uwmirror.detect import DetectionError

        monkeypatch.setattr(
            capture,
            "output_info_text",
            lambda backend="dxcam": "Device[0] Output[0]: Res:(5120, 1440) Rot:0 Primary:True\n",
        )
        with pytest.raises(DetectionError, match="diagnose"):
            app.run(Settings(target=99, hotkeys=False, cursor=False))

    def test_bad_source_index_raises_detection_error(self, monkeypatch: pytest.MonkeyPatch):
        from uwmirror import app, capture
        from uwmirror.config import Settings
        from uwmirror.detect import DetectionError

        monkeypatch.setattr(
            capture,
            "output_info_text",
            lambda backend="dxcam": "Device[0] Output[0]: Res:(5120, 1440) Rot:0 Primary:True\n",
        )
        with pytest.raises(DetectionError, match="no dxcam output"):
            app.run(Settings(source=7, hotkeys=False, cursor=False, tray=False))
