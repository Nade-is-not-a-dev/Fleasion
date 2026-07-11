import json
from unittest.mock import patch

from Fleasion.proxy.addons import texture_stripper as texture_stripper_module
from Fleasion.proxy.addons.texture_stripper import TextureStripper, _decode_texpack_slot_quality


class _Config:
    def get_all_replacements(self):
        return {}, set(), {}, {}


def test_batch_request_ignores_dummy_id_replacements():
    stripper = TextureStripper(_Config())
    body = json.dumps([
        {"assetId": 100, "requestId": "a"},
        {"assetId": 101, "requestId": "b"},
        {"assetId": 102, "requestId": "c"},
    ]).encode()

    modified, scraper_body = stripper.process_batch_request(
        body,
        {},
        ({100: 0, 101: 1, 102: 999}, set(), {}, {}),
        "batch",
    )

    assert json.loads(modified) == [
        {"assetId": 100, "requestId": "a"},
        {"assetId": 101, "requestId": "b"},
        {"assetId": 999, "requestId": "c"},
    ]
    assert json.loads(scraper_body) == [
        {"assetId": 100, "requestId": "a"},
        {"assetId": 101, "requestId": "b"},
        {"assetId": 102, "requestId": "c"},
    ]


def test_exact_id_replacement_takes_priority_over_type_removal():
    stripper = TextureStripper(_Config())
    body = json.dumps([
        {"assetId": 1234, "assetType": "TexturePack", "assetTypeId": 63, "requestId": "a"},
        {"assetId": 5678, "assetType": "TexturePack", "assetTypeId": 63, "requestId": "b"},
    ]).encode()

    modified, scraper_body = stripper.process_batch_request(
        body,
        {},
        ({1234: 999}, {63}, {}, {}),
        "batch",
    )

    assert json.loads(modified) == [
        {"assetId": 999, "assetType": "TexturePack", "assetTypeId": 63, "requestId": "a"},
    ]
    assert json.loads(scraper_body) == [
        {"assetId": 1234, "assetType": "TexturePack", "assetTypeId": 63, "requestId": "a"},
    ]


def test_cdn_replacement_takes_priority_over_type_removal(monkeypatch):
    stripper = TextureStripper(_Config())
    routed = []
    monkeypatch.setattr(stripper, '_route_cdn', lambda *args: routed.append(args))
    body = json.dumps([
        {"assetId": 1234, "assetType": "TexturePack", "assetTypeId": 63, "requestId": "a"},
    ]).encode()

    modified, _ = stripper.process_batch_request(
        body,
        {},
        ({}, {63}, {1234: "https://example.com/custom.png"}, {}),
        "batch",
    )

    assert json.loads(modified)[0]["assetId"] == 1234
    assert routed and routed[0][2] == "https://example.com/custom.png"


def test_local_replacement_takes_priority_over_type_removal(monkeypatch, tmp_path):
    stripper = TextureStripper(_Config())
    routed = []
    monkeypatch.setattr(stripper, '_route_local', lambda *args, **kwargs: routed.append((args, kwargs)))
    replacement = tmp_path / "custom.png"
    replacement.write_bytes(b"png")
    body = json.dumps([
        {"assetId": 1234, "assetType": "TexturePack", "assetTypeId": 63, "requestId": "a"},
    ]).encode()

    modified, _ = stripper.process_batch_request(
        body,
        {},
        ({}, {63}, {}, {1234: str(replacement)}),
        "batch",
    )

    assert json.loads(modified)[0]["assetId"] == 1234
    assert routed and routed[0][0][2] == str(replacement)


def test_whole_texturepack_id_replacement_swaps_parent_without_downloading_xml():
    class _Scraper:
        def _fetch_asset_with_place_id_retry(self, *args, **kwargs):
            raise AssertionError('whole TexturePack must not be downloaded as a slot image')

    stripper = TextureStripper(_Config())
    stripper.set_cache_scraper(_Scraper())
    body = json.dumps([
        _texpack_request(1234, 'color', 'color-fidelity'),
        _texpack_request(1234, 'normal', 'normal-fidelity'),
        _texpack_request(1234, 'orm', 'orm-fidelity'),
    ]).encode()

    modified, scraper_body = stripper.process_batch_request(
        body,
        {},
        ({'TexturePack': 9999}, set(), {}, {}),
        'batch',
    )

    assert [entry['assetId'] for entry in json.loads(modified)] == [9999, 9999, 9999]
    assert [entry['assetId'] for entry in json.loads(scraper_body)] == [1234, 1234, 1234]


def test_predownloaded_texturepack_xml_is_not_served_as_slot_content(tmp_path):
    stripper = TextureStripper(_Config())
    manifest = tmp_path / 'replacement.dat'
    manifest.write_bytes(
        b'<roblox><texturepack_version>2</texturepack_version>'
        b'<color>10</color><normal>11</normal></roblox>'
    )
    stripper._predownloaded = {9999: str(manifest)}
    body = json.dumps([
        _texpack_request(1234, 'color', 'color-fidelity'),
        _texpack_request(1234, 'normal', 'normal-fidelity'),
        _texpack_request(1234, 'orm', 'orm-fidelity'),
    ]).encode()

    modified, _ = stripper.process_batch_request(
        body,
        {},
        ({'TexturePack': 9999}, set(), {}, {}),
        'batch',
    )

    assert [entry['assetId'] for entry in json.loads(modified)] == [9999, 9999, 9999]
    assert not stripper._local_redirects


