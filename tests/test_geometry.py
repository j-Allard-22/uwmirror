import pytest

from uwmirror.geometry import Region, aspect, center_crop, map_point

SIXTEEN_NINE = 16 / 9


class TestRegion:
    def test_size_properties(self):
        region = Region(1280, 0, 3840, 1440)
        assert region.width == 2560
        assert region.height == 1440
        assert region.size == (2560, 1440)
        assert region.as_tuple() == (1280, 0, 3840, 1440)

    def test_contains(self):
        region = Region(10, 20, 30, 40)
        assert region.contains(10, 20)
        assert region.contains(29, 39)
        assert not region.contains(30, 39)  # right edge is exclusive
        assert not region.contains(29, 40)  # bottom edge is exclusive
        assert not region.contains(9, 20)


class TestCenterCrop:
    def test_5120x1440_crops_to_2560x1440(self):
        """The canonical 32:9 @ 1440p case from the design doc."""
        assert center_crop(5120, 1440, SIXTEEN_NINE) == Region(1280, 0, 3840, 1440)

    def test_3840x1080_crops_to_1920x1080(self):
        """The canonical 32:9 @ 1080p case — pure blit, no scaling."""
        assert center_crop(3840, 1080, SIXTEEN_NINE) == Region(960, 0, 2880, 1080)

    def test_source_already_at_target_aspect_is_full_frame(self):
        assert center_crop(1920, 1080, SIXTEEN_NINE) == Region(0, 0, 1920, 1080)

    def test_source_narrower_than_target_crops_height(self):
        # 16:10 panel mirrored to a 16:9 TV: full width, vertical center crop
        region = center_crop(1920, 1200, SIXTEEN_NINE)
        assert region == Region(0, 60, 1920, 1140)
        assert region.size == (1920, 1080)

    def test_never_hardcodes_4x3(self):
        """Regression guard for the research-report error the design doc corrects."""
        region = center_crop(5120, 1440, SIXTEEN_NINE)
        assert region.size != (1920, 1440)

    @pytest.mark.parametrize("bad", [(0, 1080), (1920, 0), (-1, 1080)])
    def test_invalid_source_raises(self, bad):
        with pytest.raises(ValueError):
            center_crop(bad[0], bad[1], SIXTEEN_NINE)

    def test_invalid_aspect_raises(self):
        with pytest.raises(ValueError):
            center_crop(1920, 1080, 0)


class TestAspect:
    def test_common_ratios(self):
        assert aspect((1920, 1080)) == pytest.approx(SIXTEEN_NINE)
        assert aspect((5120, 1440)) == pytest.approx(32 / 9)

    def test_zero_height_raises(self):
        with pytest.raises(ValueError):
            aspect((1920, 0))


class TestMapPoint:
    REGION = Region(1280, 0, 3840, 1440)
    TARGET = (1920, 1080)

    def test_center_maps_to_center(self):
        assert map_point((2560, 720), self.REGION, self.TARGET) == (960, 540)

    def test_crop_origin_maps_to_zero(self):
        assert map_point((1280, 0), self.REGION, self.TARGET) == (0, 0)

    def test_outside_crop_returns_none(self):
        assert map_point((100, 100), self.REGION, self.TARGET) is None
        assert map_point((3840, 0), self.REGION, self.TARGET) is None  # right-exclusive

    def test_no_scaling_when_sizes_match(self):
        region = Region(960, 0, 2880, 1080)
        assert map_point((960, 0), region, (1920, 1080)) == (0, 0)
        assert map_point((1000, 50), region, (1920, 1080)) == (40, 50)
