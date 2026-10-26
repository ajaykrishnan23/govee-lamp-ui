import shutil
import subprocess

import pytest

from lamp.voice import Transcriber


@pytest.mark.slow
def test_transcriber_decodes_m4a(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg missing")
    clip = tmp_path / "tone.m4a"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "aac", str(clip)], check=True)
    assert isinstance(Transcriber("tiny.en").transcribe(clip), str)
