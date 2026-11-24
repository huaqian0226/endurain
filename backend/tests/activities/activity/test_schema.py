"""Tests for activity schema validators."""

import pytest
from pydantic import ValidationError

import modules.activities.activity.schema as activity_schema


class TestTimezoneCanonicalization:
    """Legacy timezone aliases are stored under their canonical name."""

    def _activity(self, timezone):
        return activity_schema.ActivityBase(distance=0, name="Run", activity_type=1, timezone=timezone)

    def test_legacy_alias_is_canonicalized(self):
        assert self._activity("GB-Eire").timezone == "Europe/London"

    def test_canonical_name_is_kept(self):
        assert self._activity("Europe/Lisbon").timezone == "Europe/Lisbon"

    def test_none_is_kept(self):
        assert self._activity(None).timezone is None


class TestActivityEditElevation:
    """ActivityEdit accepts valid non-negative integer elevation values and rejects invalid ones."""

    def test_accepts_valid_elevation_values_including_zero_and_upper_bound(self):
        patch = activity_schema.ActivityEdit(elevation_gain=181, elevation_loss=172)
        assert patch.model_dump(exclude_unset=True) == {"elevation_gain": 181, "elevation_loss": 172}

        zero_patch = activity_schema.ActivityEdit(elevation_gain=0, elevation_loss=0)
        assert zero_patch.model_dump(exclude_unset=True) == {"elevation_gain": 0, "elevation_loss": 0}

        max_patch = activity_schema.ActivityEdit(elevation_gain=30_000, elevation_loss=30_000)
        assert max_patch.model_dump(exclude_unset=True) == {"elevation_gain": 30_000, "elevation_loss": 30_000}

    def test_omitting_elevation_leaves_fields_unset(self):
        patch = activity_schema.ActivityEdit(name="Morning Ride")
        assert patch.model_dump(exclude_unset=True) == {"name": "Morning Ride"}

    @pytest.mark.parametrize("field", ["elevation_gain", "elevation_loss"])
    @pytest.mark.parametrize("bad_value", [-1, -100, 30_001, 12.5, "180", True, False, None])
    def test_rejects_negative_out_of_range_non_int_and_explicit_null(self, field, bad_value):
        with pytest.raises(ValidationError):
            activity_schema.ActivityEdit.model_validate({field: bad_value})
