"""Tests for Strava gear utility functions."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

import modules.strava.gear_utils as gear_utils


def test_shoe_csv_is_parsed_from_the_path_it_is_given(tmp_path):
    """The upload is parsed where the caller saved it; no configured directory is consulted."""
    shoes_file = tmp_path / "gear.csv"
    shoes_file.write_text("Shoe Name,Shoe Brand,Shoe Model\nPegasus,Nike,Pegasus\n")

    shoes = gear_utils.iterate_over_shoes_csv(str(shoes_file))

    assert shoes == [{"Shoe Name": "Pegasus", "Shoe Brand": "Nike", "Shoe Model": "Pegasus"}]


def test_bike_csv_is_parsed_from_the_path_it_is_given(tmp_path):
    bikes_file = tmp_path / "gear.csv"
    bikes_file.write_text("Bike Name,Bike Brand,Bike Model\nCommuter,Trek,Domane\n")

    bikes = gear_utils.iterate_over_bikes_csv(str(bikes_file))

    assert bikes == {"Commuter": {"Bike Name": "Commuter", "Bike Brand": "Trek", "Bike Model": "Domane"}}


def test_a_csv_with_the_wrong_headers_is_refused(tmp_path):
    from fastapi import HTTPException

    bikes_file = tmp_path / "gear.csv"
    bikes_file.write_text("Name,Brand\nCommuter,Trek\n")

    with pytest.raises(HTTPException):
        gear_utils.iterate_over_bikes_csv(str(bikes_file))


def test_bike_transform_strips_whitespace():
    """Bike brand, model, and nickname are stripped of whitespace."""
    bikes_dict = {
        " Trek ": {"Bike Brand": " Trek ", "Bike Model": " Domane "},
    }
    gears = gear_utils.transform_csv_bike_gear_to_schema_gear(bikes_dict, 1)
    assert len(gears) == 1
    assert gears[0].brand == "Trek"
    assert gears[0].model == "Domane"
    assert gears[0].nickname == "Trek"


def test_bike_transform_none_fields():
    """None brand/model are preserved as None, not crashed."""
    bikes_dict = {
        "Commuter": {"Bike Brand": None, "Bike Model": None},
    }
    gears = gear_utils.transform_csv_bike_gear_to_schema_gear(bikes_dict, 1)
    assert len(gears) == 1
    assert gears[0].brand is None
    assert gears[0].model is None
    assert gears[0].nickname == "Commuter"


def test_bike_transform_empty_string_brand():
    """Empty string brand is handled safely."""
    bikes_dict = {
        "Road Bike": {"Bike Brand": "", "Bike Model": "Defy"},
    }
    gears = gear_utils.transform_csv_bike_gear_to_schema_gear(bikes_dict, 1)
    assert len(gears) == 1
    assert gears[0].brand is None
    assert gears[0].model == "Defy"


def test_bike_transform_multiple_bikes():
    """Multiple bikes are all processed with stripping."""
    bikes_dict = {
        "Road": {"Bike Brand": "Giant ", "Bike Model": " TCR "},
        "MTB": {"Bike Brand": " Specialized", "Bike Model": "Stumpjumper"},
    }
    gears = gear_utils.transform_csv_bike_gear_to_schema_gear(bikes_dict, 1)
    assert len(gears) == 2
    assert gears[0].brand == "Giant"
    assert gears[0].model == "TCR"
    assert gears[1].brand == "Specialized"
    assert gears[1].model == "Stumpjumper"


def test_shoe_transform_strips_whitespace():
    """Shoe brand, model, and name are stripped of whitespace."""
    shoes_list = [
        {"Shoe Name": " Pegasus ", "Shoe Brand": " Nike ", "Shoe Model": " Pegasus "},
    ]
    gears = gear_utils.transform_csv_shoe_gear_to_schema_gear(shoes_list, 1, Mock())
    assert len(gears) == 1
    assert gears[0].brand == "Nike"
    assert gears[0].model == "Pegasus"
    assert gears[0].nickname == "Pegasus"


def test_shoe_transform_none_brand_model():
    """None brand/model are preserved as None, not crashed."""
    shoes_list = [
        {"Shoe Name": "Speedsters", "Shoe Brand": None, "Shoe Model": None},
    ]
    gears = gear_utils.transform_csv_shoe_gear_to_schema_gear(shoes_list, 1, Mock())
    assert len(gears) == 1
    assert gears[0].brand is None
    assert gears[0].model is None
    assert gears[0].nickname == "Speedsters"


def test_shoe_transform_trailing_plus_encoded(monkeypatch):
    """Shoe name trailing whitespace is stripped."""
    monkeypatch.setattr(gear_utils.core_config, "STRAVA_BULK_IMPORT_SHOES_UNNAMED_SHOE", "Unnamed Shoe ")
    monkeypatch.setattr(gear_utils.gears_crud, "get_gear_user_by_nickname", lambda uid, name, db: None)
    monkeypatch.setattr(gear_utils, "logger", Mock())

    shoes_list = [
        {"Shoe Name": "Pegasus+ ", "Shoe Brand": "Nike", "Shoe Model": "Pegasus"},
    ]
    gears = gear_utils.transform_csv_shoe_gear_to_schema_gear(shoes_list, 1, Mock())
    assert len(gears) == 1
    assert gears[0].nickname == "Pegasus+"


def test_shoe_transform_blank_name(monkeypatch):
    """Blank shoe name gets renamed to default name."""
    monkeypatch.setattr(gear_utils.core_config, "STRAVA_BULK_IMPORT_SHOES_UNNAMED_SHOE", "Unnamed Shoe ")
    monkeypatch.setattr(gear_utils.gears_crud, "get_gear_user_by_nickname", lambda uid, name, db: None)
    logger = Mock()
    monkeypatch.setattr(gear_utils, "logger", logger)

    shoes_list = [
        {"Shoe Name": None, "Shoe Brand": "Nike", "Shoe Model": "Pegasus"},
    ]
    gears = gear_utils.transform_csv_shoe_gear_to_schema_gear(shoes_list, 1, Mock())
    assert len(gears) == 1
    assert gears[0].nickname == "Unnamed Shoe 1"
    assert gears[0].brand == "Nike"
    assert gears[0].model == "Pegasus"
    assert len(logger.method_calls) == 1


def test_shoe_transform_multiple_shoes():
    """Multiple shoes are all processed with stripping."""
    shoes_list = [
        {"Shoe Name": " Speed ", "Shoe Brand": " Nike", "Shoe Model": " Vaporfly "},
        {"Shoe Name": "Trail  ", "Shoe Brand": " Hoka ", "Shoe Model": " Speedgoat"},
    ]
    gears = gear_utils.transform_csv_shoe_gear_to_schema_gear(shoes_list, 1, Mock())
    assert len(gears) == 2
    assert gears[0].brand == "Nike"
    assert gears[0].nickname == "Speed"
    assert gears[1].brand == "Hoka"
    assert gears[1].nickname == "Trail"


def test_shoe_transform_empty_string_name(monkeypatch):
    """Empty string shoe name gets renamed."""
    monkeypatch.setattr(gear_utils.core_config, "STRAVA_BULK_IMPORT_SHOES_UNNAMED_SHOE", "Unnamed Shoe ")
    monkeypatch.setattr(gear_utils.gears_crud, "get_gear_user_by_nickname", lambda uid, name, db: None)
    monkeypatch.setattr(gear_utils, "logger", Mock())

    shoes_list = [
        {"Shoe Name": "", "Shoe Brand": "Adidas", "Shoe Model": "Adios"},
    ]
    gears = gear_utils.transform_csv_shoe_gear_to_schema_gear(shoes_list, 1, Mock())
    assert len(gears) == 1
    assert gears[0].nickname == "Unnamed Shoe 1"


class TestChineseLocalizedGearCsv:
    """Chinese-localized Strava bikes.csv and shoes.csv imports."""

    def test_chinese_bikes_csv_normalizes_headers_and_transforms(self, tmp_path):
        bikes_file = tmp_path / "bikes.csv"
        bikes_file.write_text(
            "\ufeff自行车名,自行车品牌,自行车型号,自行车默认的运动类型\n"
            '青风公路车,捷安特,TCR Advanced,""\n'
            'Commuter-ZH,Merida,Scultura,"骑行"\n',
            encoding="utf-8",
        )

        bikes = gear_utils.iterate_over_bikes_csv(str(bikes_file))

        assert list(bikes) == ["青风公路车", "Commuter-ZH"]
        assert bikes["青风公路车"] == {
            "Bike Name": "青风公路车",
            "Bike Brand": "捷安特",
            "Bike Model": "TCR Advanced",
            "Bike Default Sport Types": "",
        }

        gears = gear_utils.transform_csv_bike_gear_to_schema_gear(bikes, 9)
        assert [(g.nickname, g.brand, g.model) for g in gears] == [
            ("青风公路车", "捷安特", "TCR Advanced"),
            ("Commuter-ZH", "Merida", "Scultura"),
        ]

    def test_chinese_shoes_csv_normalizes_headers_and_handles_blank_name(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gear_utils.core_config, "STRAVA_BULK_IMPORT_SHOES_UNNAMED_SHOE", "Unnamed Shoe ")
        monkeypatch.setattr(gear_utils.gears_crud, "get_gear_user_by_nickname", lambda uid, name, db: None)
        monkeypatch.setattr(gear_utils, "logger", Mock())

        shoes_file = tmp_path / "shoes.csv"
        shoes_file.write_text(
            "\ufeff鞋名,鞋品牌,鞋型号,鞋子默认的运动类型\n飞马跑鞋,耐克,Pegasus 41,跑步\n,亚瑟士,Kayano,\n",
            encoding="utf-8",
        )

        shoes = gear_utils.iterate_over_shoes_csv(str(shoes_file))

        assert shoes == [
            {
                "Shoe Name": "飞马跑鞋",
                "Shoe Brand": "耐克",
                "Shoe Model": "Pegasus 41",
                "Shoe Default Sport Types": "跑步",
            },
            {
                "Shoe Name": "",
                "Shoe Brand": "亚瑟士",
                "Shoe Model": "Kayano",
                "Shoe Default Sport Types": "",
            },
        ]

        gears = gear_utils.transform_csv_shoe_gear_to_schema_gear(shoes, 9, Mock())
        assert [(g.nickname, g.brand, g.model) for g in gears] == [
            ("飞马跑鞋", "耐克", "Pegasus 41"),
            ("Unnamed Shoe 1", "亚瑟士", "Kayano"),
        ]

    def test_direct_transform_accepts_chinese_keyed_rows(self):
        bike_gears = gear_utils.transform_csv_bike_gear_to_schema_gear(
            {"城市车": {"自行车品牌": " 迪卡侬 ", "自行车型号": " Triban "}},
            5,
        )
        assert [(g.nickname, g.brand, g.model) for g in bike_gears] == [("城市车", "迪卡侬", "Triban")]

        shoe_gears = gear_utils.transform_csv_shoe_gear_to_schema_gear(
            [{"鞋名": " 慢跑鞋 ", "鞋品牌": " 美津浓 ", "鞋型号": " Rider "}],
            5,
            Mock(),
        )
        assert [(g.nickname, g.brand, g.model) for g in shoe_gears] == [("慢跑鞋", "美津浓", "Rider")]

    def test_missing_bike_headers_keeps_424_detail_and_logs_chinese_names(self, tmp_path, monkeypatch):
        from fastapi import HTTPException

        logger = Mock()
        monkeypatch.setattr(gear_utils, "logger", logger)
        bikes_file = tmp_path / "bikes.csv"
        bikes_file.write_text("名称,品牌\n测试车,某品牌\n", encoding="utf-8")

        with pytest.raises(HTTPException) as exc_info:
            gear_utils.iterate_over_bikes_csv(str(bikes_file))

        assert exc_info.value.status_code == 424
        assert exc_info.value.detail == "Invalid file. Proper headers not found in Strava bikes CSV file."
        log_text = " ".join(str(call.args[0]) for call in logger.info.call_args_list)
        assert "自行车名" in log_text
        assert "自行车品牌" in log_text
        assert "自行车型号" in log_text

    def test_missing_shoe_headers_keeps_424_detail_and_logs_chinese_names(self, tmp_path, monkeypatch):
        from fastapi import HTTPException

        logger = Mock()
        monkeypatch.setattr(gear_utils, "logger", logger)
        shoes_file = tmp_path / "shoes.csv"
        shoes_file.write_text("名称,品牌\n测试鞋,某品牌\n", encoding="utf-8")

        with pytest.raises(HTTPException) as exc_info:
            gear_utils.iterate_over_shoes_csv(str(shoes_file))

        assert exc_info.value.status_code == 424
        assert exc_info.value.detail == "Invalid file. Proper headers not found in Strava shoes CSV file."
        log_text = " ".join(str(call.args[0]) for call in logger.info.call_args_list)
        assert "鞋名" in log_text
        assert "鞋品牌" in log_text
        assert "鞋型号" in log_text
