"""Tests for Strava bulk-import file handling."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

import core.exceptions as core_exceptions
import modules.activities.activity.constants as activity_constants
import modules.activities.activity.contracts as activity_contracts
import modules.strava.bulk_import_utils as bulk_import_utils
import modules.strava.utils as strava_utils
from core.file_uploads import UploadKind


def _activity(start_time: str) -> activity_contracts.ActivityCore:
    """An ActivityCore as the FIT parser produces it (start_time coerced to aware UTC)."""
    return activity_contracts.ActivityCore(
        user_id=1,
        name="Workout",
        distance=1000,
        activity_type=1,
        start_time=start_time,
        end_time="2023-10-21T08:41:47",
    )


class TestDoesActivityStartTimeMatchTheCsv:
    """Selects which activity of a multi-activity .fit a Strava CSV row refers to."""

    def test_matching_start_times_are_recognised(self):
        # Regression: ActivityCore coerces start_time to an aware datetime at
        # construction, but this comparison parsed it as an ISO *string*. That
        # raised TypeError for every multi-activity .fit in a Strava export,
        # which the bulk entry caught and turned into "move the whole file to
        # the import-error directory" — so none of its activities imported.
        assert (
            bulk_import_utils.does_activity_start_time_match_the_data_in_strava_activities_csv(
                _activity("2023-10-21T07:41:47"),
                {"activity date": "Oct 21, 2023, 7:41:47 AM"},
            )
            is True
        )

    def test_differing_start_times_are_rejected(self):
        assert (
            bulk_import_utils.does_activity_start_time_match_the_data_in_strava_activities_csv(
                _activity("2023-10-21T07:41:47"),
                {"activity date": "Oct 21, 2023, 8:13:28 AM"},
            )
            is False
        )

    @pytest.mark.parametrize(
        ("activity_start", "csv_date"),
        [
            ("2026-09-10T09:27:12Z", "2026年9月10日 09:27:12"),
            ("2026-09-01T09:07:02Z", "2026年09月01日 09:07:02"),
            ("2026-09-01T09:07:02Z", "2026年9月1日 9:7:2"),
            ("2024-11-12T13:47:44Z", "2024年11月12日 13:47:44"),
            ("2023-10-05T07:04:07Z", "Oct 05, 2023, 07:04:07 AM"),
            ("2023-10-05T20:04:07Z", "Oct 5, 2023, 8:04:07 PM"),
        ],
    )
    def test_chinese_and_padded_start_times_match(self, activity_start, csv_date):
        assert (
            bulk_import_utils.does_activity_start_time_match_the_data_in_strava_activities_csv(
                _activity(activity_start),
                {"activity date": csv_date},
            )
            is True
        )

    def test_chinese_differing_start_time_is_rejected(self):
        assert (
            bulk_import_utils.does_activity_start_time_match_the_data_in_strava_activities_csv(
                _activity("2026-09-10T09:27:12Z"),
                {"activity date": "2026年9月10日 10:27:12"},
            )
            is False
        )

    @pytest.mark.parametrize(
        "metadata",
        [
            {"activity date": "not-a-date"},
            {"activity date": ""},
            {"activity date": "   "},
            {"activity date": None},
            {"activity date": 12345},
            {},
        ],
    )
    def test_unparseable_or_missing_csv_date_returns_false_without_crashing(self, metadata):
        assert (
            bulk_import_utils.does_activity_start_time_match_the_data_in_strava_activities_csv(
                _activity("2026-09-10T09:27:12Z"),
                metadata,
            )
            is False
        )


class _MockGear:
    def __init__(self, gear_id: int, brand: str | None, model: str | None, nickname: str):
        self.id = gear_id
        self.brand = brand
        self.model = model
        self.nickname = nickname


def test_media_is_validated_as_an_image_before_it_is_stored(monkeypatch):
    """The bytes are checked through the upload pipeline before the media module sees them."""
    validate = Mock()
    store_media = Mock()
    monkeypatch.setattr(bulk_import_utils.file_uploads, "validate_local_file_sync", validate)
    monkeypatch.setattr(bulk_import_utils.activity_media_integration, "attach_media_bytes", store_media)

    bulk_import_utils.create_activity_media_from_strava_bulk_import(7, "photo.jpg", b"image-bytes", Mock())

    assert validate.call_args.kwargs == {"kind": UploadKind.IMAGE, "filename": "photo.jpg"}
    # The media module owns the key and the storage area; only bytes cross over.
    assert store_media.call_args.args[:3] == (7, "photo.jpg", b"image-bytes")


def test_invalid_media_is_rejected_before_it_is_stored(monkeypatch):
    validate = Mock(side_effect=core_exceptions.InvalidInputError("bad image"))
    store_media = Mock()
    monkeypatch.setattr(bulk_import_utils.file_uploads, "validate_local_file_sync", validate)
    monkeypatch.setattr(bulk_import_utils.activity_media_integration, "attach_media_bytes", store_media)

    bulk_import_utils.create_activity_media_from_strava_bulk_import(7, "photo.jpg", b"not an image", Mock())

    store_media.assert_not_called()


class TestMediaFromTheArchive:
    def _activity(self):
        return Mock(id=11)

    def test_each_listed_photo_is_read_from_the_exports_media_folder(self, monkeypatch):
        store = Mock()
        monkeypatch.setattr(bulk_import_utils, "create_activity_media_from_strava_bulk_import", store)
        read = Mock(side_effect=lambda name: {"media/a.jpg": b"A", "media/b.jpg": b"B"}.get(name))
        rows = {"ride.fit": {"Media": "media/a.jpg|media/b.jpg"}}

        bulk_import_utils.import_media_from_strava_bulk_export(rows, self._activity(), "ride.fit", read, Mock())

        assert [call.args[1:3] for call in store.call_args_list] == [("a.jpg", b"A"), ("b.jpg", b"B")]

    def test_a_photo_missing_from_the_export_is_skipped_not_fatal(self, monkeypatch):
        store = Mock()
        monkeypatch.setattr(bulk_import_utils, "create_activity_media_from_strava_bulk_import", store)
        read = Mock(side_effect=lambda name: b"B" if name == "media/b.jpg" else None)
        rows = {"ride.fit": {"Media": "media/a.jpg|media/b.jpg"}}

        bulk_import_utils.import_media_from_strava_bulk_export(rows, self._activity(), "ride.fit", read, Mock())

        assert store.call_count == 1

    def test_a_row_without_media_reads_nothing(self, monkeypatch):
        read = Mock()
        rows = {"ride.fit": {"Media": "  "}}

        bulk_import_utils.import_media_from_strava_bulk_export(rows, self._activity(), "ride.fit", read, Mock())

        read.assert_not_called()

    def test_a_path_in_the_manifest_cannot_reach_outside_the_media_folder(self, monkeypatch):
        """Only the base name is used, so a crafted entry cannot name another member."""
        read = Mock(return_value=None)
        rows = {"ride.fit": {"Media": "../activities/secret.fit"}}

        bulk_import_utils.import_media_from_strava_bulk_export(rows, self._activity(), "ride.fit", read, Mock())

        read.assert_called_once_with("media/secret.fit")


class TestParseActivitiesManifest:
    HEADER = "Activity ID,Activity Date,Activity Name,Activity Type,Activity Description,Elapsed Time,Filename,Activity Gear,Media\n"

    def _write(self, tmp_path, body: str) -> str:
        path = tmp_path / "activities.csv"
        path.write_text(body)
        return str(path)

    def test_rows_are_keyed_by_the_files_base_name(self, tmp_path):
        path = self._write(
            tmp_path, self.HEADER + '1,"Oct 21, 2023, 7:41:47 AM",Ride,Ride,,10,activities/123.fit.gz,Bike,\n'
        )

        parsed = bulk_import_utils.parse_activities_manifest(path)

        assert list(parsed) == ["123.fit.gz"]
        assert parsed["123.fit.gz"]["Activity Name"] == "Ride"

    def test_a_manifest_without_the_required_headers_is_refused(self, tmp_path):
        path = self._write(tmp_path, "Activity ID,Filename\n1,activities/1.fit\n")

        assert bulk_import_utils.parse_activities_manifest(path) is None

    def test_an_unreadable_manifest_is_refused_not_raised(self, tmp_path):
        assert bulk_import_utils.parse_activities_manifest(str(tmp_path / "missing.csv")) is None

    def test_chinese_manifest_with_duplicate_headers_parses_all_needed_columns(self, tmp_path):
        header = (
            "\ufeff活动 ID,活动日期,活动名称,活动类型,活动描述,全程耗时,距离,最大心率,相对负荷度,通勤,"
            "活动隐私说明,活动装备,文件名,全程耗时,距离,最大心率,相对负荷度,通勤,媒体,标签\n"
        )
        row1 = (
            '900001,2026年9月10日 09:27:12,海滨合成骑行,骑行,"第一行\n第二行",3600,32.5,170,80,false,'
            ",合成公路车,activities/900001.gpx,3600.0,32500.0,170.0,80.0,0.0,media/a.jpg|media/b.jpg,riding\n"
        )
        row2 = (
            "900002,2026年9月11日 06:15:00,未知项目测试,外星滑翔,,1200,5.0,,,true,"
            ",,activities/900002.gpx,1200.0,5000.0,,,1.0,,\n"
        )
        path = self._write(tmp_path, header + row1 + row2)

        parsed = bulk_import_utils.parse_activities_manifest(path)

        assert parsed is not None
        assert list(parsed) == ["900001.gpx", "900002.gpx"]
        first = parsed["900001.gpx"]
        assert first["Activity ID"] == "900001"
        assert first["Activity Date"] == "2026年9月10日 09:27:12"
        assert first["Activity Name"] == "海滨合成骑行"
        assert first["Activity Type"] == "Ride"
        assert first["Activity Description"] == "第一行\n第二行"
        assert first["Activity Gear"] == "合成公路车"
        assert first["Filename"] == "activities/900001.gpx"
        assert first["Media"] == "media/a.jpg|media/b.jpg"

        second = parsed["900002.gpx"]
        assert second["Activity Type"] == "外星滑翔"

    def test_chinese_manifest_with_elevation_and_duplicate_headers_parses_elevation(self, tmp_path):
        header = (
            "\ufeff活动 ID,活动日期,活动名称,活动类型,活动描述,全程耗时,距离,活动装备,文件名,"
            "全程耗时,距离,海拔爬升,降低海拔,低海拔,高海拔,媒体\n"
        )
        row = (
            "900010,2026年9月12日 08:00:00,平路起伏合成骑行,骑行,测试海拔,3600,30.0,合成公路车,"
            "activities/900010.gpx,3600.0,30000.0,180.6,172.4,5.0,62.0,\n"
        )
        path = self._write(tmp_path, header + row)

        parsed = bulk_import_utils.parse_activities_manifest(path)

        assert parsed is not None
        assert parsed["900010.gpx"]["Elevation Gain"] == "180.6"
        assert parsed["900010.gpx"]["Elevation Loss"] == "172.4"

    def test_missing_headers_log_includes_chinese_header_names(self, tmp_path, monkeypatch):
        logger = Mock()
        monkeypatch.setattr(bulk_import_utils, "logger", logger)
        path = self._write(tmp_path, "活动 ID,文件名\n1,activities/1.gpx\n")

        assert bulk_import_utils.parse_activities_manifest(path) is None
        log_text = " ".join(str(call.args[0]) for call in logger.error.call_args_list)
        assert "活动日期" in log_text
        assert "活动名称" in log_text
        assert "活动类型" in log_text
        assert "活动装备" in log_text
        assert "媒体" in log_text


class TestParseStravaElevationMeters:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("0", 0),
            ("0.0", 0),
            ("-0.0", 0),
            (0, 0),
            ("0.4", 0),
            ("0.5", 1),
            ("2.5", 3),
            ("180.4", 180),
            ("180.5", 181),
            ("180.6", 181),
            ("  42.5  ", 43),
            (180, 180),
            (180.5, 181),
            ("30000", 30000),
            ("29999.6", 30000),
        ],
    )
    def test_parses_valid_values_with_half_up_rounding(self, raw, expected):
        assert bulk_import_utils.parse_strava_elevation_meters(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "   ",
            "-0.1",
            "-10",
            -1,
            "30000.1",
            "30001",
            "999999",
            "nan",
            "NaN",
            "inf",
            "-inf",
            "Infinity",
            "1e1000",
            "abc",
            "180.6m",
            True,
            False,
            float("nan"),
            float("inf"),
            float("-inf"),
            ["180"],
        ],
    )
    def test_rejects_empty_or_invalid_values(self, raw):
        assert bulk_import_utils.parse_strava_elevation_meters(raw) is None


class TestBuildMetadataAndActivityTypeMapping:
    def test_chinese_manifest_row_builds_canonical_metadata_and_matches_gear(self):
        rows = {
            "900001.gpx": {
                "活动 ID": "900001",
                "活动日期": "2026年9月10日 09:27:12",
                "活动名称": "海滨合成骑行",
                "活动类型": "骑行",
                "活动描述": "逆风骑行",
                "活动装备": "合成公路车",
                "文件名": "activities/900001.gpx",
                "媒体": "media/photo.jpg",
                "海拔爬升": "180.6",
                "降低海拔": "175.5",
            }
        }

        metadata = bulk_import_utils.build_metadata_dict(
            "900001.gpx",
            rows,
            "2026-09-10T12:00:00Z",
            {"合成公路车": [42]},
        )

        assert metadata["metadata_found_in_csv"] is True
        assert metadata["name"] == "海滨合成骑行"
        assert metadata["description"] == "逆风骑行"
        assert metadata["activity type"] == "Ride"
        assert metadata["activity date"] == "2026年9月10日 09:27:12"
        assert metadata["gear_id"] == 42
        assert metadata["elevation_gain"] == 181
        assert metadata["elevation_loss"] == 176
        assert metadata["import_dict"]["strava_activity_id"] == 900001

    def test_build_metadata_dict_handles_zero_alias_and_omits_invalid_elevation(self):
        rows = {
            "zero.gpx": {
                "Activity ID": "101",
                "Activity Date": "Sep 10, 2026, 9:27:12 AM",
                "Activity Name": "Flat Ride",
                "Activity Type": "Ride",
                "Activity Description": "",
                "Activity Gear": "",
                "Filename": "activities/zero.gpx",
                "Media": "",
                "Elevation Gain": "0",
                "Elevation Loss": "0.0",
            },
            "alt_zh.gpx": {
                "活动 ID": "102",
                "活动日期": "2026年9月10日 09:27:12",
                "活动名称": "备用列名",
                "活动类型": "骑行",
                "活动描述": "",
                "活动装备": "",
                "文件名": "activities/alt_zh.gpx",
                "媒体": "",
                "海拔爬升": " 12.5 ",
                "海拔下降": " 11.4 ",
            },
            "invalid.gpx": {
                "Activity ID": "103",
                "Activity Date": "Sep 10, 2026, 9:27:12 AM",
                "Activity Name": "Bad Elevation",
                "Activity Type": "Ride",
                "Activity Description": "",
                "Activity Gear": "",
                "Filename": "activities/invalid.gpx",
                "Media": "",
                "Elevation Gain": "-5",
                "Elevation Loss": "",
            },
            "old_csv.gpx": {
                "Activity ID": "104",
                "Activity Date": "Sep 10, 2026, 9:27:12 AM",
                "Activity Name": "No Elevation Columns",
                "Activity Type": "Ride",
                "Activity Description": "",
                "Activity Gear": "",
                "Filename": "activities/old_csv.gpx",
                "Media": "",
            },
        }

        zero_meta = bulk_import_utils.build_metadata_dict("zero.gpx", rows, "2026-09-10T12:00:00Z", {})
        assert zero_meta["elevation_gain"] == 0
        assert zero_meta["elevation_loss"] == 0

        alt_meta = bulk_import_utils.build_metadata_dict("alt_zh.gpx", rows, "2026-09-10T12:00:00Z", {})
        assert alt_meta["elevation_gain"] == 13
        assert alt_meta["elevation_loss"] == 11

        invalid_meta = bulk_import_utils.build_metadata_dict("invalid.gpx", rows, "2026-09-10T12:00:00Z", {})
        assert "elevation_gain" not in invalid_meta
        assert "elevation_loss" not in invalid_meta

        old_meta = bulk_import_utils.build_metadata_dict("old_csv.gpx", rows, "2026-09-10T12:00:00Z", {})
        assert "elevation_gain" not in old_meta
        assert "elevation_loss" not in old_meta

    @pytest.mark.parametrize(
        ("zh_label", "en_label"),
        [
            ("骑行", "Ride"),
            ("跑步", "Run"),
            ("越野跑", "Trail Run"),
            ("虚拟骑行", "Virtual Ride"),
            ("虚拟跑步", "Virtual Run"),
            ("砾石路骑行", "Gravel Ride"),
            ("山地自行车骑行", "MountainBikeRide"),
            ("游泳", "Swim"),
            ("步行", "Walk"),
            ("徒步", "Hike"),
            ("锻炼", "Workout"),
            ("力量训练", "WeightTraining"),
            ("瑜伽", "Yoga"),
            ("乒乓球", "TableTennis"),
            ("轮滑", "InlineSkate"),
            ("电动自行车骑行", "E-Bike Ride"),
        ],
    )
    def test_chinese_activity_types_map_to_same_internal_id_as_english(self, zh_label, en_label):
        mapped = strava_utils.normalize_strava_activity_type(zh_label)
        assert activity_constants.define_activity_type(mapped) == activity_constants.define_activity_type(en_label)

    def test_every_chinese_activity_type_alias_resolves_to_expected_id(self):
        for zh_label, en_label in strava_utils.STRAVA_ACTIVITY_TYPE_ALIASES.items():
            resolved = activity_constants.define_activity_type(strava_utils.normalize_strava_activity_type(zh_label))
            if en_label == "Workout":
                assert resolved == 10
            else:
                assert resolved != 10, f"{zh_label!r} -> {en_label!r} fell back to Workout(10)"

    def test_english_and_unknown_activity_types_pass_through_unchanged(self):
        assert strava_utils.normalize_strava_activity_type("Ride") == "Ride"
        assert strava_utils.normalize_strava_activity_type("Skydiving") == "Skydiving"
        assert strava_utils.normalize_strava_activity_type("自定义运动") == "自定义运动"
        assert activity_constants.define_activity_type(strava_utils.normalize_strava_activity_type("自定义运动")) == 10
        assert strava_utils.normalize_strava_activity_type(None) is None


def _gear(monkeypatch, items):
    monkeypatch.setattr(bulk_import_utils.gears_crud, "get_gear_user", lambda uid, db: items)


def test_gear_dictionary_normal(monkeypatch):
    """Smoosh key is built correctly with clean values."""
    _gear(monkeypatch, [_MockGear(gear_id=1, brand="Nike", model="Pegasus", nickname="Fast Shoes")])

    result = bulk_import_utils.create_gear_dictionary_for_bulk_import(42, Mock())

    assert result["Fast Shoes"] == [1]
    assert result["Nike Pegasus Fast Shoes"] == [1]


def test_gear_dictionary_strips_surrounding_whitespace(monkeypatch):
    _gear(monkeypatch, [_MockGear(gear_id=2, brand="Nike ", model=" Pegasus ", nickname="Fast Shoes ")])

    result = bulk_import_utils.create_gear_dictionary_for_bulk_import(42, Mock())

    assert result["Nike Pegasus Fast Shoes"] == [2]


def test_gear_dictionary_handles_missing_brand_and_model(monkeypatch):
    _gear(monkeypatch, [_MockGear(gear_id=3, brand=None, model=None, nickname="Unbranded")])

    assert bulk_import_utils.create_gear_dictionary_for_bulk_import(42, Mock())["Unbranded"] == [3]


def test_a_user_with_no_gear_gets_an_empty_map_not_an_aborted_import(monkeypatch):
    """No gear only means no activity is linked to one; the import still runs."""
    _gear(monkeypatch, None)

    assert bulk_import_utils.create_gear_dictionary_for_bulk_import(42, Mock()) == {}
