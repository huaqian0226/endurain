"""Tests for the Strava-export bulk-import source.

These behaviours used to live on ``BulkImportSource`` in the activities module,
which meant activities imported Strava while Strava imported the ingestion entry
point. They are asserted here, against the subclass, because that is where the
knowledge belongs.
"""

from unittest.mock import MagicMock, patch

import pytest

import core.exceptions as core_exceptions
import modules.activities.activity.contracts as activity_contracts
import modules.strava.bulk_import_source as strava_bulk_import_source


def _activity() -> activity_contracts.ActivityCore:
    return activity_contracts.ActivityCore(
        user_id=1,
        name="Workout",
        distance=1000,
        activity_type=1,
        start_time="2023-10-21T07:41:47",
        end_time="2023-10-21T08:41:47",
    )


def _source(**kwargs) -> strava_bulk_import_source.StravaBulkImportSource:
    return strava_bulk_import_source.StravaBulkImportSource(**kwargs)


class TestSourceKind:
    def test_it_is_still_a_bulk_import(self):
        # The pipeline narrows on the base type, so the subclass must satisfy it.
        assert _source().kind == "bulk_import"
        assert isinstance(_source(), strava_bulk_import_source.activity_ingestion_integration.BulkImportSource)


class TestMetadataFor:
    def test_no_metadata_without_an_initiated_time(self):
        assert _source(strava_activities={"f.fit": {}}).metadata_for("f.fit") == {}

    @patch("modules.strava.bulk_import_source.strava_bulk_import_utils")
    def test_builds_the_full_metadata_dict_from_the_csv(self, mock_utils):
        mock_utils.build_metadata_dict.return_value = {"name": "Morning Ride"}
        source = _source(
            import_initiated_time="2026-07-21T00:00:00",
            strava_activities={"f.fit": {}},
            gear_nickname_to_id={"Bike": 3},
        )

        assert source.metadata_for("f.fit") == {"name": "Morning Ride"}
        mock_utils.build_metadata_dict.assert_called_once_with(
            "f.fit", {"f.fit": {}}, "2026-07-21T00:00:00", {"Bike": 3}
        )

    def test_falls_back_to_the_plain_import_record_without_a_csv(self):
        source = _source(import_initiated_time="2026-07-21T00:00:00")

        assert source.metadata_for("f.gpx")["import_dict"]["import_source"] == "Basic bulk import"


class TestShouldImport:
    """Strava lists a multi-activity .fit once per activity it contains."""

    def test_single_activity_file_is_always_imported(self):
        source = _source(strava_activities={"f.fit": {}})
        assert source.should_import("activity", {"metadata_found_in_csv": True}, activities_in_file=1) is True

    def test_imports_when_the_csv_has_no_row_for_the_file(self):
        source = _source(strava_activities={"f.fit": {}})
        assert source.should_import("activity", {"metadata_found_in_csv": False}, activities_in_file=5) is True

    @patch("modules.strava.bulk_import_source.strava_bulk_import_utils")
    def test_imports_the_activity_whose_start_time_matches_the_csv(self, mock_utils):
        mock_utils.does_activity_start_time_match_the_data_in_strava_activities_csv.return_value = True
        source = _source(strava_activities={"f.fit": {}})

        assert source.should_import("activity", {"metadata_found_in_csv": True}, activities_in_file=5) is True

    @patch("modules.strava.bulk_import_source.strava_bulk_import_utils")
    def test_skips_the_activities_the_csv_row_does_not_refer_to(self, mock_utils):
        mock_utils.does_activity_start_time_match_the_data_in_strava_activities_csv.return_value = False
        source = _source(strava_activities={"f.fit": {}})

        assert source.should_import("activity", {"metadata_found_in_csv": True}, activities_in_file=5) is False
        mock_utils.does_activity_start_time_match_the_data_in_strava_activities_csv.assert_called_once()


class TestApplyMetadata:
    def test_it_reuses_the_shared_applier(self):
        activity = _activity()

        _source().apply_metadata(activity, {"name": "Morning Ride", "gear_id": 4})

        assert (activity.name, activity.gear_id) == ("Morning Ride", 4)


class TestImportSideArtifacts:
    @patch("modules.strava.bulk_import_source.strava_bulk_import_utils")
    def test_attaches_the_sidecar_photos_to_the_last_created_activity(self, mock_utils):
        created = ["first", "last"]
        read_member = object()
        source = _source(strava_activities={"f.fit": {}}, read_member=read_member)

        source.import_side_artifacts(created, "f.fit", "db")

        mock_utils.import_media_from_strava_bulk_export.assert_called_once_with(
            {"f.fit": {}}, "last", "f.fit", read_member, "db"
        )

    @patch("modules.strava.bulk_import_source.strava_bulk_import_utils")
    def test_nothing_to_attach_without_created_activities(self, mock_utils):
        _source(strava_activities={"f.fit": {}}, read_member=object()).import_side_artifacts([], "f.fit", "db")

        mock_utils.import_media_from_strava_bulk_export.assert_not_called()

    @patch("modules.strava.bulk_import_source.strava_bulk_import_utils")
    def test_nothing_to_attach_without_a_way_to_read_the_archive(self, mock_utils):
        _source(strava_activities={"f.fit": {}}).import_side_artifacts(["a"], "f.fit", "db")

        mock_utils.import_media_from_strava_bulk_export.assert_not_called()


