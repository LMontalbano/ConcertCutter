"""Vérifie les transitions sur les échantillons et les images réellement rendus."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from concertcutter import video
from concertcutter.render import _Album, _album_durations


class AlbumTimingTests(unittest.TestCase):
    def test_chapters_match_audio_including_short_tracks(self) -> None:
        for lengths in ([6, 6, 6], [2, 6, 6], [6, 1, 6], [6, 3, 6]):
            with self.subTest(lengths=lengths), tempfile.TemporaryDirectory() as root:
                path = Path(root) / "album.wav"
                sf.write(path, np.zeros((1, 2)), 8000)
                album = _Album(path, sf.info(path), 2.0)
                for index, length in enumerate(lengths):
                    samples = np.zeros((length * 8000, 2), dtype=np.float32)
                    samples[:, index % 2] = 0.5
                    album.add(samples)
                album.close()
                audio, rate = sf.read(path, always_2d=True)
                durations = _album_durations([{"duration": n} for n in lengths], 2)
                self.assertAlmostEqual(sum(durations), len(audio) / rate)
                # La deuxième piste apparaît au départ du deuxième chapitre.
                audible = np.flatnonzero(audio[:, 1] > 0.0001)[0] / rate
                self.assertAlmostEqual(audible, durations[0], delta=0.002)


@unittest.skipUnless(video.find_ffmpeg(), "ffmpeg absent")
class ImageTimingTests(unittest.TestCase):
    def test_two_second_fades_start_with_audio_at_every_chapter(self) -> None:
        durations = _album_durations([{"duration": 6}] * 3, 2)
        levels = self.render_frames(durations, fade=2)
        # Blanc -> noir à 4 s, puis noir -> blanc à 8 s, sur deux secondes.
        for time, expected in ((3.5, 1), (4.5, .75), (5, .5), (5.5, .25),
                               (6.5, 0), (8.5, .25), (9, .5), (9.5, .75), (13, 1)):
            with self.subTest(time=time):
                self.assertAlmostEqual(levels[round(time * 10)], expected, delta=.08)
        self.assertAlmostEqual(len(levels) / 10, sum(durations), delta=.1)

    def test_a_short_chapter_only_limits_its_own_fade(self) -> None:
        levels = self.render_frames([4, 1, 5], fade=2)
        self.assertAlmostEqual(levels[45], .5, delta=.08)
        self.assertAlmostEqual(levels[55], .25, delta=.08)
        self.assertAlmostEqual(levels[60], .5, delta=.08)
        self.assertAlmostEqual(len(levels) / 10, 10, delta=.1)

    def test_zero_fade_keeps_a_hard_cut(self) -> None:
        levels = self.render_frames([4, 4, 4], fade=0)
        for frame, expected in ((39, 1), (40, 0), (79, 0), (80, 1), (119, 1)):
            self.assertAlmostEqual(levels[frame], expected, delta=.03)

    def render_frames(self, durations: list[float], fade: float) -> np.ndarray:
        with tempfile.TemporaryDirectory() as root:
            stills = []
            for name, colour in (("white", 255), ("black", 0)):
                path = Path(root) / f"{name}.ppm"
                path.write_bytes(b"P6\n32 18\n255\n" + bytes([colour]) * 32 * 18 * 3)
                stills.append(str(path))
            captions = video.captions_from_durations([""] * len(durations), durations)
            params = video.VideoParams(image=stills[0], images=tuple(stills),
                                       per_caption=True, slide_fade_s=fade,
                                       width=32, height=18, fps=10)
            path = video._chapters(captions, params)
            result = subprocess.run([
                video.find_ffmpeg(), "-v", "error", "-i", str(path),
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
            ], capture_output=True, check=True)
            frames = np.frombuffer(result.stdout, np.uint8).reshape(-1, 18, 32, 3)
            return frames.mean(axis=(1, 2, 3)) / 255


if __name__ == "__main__":
    unittest.main()
