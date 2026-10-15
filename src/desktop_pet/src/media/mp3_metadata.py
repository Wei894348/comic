"""Fast MP3 duration parsing without decoding the audio stream."""

from __future__ import annotations

from pathlib import Path


_MPEG1_LAYER3_BITRATES = (
    0,
    32,
    40,
    48,
    56,
    64,
    80,
    96,
    112,
    128,
    160,
    192,
    224,
    256,
    320,
)
_MPEG2_LAYER3_BITRATES = (
    0,
    8,
    16,
    24,
    32,
    40,
    48,
    56,
    64,
    80,
    96,
    112,
    128,
    144,
    160,
)
_SAMPLE_RATES = {
    3: (44100, 48000, 32000),
    2: (22050, 24000, 16000),
    0: (11025, 12000, 8000),
}


def _syncsafe_integer(value: bytes) -> int:
    if len(value) != 4:
        return 0
    return (
        (value[0] << 21)
        | (value[1] << 14)
        | (value[2] << 7)
        | value[3]
    )


def _first_frame_offset(data: bytes) -> int | None:
    start = 0
    if data.startswith(b"ID3") and len(data) >= 10:
        start = 10 + _syncsafe_integer(data[6:10])
        if data[5] & 0x10:
            start += 10

    for offset in range(start, len(data) - 4):
        header = int.from_bytes(data[offset : offset + 4], "big")
        if header & 0xFFE00000 != 0xFFE00000:
            continue
        version_id = (header >> 19) & 0x3
        layer_id = (header >> 17) & 0x3
        bitrate_index = (header >> 12) & 0xF
        sample_rate_index = (header >> 10) & 0x3
        if (
            version_id == 1
            or layer_id != 1
            or bitrate_index in (0, 15)
            or sample_rate_index == 3
        ):
            continue
        return offset
    return None


def read_mp3_duration(path: str | Path) -> float:
    file_path = Path(path)
    file_size = file_path.stat().st_size
    with file_path.open("rb") as file:
        header = file.read(10)
        id3_size = (
            10 + _syncsafe_integer(header[6:10])
            if header.startswith(b"ID3") and len(header) == 10
            else 0
        )
        file.seek(0)
        scan_size = max(512 * 1024, id3_size + 64 * 1024)
        data = file.read(min(file_size, scan_size))

    frame_offset = _first_frame_offset(data)
    if frame_offset is None:
        return 0.0

    header = int.from_bytes(data[frame_offset : frame_offset + 4], "big")
    version_id = (header >> 19) & 0x3
    bitrate_index = (header >> 12) & 0xF
    sample_rate_index = (header >> 10) & 0x3
    channel_mode = (header >> 6) & 0x3
    sample_rate = _SAMPLE_RATES[version_id][sample_rate_index]
    samples_per_frame = 1152 if version_id == 3 else 576

    side_info_size = 17 if version_id == 3 and channel_mode == 3 else 32
    if version_id != 3:
        side_info_size = 9 if channel_mode == 3 else 17
    xing_offset = frame_offset + 4 + side_info_size
    marker = data[xing_offset : xing_offset + 4]
    if marker in (b"Xing", b"Info") and len(data) >= xing_offset + 12:
        flags = int.from_bytes(data[xing_offset + 4 : xing_offset + 8], "big")
        if flags & 0x1:
            frame_count = int.from_bytes(
                data[xing_offset + 8 : xing_offset + 12], "big"
            )
            if frame_count > 0:
                return frame_count * samples_per_frame / sample_rate

    vbri_offset = frame_offset + 36
    if data[vbri_offset : vbri_offset + 4] == b"VBRI" and len(data) >= vbri_offset + 18:
        frame_count = int.from_bytes(
            data[vbri_offset + 14 : vbri_offset + 18], "big"
        )
        if frame_count > 0:
            return frame_count * samples_per_frame / sample_rate

    bitrates = (
        _MPEG1_LAYER3_BITRATES
        if version_id == 3
        else _MPEG2_LAYER3_BITRATES
    )
    bitrate = bitrates[bitrate_index]
    if bitrate <= 0:
        return 0.0
    return max(0.0, (file_size - frame_offset) * 8 / (bitrate * 1000))