class TestExportLayout:
    def test_activity_files_are_those_directly_in_the_activities_folder(self):
        is_activity = strava_bulk_import_source._is_activity_member

        assert is_activity("activities/123.fit.gz")
        assert is_activity("activities/45.gpx")
        assert not is_activity("activities.csv")
        assert not is_activity("media/photo.jpg")
        assert not is_activity("activities/readme.txt")
        assert not is_activity("activities/.DS_Store")

    def test_the_export_is_its_manifest_activities_and_photos_only(self):
        is_export = strava_bulk_import_source._is_export_member

        assert is_export("activities.csv")
        assert is_export("activities/1.fit")
        assert is_export("media/p.jpg")
        # Anything else a user keeps in that folder is left alone.
        assert not is_export("notes.txt")
        assert not is_export("bikes.csv")


class TestBuildSource:
    def test_it_parses_the_manifest_and_reads_the_users_gear(self, monkeypatch):
        read = lambda name: b"csv" if name == "activities.csv" else None  # noqa: E731
        monkeypatch.setattr(
            strava_bulk_import_source.strava_bulk_import_utils,
            "parse_activities_manifest",
            lambda path: {"1.fit": {"Activity Name": "Ride"}},
        )
        monkeypatch.setattr(
            strava_bulk_import_source.strava_bulk_import_utils,
            "create_gear_dictionary_for_bulk_import",
            lambda user_id, db: {"Bike": [3]},
        )
        monkeypatch.setattr(strava_bulk_import_source, "SessionLocal", MagicMock())

        source = strava_bulk_import_source._build_source(7, "2026-10-15T00:00:00", read)

        assert source.strava_activities == {"1.fit": {"Activity Name": "Ride"}}
        assert source.gear_nickname_to_id == {"Bike": [3]}
        assert (source.user_id, source.import_initiated_time) == (7, "2026-10-15T00:00:00")
        assert source.read_member is read

    def test_an_archive_without_a_manifest_is_not_a_strava_export(self):
        with pytest.raises(core_exceptions.InvalidInputError):
            strava_bulk_import_source._build_source(7, "t", lambda name: None)

    def test_an_unparseable_manifest_is_refused(self, monkeypatch):
        monkeypatch.setattr(
            strava_bulk_import_source.strava_bulk_import_utils, "parse_activities_manifest", lambda path: None
        )

        with pytest.raises(core_exceptions.InvalidInputError):
            strava_bulk_import_source._build_source(7, "t", lambda name: b"garbage")

    def test_the_format_is_registered_under_strava(self):
        from modules.activities.activity_ingestion import provider_registry

        provider_registry.clear()
        strava_bulk_import_source.register_bulk_import_format()

        registered = provider_registry.get_bulk_format("strava")
        assert registered is not None
        assert registered.drop_directory(5).endswith("/5")
        provider_registry.clear()


