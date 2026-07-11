import pytest

from uwmirror.detect import (
    DetectionError,
    Monitor,
    OutputInfo,
    choose_source,
    choose_target,
    find_output,
    match_output_to_monitor,
    parse_output_info,
)

DXCAM_TEXT = (
    "Device[0] Output[0]: Res:(5120, 1440) Rot:0 Primary:True\n"
    "Device[0] Output[1]: Res:(1920, 1080) Rot:0 Primary:False\n"
)


def out(index=0, width=5120, height=1440, primary=False, device=0, rotation=0):
    return OutputInfo(
        device=device,
        index=index,
        width=width,
        height=height,
        rotation=rotation,
        primary=primary,
    )


class TestParseOutputInfo:
    def test_parses_dxcam_format(self):
        outputs = parse_output_info(DXCAM_TEXT)
        assert outputs == [
            out(index=0, width=5120, height=1440, primary=True),
            out(index=1, width=1920, height=1080, primary=False),
        ]

    def test_unparseable_text_raises(self):
        with pytest.raises(DetectionError):
            parse_output_info("no outputs here")

    def test_parses_multiple_devices(self):
        text = (
            "Device[0] Output[0]: Res:(5120, 1440) Rot:0 Primary:True\n"
            "Device[1] Output[0]: Res:(1920, 1080) Rot:0 Primary:False\n"
        )
        outputs = parse_output_info(text)
        assert [(o.device, o.index) for o in outputs] == [(0, 0), (1, 0)]


class TestFindOutput:
    def test_finds_by_index(self):
        outputs = [out(index=0), out(index=1, width=1920, height=1080)]
        assert find_output(outputs, 1).width == 1920

    def test_missing_index_raises_with_diagnose_hint(self):
        with pytest.raises(DetectionError, match="diagnose"):
            find_output([out(index=0)], 7)

    def test_same_index_across_devices_prefers_lowest_device(self):
        outputs = [
            out(index=0, device=1, width=1920, height=1080),
            out(index=0, device=0, width=5120, height=1440),
        ]
        assert find_output(outputs, 0).device == 0


class TestChooseSource:
    def test_picks_widest_aspect(self):
        outputs = [out(index=0, width=1920, height=1080), out(index=1, width=5120, height=1440)]
        assert choose_source(outputs).index == 1

    def test_tie_broken_by_primary(self):
        outputs = [
            out(index=0, width=1920, height=1080, primary=False),
            out(index=1, width=1920, height=1080, primary=True),
        ]
        assert choose_source(outputs).index == 1

    def test_full_tie_prefers_lowest_index(self):
        outputs = [out(index=0), out(index=1)]
        assert choose_source(outputs).index == 0


class TestChooseTarget:
    def test_picks_the_other_display(self):
        assert choose_target([(5120, 1440), (1920, 1080)], (5120, 1440)) == 1

    def test_picks_closest_to_16_9_among_candidates(self):
        sizes = [(5120, 1440), (1920, 1200), (1920, 1080)]
        assert choose_target(sizes, (5120, 1440)) == 2

    def test_single_display_raises_with_extend_hint(self):
        with pytest.raises(DetectionError, match="Extend"):
            choose_target([(5120, 1440)], (5120, 1440))

    def test_all_same_resolution_raises(self):
        with pytest.raises(DetectionError, match="--source and --target"):
            choose_target([(1920, 1080), (1920, 1080)], (1920, 1080))


class TestMatchOutputToMonitor:
    def test_matches_by_size_and_primary(self):
        monitors = [
            Monitor(0, 0, 5120, 1440, primary=True),
            Monitor(5120, 0, 1920, 1080, primary=False),
        ]
        match = match_output_to_monitor(out(width=5120, height=1440, primary=True), monitors)
        assert match == monitors[0]

    def test_falls_back_to_size_only_match(self):
        monitors = [Monitor(0, 0, 5120, 1440, primary=False)]
        match = match_output_to_monitor(out(width=5120, height=1440, primary=True), monitors)
        assert match == monitors[0]

    def test_ambiguous_returns_none(self):
        monitors = [
            Monitor(0, 0, 1920, 1080, primary=False),
            Monitor(1920, 0, 1920, 1080, primary=False),
        ]
        assert match_output_to_monitor(out(width=1920, height=1080), monitors) is None

    def test_no_match_returns_none(self):
        monitors = [Monitor(0, 0, 1920, 1080, primary=True)]
        assert match_output_to_monitor(out(width=5120, height=1440), monitors) is None