def test_exact_local_texturepack_rule_overrides_type_id_rule(monkeypatch, tmp_path):
    stripper = TextureStripper(_Config())
    routed = []
    monkeypatch.setattr(stripper, '_route_local', lambda *args, **kwargs: routed.append((args, kwargs)))
    fish = tmp_path / 'fish.png'
    fish.write_bytes(b'png')
    body = json.dumps([
        _texpack_request(14108663921, 'carpet-color', 'color-fidelity'),
        _texpack_request(2222, 'wall-color', 'color-fidelity'),
    ]).encode()

    modified, scraper_body = stripper.process_batch_request(
        body,
        {},
        ({'TexturePack': 7547162198}, set(), {}, {14108663921: str(fish)}),
        'batch',
    )

    entries = json.loads(modified)
    assert entries[0]['assetId'] == 14108663921
    assert entries[1]['assetId'] == 7547162198
    assert len(routed) == 1
    assert routed[0][0][1:3] == (14108663921, str(fish))
    assert [entry['assetId'] for entry in json.loads(scraper_body)] == [
        14108663921,
        2222,
    ]


def _texpack_request(asset_id, request_id, crpl):
    return {
        "assetId": asset_id,
        "contentRepresentationPriorityList": crpl,
        "doNotFallbackToBaselineRepresentation": "true",
        "assetType": "TexturePack",
        "requestId": str(request_id),
    }


def test_texturepack_fidelity_decodes_slot_and_quality():
    assert _decode_texpack_slot_quality(_texpack_request(1, 0, "W3siZm9ybWF0Ijoia3R4MiIsIm1ham9yVmVyc2lvbiI6IjdyZG8iLCJmaWRlbGl0eSI6IkFFQT0ifV0=")) == (0, 1)
    assert _decode_texpack_slot_quality(_texpack_request(1, 0, "W3siZm9ybWF0Ijoia3R4MiIsIm1ham9yVmVyc2lvbiI6IjdyZG8iLCJmaWRlbGl0eSI6IklFQT0ifV0=")) == (1, 1)
    assert _decode_texpack_slot_quality(_texpack_request(1, 0, "W3siZm9ybWF0Ijoia3R4MiIsIm1ham9yVmVyc2lvbiI6IjdyZG8iLCJmaWRlbGl0eSI6IlFFQT0ifV0=")) == (2, 1)


def test_texturepack_partial_batch_uses_fidelity_before_occurrence_order():
    stripper = TextureStripper(_Config())
    requests = [
        _texpack_request(
            88088208586015,
            7,
            "W3siZm9ybWF0Ijoia3R4MiIsIm1ham9yVmVyc2lvbiI6IjdyZG8iLCJmaWRlbGl0eSI6IlFJQT0ifSx7ImZvcm1hdCI6Imt0eDIiLCJtYWpvclZlcnNpb24iOiI2cmRvIiwiZmlkZWxpdHkiOiJnZ0E9In1d",
        ),
        _texpack_request(
            88088208586015,
            8,
            "W3siZm9ybWF0Ijoia3R4MiIsIm1ham9yVmVyc2lvbiI6IjdyZG8iLCJmaWRlbGl0eSI6IklJQT0ifSx7ImZvcm1hdCI6Imt0eDIiLCJtYWpvclZlcnNpb24iOiI2cmRvIiwiZmlkZWxpdHkiOiJnUUE9In1d",
        ),
    ]

    assert stripper._build_texpack_request_slot_map(requests, {88088208586015}) == {
        0: 2,
        1: 1,
    }


def test_cdn_redirect_match_does_not_log_short_circuit_noise(monkeypatch):
    messages = []

    class _LogBuffer:
        def log(self, category, message):
            messages.append((category, message))

    monkeypatch.setattr(texture_stripper_module, 'log_buffer', _LogBuffer())
    with TextureStripper._lock:
        TextureStripper._pending.clear()
        TextureStripper._cdn_redirects.clear()
        TextureStripper._local_redirects.clear()
        TextureStripper._solidmodel_injections.clear()
        TextureStripper._cdn_redirects['https://fts.rbxcdn.com/sc1/example'] = (
            'https://file.garden/example.obj'
        )

    stripper = TextureStripper(_Config())

    assert stripper.check_cdn_request('fts.rbxcdn.com', '/sc1/example?x=1') == (
        'cdn',
        'https://file.garden/example.obj',
    )
    assert not any('CDN short-circuit match' in message for _, message in messages)


def test_animation_replacement_rig_detection_strips_bin_metadata(tmp_path):
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"RBXH amazon metadata" + b"<roblox!binary animation")
    stripper = TextureStripper(_Config())

    with patch("Fleasion.utils.anim_converter.detect_rig", return_value="R15") as detect_rig:
        assert stripper._detect_repl_rig(str(replacement)) == "R15"

    detect_rig.assert_called_once_with(b"<roblox!binary animation")