class TestChineseExportEndToEnd:
    """Synthetic Chinese Strava export flows through source build, GPX parse, metadata, matching, and media."""

    SYNTHETIC_GPX = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx creator="Synthetic" version="1.1" xmlns="http://www.topografix.com/GPX/1/1">\n'
        "  <metadata><time>2026-09-10T09:27:12Z</time></metadata>\n"
        "  <trk>\n"
        "    <name>原始轨迹名</name>\n"
        "    <type>cycling</type>\n"
        "    <trkseg>\n"
        '      <trkpt lat="31.2304" lon="121.4737"><ele>10.0</ele><time>2026-09-10T09:27:12Z</time></trkpt>\n'
        '      <trkpt lat="31.2314" lon="121.4747"><ele>12.0</ele><time>2026-09-10T09:28:12Z</time></trkpt>\n'
        "    </trkseg>\n"
        "  </trk>\n"
        "</gpx>\n"
    )

    def test_chinese_export_manifest_gpx_gear_and_media_import_cleanly(self, tmp_path, monkeypatch):
        import modules.activities.activity.constants as activity_constants
        import modules.activities.activity_file_import.gpx_utils as gpx_utils
        import modules.strava.bulk_import_utils as bulk_import_utils

        manifest_csv = (
            "活动 ID,活动日期,活动名称,活动类型,活动描述,全程耗时,距离,通勤,活动装备,文件名,全程耗时,距离,通勤,媒体\n"
            "555001,2026年9月10日 09:27:12,合成晨骑,骑行,顺风很舒服,60,0.15,false,合成公路车,"
            "activities/555001.gpx,60.0,150.0,0.0,media/pic1.jpg\n"
        ).encode()

        archive_members = {
            "activities.csv": manifest_csv,
            "media/pic1.jpg": b"fake-jpeg-bytes",
        }
        read_member = archive_members.get

        monkeypatch.setattr(
            strava_bulk_import_source.strava_bulk_import_utils,
            "create_gear_dictionary_for_bulk_import",
            lambda user_id, db: {"合成公路车": [17]},
        )
        monkeypatch.setattr(strava_bulk_import_source, "SessionLocal", MagicMock())

        source = strava_bulk_import_source._build_source(7, "2026-09-10T10:00:00Z", read_member)

        gpx_path = tmp_path / "555001.gpx"
        gpx_path.write_text(self.SYNTHETIC_GPX, encoding="utf-8")
        parsed = gpx_utils.parse_gpx_file(str(gpx_path), 7, activity_name_input=None, default_timezone="UTC")
        activity = parsed["activity"]

        metadata = source.metadata_for("555001.gpx")
        assert metadata["metadata_found_in_csv"] is True
        assert metadata["activity type"] == "Ride"
        assert activity_constants.define_activity_type(metadata["activity type"]) == 4

        assert source.should_import(activity, metadata, activities_in_file=2) is True
        mismatched = activity.model_copy(update={"start_time": "2026-09-10T11:27:12Z"})
        assert source.should_import(mismatched, metadata, activities_in_file=2) is False

        source.apply_metadata(activity, metadata)
        assert activity.name == "合成晨骑"
        assert activity.description == "顺风很舒服"
        assert activity.gear_id == 17
        assert activity.activity_type == 4
        assert activity.import_info["strava_activity_id"] == 555001

        store_media = MagicMock()
        monkeypatch.setattr(bulk_import_utils, "create_activity_media_from_strava_bulk_import", store_media)
        source.import_side_artifacts([MagicMock(id=99)], "555001.gpx", MagicMock())
        store_media.assert_called_once()
        assert store_media.call_args.args[:3] == (99, "pic1.jpg", b"fake-jpeg-bytes")

    def test_english_export_manifest_gpx_gear_and_media_regression(self, tmp_path, monkeypatch):
        import modules.activities.activity_file_import.gpx_utils as gpx_utils
        import modules.strava.bulk_import_utils as bulk_import_utils

        manifest_csv = (
            b"Activity ID,Activity Date,Activity Name,Activity Type,Activity Description,"
            b"Elapsed Time,Distance,Commute,Activity Gear,Filename,Elapsed Time,Distance,Commute,Media\n"
            b'555002,"Sep 10, 2026, 9:27:12 AM",Synthetic Ride,Ride,Smooth tailwind,60,0.15,false,Roadster,'
            b"activities/555002.gpx,60.0,150.0,0.0,media/en1.jpg\n"
        )

        archive_members = {
            "activities.csv": manifest_csv,
            "media/en1.jpg": b"fake-en-jpeg",
        }
        read_member = archive_members.get

        monkeypatch.setattr(
            strava_bulk_import_source.strava_bulk_import_utils,
            "create_gear_dictionary_for_bulk_import",
            lambda user_id, db: {"Roadster": [21]},
        )
        monkeypatch.setattr(strava_bulk_import_source, "SessionLocal", MagicMock())

        source = strava_bulk_import_source._build_source(7, "2026-09-10T10:00:00Z", read_member)

        gpx_path = tmp_path / "555002.gpx"
        gpx_path.write_text(self.SYNTHETIC_GPX, encoding="utf-8")
        parsed = gpx_utils.parse_gpx_file(str(gpx_path), 7, activity_name_input=None, default_timezone="UTC")
        activity = parsed["activity"]

        metadata = source.metadata_for("555002.gpx")
        assert metadata["metadata_found_in_csv"] is True
        assert metadata["activity type"] == "Ride"
        assert source.should_import(activity, metadata, activities_in_file=2) is True

        source.apply_metadata(activity, metadata)
        assert activity.name == "Synthetic Ride"
        assert activity.description == "Smooth tailwind"
        assert activity.gear_id == 21
        assert activity.activity_type == 4
        assert activity.import_info["strava_activity_id"] == 555002

        store_media = MagicMock()
        monkeypatch.setattr(bulk_import_utils, "create_activity_media_from_strava_bulk_import", store_media)
        source.import_side_artifacts([MagicMock(id=100)], "555002.gpx", MagicMock())
        store_media.assert_called_once()
        assert store_media.call_args.args[:3] == (100, "en1.jpg", b"fake-en-jpeg")
