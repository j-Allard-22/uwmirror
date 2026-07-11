from uwmirror.detect import Monitor, OutputInfo
from uwmirror.diagnose import format_report

OUTPUTS = [
    OutputInfo(device=0, index=0, width=5120, height=1440, rotation=0, primary=True),
    OutputInfo(device=0, index=1, width=1920, height=1080, rotation=0, primary=False),
]
SIZES = [(5120, 1440), (1920, 1080)]
MONITORS = [
    Monitor(0, 0, 5120, 1440, primary=True),
    Monitor(5120, 180, 1920, 1080, primary=False),
]


class TestFormatReport:
    def test_lists_all_three_enumerations(self):
        report = format_report(OUTPUTS, SIZES, MONITORS)
        assert "[0] 5120x1440" in report
        assert "[1] 1920x1080" in report
        assert "(5120, 180) 1920x1080" in report
        assert "primary" in report

    def test_explains_autodetection(self):
        report = format_report(OUTPUTS, SIZES, MONITORS)
        assert "auto-detected source: output 0" in report
        assert "auto-detected target: display 1" in report

    def test_emits_pasteable_config_snippet(self):
        report = format_report(OUTPUTS, SIZES, MONITORS)
        assert "source = 0" in report
        assert "target = 1" in report
        assert "config.toml" in report

    def test_single_display_reports_failure_not_crash(self):
        report = format_report(OUTPUTS[:1], SIZES[:1], MONITORS[:1])
        assert "auto-detected target: FAILED" in report
        assert "Extend" in report

    def test_multi_device_outputs_are_annotated(self):
        outputs = [
            OUTPUTS[0],
            OutputInfo(device=1, index=0, width=1920, height=1080, rotation=0, primary=False),
        ]
        report = format_report(outputs, SIZES, MONITORS)
        assert "(device 0)" in report
        assert "(device 1)" in report
