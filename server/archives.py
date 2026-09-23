"""Bounded, random-access readers for RTX IO packages and Valve VPK archives."""

import struct
from pathlib import Path, PurePosixPath


def safe_name(value):
    name = value.replace("\\", "/")
    parts = PurePosixPath(name).parts
    if not parts or name.startswith("/") or any(p in ("..", ".") or ":" in p for p in parts):
        raise ValueError("Unsafe archive member")
    return name


def read_exact(stream, size):
    value = stream.read(size)
    if len(value) != size:
        raise ValueError("Truncated archive")
    return value


class Package:
    """RTX IO v1 directory reader and selective package writer."""

    def __init__(self, path):
        self.path = Path(path)
        size = self.path.stat().st_size
        with self.path.open("rb") as stream:
            magic, version, offset = struct.unpack("<IIQ", read_exact(stream, 16))
            if magic != 0xBAADD00D or version != 1 or not 16 <= offset < size:
                raise ValueError("Unsupported RTX IO package header")
            stream.seek(offset)
            count, blob_count = struct.unpack("<HH", read_exact(stream, 4))
            self.descriptors = [struct.unpack("<HBBHHHHHHHH", read_exact(stream, 20)) for _ in range(count)]
            self.blobs = [struct.unpack("<QII", read_exact(stream, 16)) for _ in range(blob_count)]
            names_size = size - stream.tell()
            if names_size > 32 * 1024 * 1024:
                raise ValueError("Archive name table exceeds limit")
            names = read_exact(stream, names_size).split(b"\0")
            if len(names) < count:
                raise ValueError("Missing archive names")
            self.names = [safe_name(v.decode("utf-8")) for v in names[:count]]
        for value, length, _ in self.blobs:
            start = value & ((1 << 40) - 1)
            if start < 16 or start + length > offset:
                raise ValueError("Invalid archive blob extent")

    def metadata(self, index):
        d = self.descriptors[index]
        return dict(width=d[3], height=d[4], format=d[2], mips=d[6], array_size=d[8])

    def select(self, index, destination, preview=False):
        d = list(self.descriptors[index])
        if d[1] != 2 or d[8] != 1 or d[5] > 1:
            raise ValueError("Only ordinary 2D textures are supported for PNG export")
        loose = d[6] - d[7]
        if preview and loose:
            mip = 0
            while max(d[3] >> mip, d[4] >> mip) > 1024 and mip < loose - 1:
                mip += 1
            indices = [d[9] + mip]
            d[3], d[4] = max(1, d[3] >> mip), max(1, d[4] >> mip)
            d[6], d[7], d[9], d[10] = 1, 0, 0, 0
        else:
            indices = list(range(d[9], d[9] + loose))
            if d[7]:
                indices.append(d[10])
            d[9], d[10] = 0, loose
        d[0] = 0
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptors = []
        with self.path.open("rb") as source, destination.open("wb") as output:
            output.write(bytes(16))
            for blob_index in indices:
                flags, size, crc = self.blobs[blob_index]
                source.seek(flags & ((1 << 40) - 1))
                offset = output.tell()
                remaining = size
                while remaining:
                    chunk = read_exact(source, min(remaining, 1024 * 1024))
                    output.write(chunk)
                    remaining -= len(chunk)
                descriptors.append(((flags & ~((1 << 40) - 1)) | offset, size, crc))
            dictionary = output.tell()
            output.write(struct.pack("<HH", 1, len(descriptors)))
            output.write(struct.pack("<HBBHHHHHHHH", *d))
            for blob in descriptors:
                output.write(struct.pack("<QII", *blob))
            output.write(b"selected.dds\0")
            output.seek(0)
            output.write(struct.pack("<IIQ", 0xBAADD00D, 1, dictionary))
        return self.metadata(index)


def vpk_entries(path):
    """Yield VPK v1/v2 directory entries without reading payload archives."""
    path = Path(path)
    with path.open("rb") as stream:
        signature, version, size = struct.unpack("<III", read_exact(stream, 12))
        if signature != 0x55AA1234 or version not in (1, 2) or size > 128 * 1024 * 1024:
            raise ValueError("Invalid VPK header")
        if version == 2:
            read_exact(stream, 16)
        tree_start = stream.tell()
        tree_end = tree_start + size

        def string():
            value = bytearray()
            while stream.tell() < tree_end and len(value) < 32768:
                char = read_exact(stream, 1)
                if char == b"\0":
                    return value.decode("utf-8")
                value.extend(char)
            raise ValueError("Invalid VPK string")

        while ext := string():
            while directory := string():
                while name := string():
                    crc, preload, archive, offset, length, terminator = struct.unpack("<IHHIIH", read_exact(stream, 18))
                    if terminator != 65535:
                        raise ValueError("Invalid VPK entry")
                    prefix_offset = stream.tell()
                    read_exact(stream, preload)
                    member = safe_name(("" if directory == " " else directory + "/") + name + ("" if ext == " " else "." + ext))
                    payload = path if archive == 0x7FFF else path.with_name(path.name.replace("_dir.vpk", f"_{archive:03d}.vpk"))
                    yield dict(member=member, archive=str(payload), offset=offset + (tree_end if archive == 0x7FFF else 0), length=length, preload=preload, preload_offset=prefix_offset, directory=str(path), crc=crc)


def extract_vpk(entry, destination):
    destination = Path(destination)
    with destination.open("wb") as output:
        with Path(entry["directory"]).open("rb") as source:
            source.seek(entry["preload_offset"])
            output.write(read_exact(source, entry["preload"]))
        with Path(entry["archive"]).open("rb") as source:
            source.seek(entry["offset"])
            remaining = entry["length"]
            while remaining:
                data = read_exact(source, min(remaining, 1024 * 1024))
                output.write(data)
                remaining -= len(data)
