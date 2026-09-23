"""Archive boundary, selective extraction, and Source preload regression tests."""

import struct

import pytest

from server.archives import Package, extract_vpk, safe_name, vpk_entries


def package_fixture(path):
    with path.open("wb") as stream:
        stream.write(bytes(16))
        blobs = []
        for value in (b"A" * 8, b"B" * 8, b"C" * 8, b"D" * 8):
            blobs.append((stream.tell(), len(value), 0))
            stream.write(value)
        dictionary = stream.tell()
        stream.write(struct.pack("<HH", 1, len(blobs)))
        stream.write(struct.pack("<HBBHHHHHHHH", 0, 2, 139, 4096, 4096, 1, 4, 1, 1, 0, 3))
        for blob in blobs:
            stream.write(struct.pack("<QII", *blob))
        stream.write(b"textures/test.dds\0")
        stream.seek(0)
        stream.write(struct.pack("<IIQ", 0xBAADD00D, 1, dictionary))


def test_preview_copies_only_selected_mip(tmp_path):
    source = tmp_path / "source.pkg"
    package_fixture(source)
    package = Package(source)
    preview = tmp_path / "preview.pkg"
    package.select(0, preview, True)
    result = Package(preview)
    assert result.metadata(0)["width"] == 1024
    assert result.metadata(0)["mips"] == 1
    assert len(result.blobs) == 1
    assert preview.read_bytes()[16:24] == b"C" * 8
    assert source.read_bytes()[16:24] == b"A" * 8


def test_full_export_preserves_mips_and_tail(tmp_path):
    source = tmp_path / "source.pkg"
    package_fixture(source)
    output = tmp_path / "full.pkg"
    Package(source).select(0, output)
    result = Package(output)
    assert result.metadata(0)["width"] == 4096
    assert len(result.blobs) == 4
    assert output.read_bytes()[16:48] == b"A" * 8 + b"B" * 8 + b"C" * 8 + b"D" * 8


@pytest.mark.parametrize("name", ["../escape", "x/../../escape", "C:/file", "/absolute", "\\server\\file"])
def test_archive_traversal_rejected(name):
    with pytest.raises(ValueError):
        safe_name(name)


def test_truncated_package_rejected(tmp_path):
    source = tmp_path / "broken.pkg"
    source.write_bytes(struct.pack("<IIQ", 0xBAADD00D, 1, 16) + b"x")
    with pytest.raises(ValueError):
        Package(source)


def test_vpk_preload_and_split_payload(tmp_path):
    path = tmp_path / "sounds_dir.vpk"
    tree = b"wav\0sound/test\0click\0" + struct.pack("<IHHIIH", 0, 3, 0, 2, 4, 65535) + b"PRE" + b"\0\0\0"
    path.write_bytes(struct.pack("<III", 0x55AA1234, 1, len(tree)) + tree)
    (tmp_path / "sounds_000.vpk").write_bytes(b"xxDATAignored")
    entry = list(vpk_entries(path))[0]
    assert entry["member"] == "sound/test/click.wav"
    output = tmp_path / "click.wav"
    extract_vpk(entry, output)
    assert output.read_bytes() == b"PREDATA"


def test_vpk_embedded_payload(tmp_path):
    path = tmp_path / "single_dir.vpk"
    tree = b"mp3\0sound\0music\0" + struct.pack("<IHHIIH", 0, 0, 0x7FFF, 0, 5, 65535) + b"\0\0\0"
    path.write_bytes(struct.pack("<III", 0x55AA1234, 2, len(tree)) + bytes(16) + tree + b"AUDIO")
    output = tmp_path / "music.mp3"
    extract_vpk(list(vpk_entries(path))[0], output)
    assert output.read_bytes() == b"AUDIO"
