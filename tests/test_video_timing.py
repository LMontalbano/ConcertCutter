"""Vérifie les transitions sur les échantillons et les images réellement rendus."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

from concertcutter import video
from concertcutter.render import _Album, _album_durations, _timeline_audio


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

    def test_padded_spans_applies_track_trims(self) -> None:
        from concertcutter.render import _padded_spans, RenderParams
        from concertcutter.segment import Analysis, Segment, MUSIC, GAP

        analysis = Analysis(
            source="test.wav",
            samplerate=1000,
            channels=2,
            duration=100.0,
            segments=[
                Segment(start=10.0, end=40.0, kind=MUSIC, number=1),
                Segment(start=40.0, end=50.0, kind=GAP, number=0),
                Segment(start=50.0, end=90.0, kind=MUSIC, number=2),
            ],
        )
        params_no_trim = RenderParams(pad_start_s=0.0, pad_end_s=0.0)
        spans_no_trim = _padded_spans(analysis, params_no_trim, total_frames=100_000, samplerate=1000)
        self.assertEqual(spans_no_trim[0], (0, 1, 10_000, 40_000))
        self.assertEqual(spans_no_trim[1], (1, 2, 50_000, 90_000))

        params_trim = RenderParams(
            pad_start_s=0.0,
            pad_end_s=0.0,
            track_trims={1: (2.0, 5.0), 2: (1.0, 0.0)},
        )
        spans_trim = _padded_spans(analysis, params_trim, total_frames=100_000, samplerate=1000)
        self.assertEqual(spans_trim[0], (0, 1, 12_000, 35_000))
        self.assertEqual(spans_trim[1], (1, 2, 51_000, 90_000))

    def test_timeline_audio_keeps_gaps_and_source_trims(self) -> None:
        from concertcutter.segment import Analysis, Segment, MUSIC

        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source.wav"
            samples = np.arange(10_000, dtype=np.float32).reshape(-1, 1) / 10_000
            sf.write(source, samples, 1000, subtype="FLOAT")
            analysis = Analysis(
                source=str(source), samplerate=1000, channels=1, duration=10,
                segments=[Segment(start=0, end=10, kind=MUSIC, number=1)],
            )
            output = Path(root) / "montage.wav"
            _timeline_audio(analysis, ({
                "trackNumber": 1,
                "start": 2.0,
                "end": 5.0,
                "sourceStart": 4.0,
                "sourceEnd": 7.0,
            },), output)
            rendered, rate = sf.read(output, always_2d=True)
            self.assertEqual(rate, 1000)
            self.assertEqual(len(rendered), 5000)
            self.assertTrue(np.allclose(rendered[:2000], 0))
            self.assertAlmostEqual(rendered[2000, 0], samples[4000, 0], places=4)

    def test_overlapping_clips_crossfade_their_music(self) -> None:
        """Le recouvrement mêle les deux musiques : A s'éteint pendant que B monte."""
        from concertcutter.segment import Analysis, Segment, MUSIC

        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source.wav"
            samples = np.zeros((4000, 2), dtype=np.float32)
            samples[:2000, 0] = 1.0     # le morceau A, sur le canal 0
            samples[2000:, 1] = 1.0     # le morceau B, sur le canal 1
            sf.write(source, samples, 1000, subtype="FLOAT")
            analysis = Analysis(
                source=str(source), samplerate=1000, channels=2, duration=4,
                segments=[Segment(start=0, end=4, kind=MUSIC, number=1)],
            )
            output = Path(root) / "montage.wav"
            _timeline_audio(analysis, (
                {"trackNumber": 1, "start": 0.0, "end": 2.0,
                 "sourceStart": 0.0, "sourceEnd": 2.0},
                {"trackNumber": 1, "start": 1.5, "end": 3.5,
                 "sourceStart": 2.0, "sourceEnd": 4.0},
            ), output)
            rendered, _ = sf.read(output, always_2d=True)
            self.assertEqual(len(rendered), 3500)
            np.testing.assert_allclose(rendered[1000], [1.0, 0.0], atol=0.01)
            np.testing.assert_allclose(rendered[1500], [1.0, 0.0], atol=0.01)
            np.testing.assert_allclose(rendered[1750], [0.707, 0.707], atol=0.01)
            np.testing.assert_allclose(rendered[1999], [0.0, 1.0], atol=0.01)
            np.testing.assert_allclose(rendered[2500], [0.0, 1.0], atol=0.01)

    def test_titles_hand_over_in_the_middle_of_a_crossfade(self) -> None:
        from concertcutter.render import _caption_spans

        spans = [span for _clip, span in _caption_spans((
            {"start": 0.0, "end": 10.0}, {"start": 8.0, "end": 20.0},
            {"start": 25.0, "end": 30.0}))]
        self.assertEqual(spans, [(0.0, 9.0), (9.0, 20.0), (25.0, 30.0)])

    def test_three_clips_never_overlap_at_once(self) -> None:
        from concertcutter.segment import Analysis, Segment, MUSIC

        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source.wav"
            sf.write(source, np.ones((4000, 1), dtype=np.float32), 1000, subtype="FLOAT")
            analysis = Analysis(
                source=str(source), samplerate=1000, channels=1, duration=4,
                segments=[Segment(start=0, end=4, kind=MUSIC, number=1)],
            )
            clip = lambda start, end: {"trackNumber": 1, "start": start, "end": end,
                                       "sourceStart": 0.0, "sourceEnd": end - start}
            for clips in ((clip(0, 2), clip(1, 3), clip(1.5, 3.5)),   # trois à la fois
                          (clip(0, 3), clip(1, 2))):                  # l'un dans l'autre
                with self.subTest(clips=clips), self.assertRaises(ValueError):
                    _timeline_audio(analysis, clips, Path(root) / "m.wav")

    def test_free_clip_edges_get_the_anti_click_fade(self) -> None:
        from concertcutter.segment import Analysis, Segment, MUSIC

        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source.wav"
            sf.write(source, np.ones((4000, 1), dtype=np.float32), 1000,
                     subtype="FLOAT")
            analysis = Analysis(
                source=str(source), samplerate=1000, channels=1, duration=4,
                segments=[Segment(start=0, end=4, kind=MUSIC, number=1)],
            )
            output = Path(root) / "montage.wav"
            _timeline_audio(analysis, ({
                "trackNumber": 1, "start": 1.0, "end": 3.0,
                "sourceStart": 1.0, "sourceEnd": 3.0,
            },), output, edge_ms=100.0)
            rendered, _ = sf.read(output, always_2d=True)
            self.assertEqual(len(rendered), 3000)
            self.assertLess(rendered[1000, 0], 0.01)
            self.assertAlmostEqual(rendered[1050, 0], 0.5, delta=0.02)
            self.assertAlmostEqual(rendered[2000, 0], 1.0, places=4)
            self.assertLess(rendered[2999, 0], 0.01)


@unittest.skipUnless(video.find_ffmpeg(), "ffmpeg absent")
class ImageTimingTests(unittest.TestCase):
    def test_slideshow_honours_a_fade_longer_than_its_hold(self) -> None:
        levels = self.render_slideshow_frames(hold=2, fade=3)
        # Deux secondes pleinement blanc, trois secondes de fondu vers noir,
        # deux secondes noires, puis trois secondes pour revenir au blanc.
        for time, expected in ((1.5, 1), (2.75, .75), (3.5, .5), (4.25, .25),
                               (6, 0), (7.75, .25), (8.5, .5), (9.25, .75)):
            with self.subTest(time=time):
                self.assertAlmostEqual(levels[round(time * 10)], expected, delta=.08)
        self.assertAlmostEqual(len(levels) / 10, 10, delta=.1)

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

    def test_timeline_video_with_clips_and_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stills = self.stills(Path(root))
            audio_path = Path(root) / "test.wav"
            sf.write(str(audio_path), np.zeros((10 * 8000, 2), dtype=np.float32), 8000)
            clips = (
                {"image": stills[0], "start": 0.0, "end": 4.0},
                {"image": stills[0], "start": 7.0, "end": 10.0},
            )
            params = video.VideoParams(
                image=stills[0], clips=clips, slide_fade_s=0.0,
                width=32, height=18, fps=10,
            )
            out_path = video._timeline_video(audio_path, params)
            levels = self.levels(out_path)
            self.assertAlmostEqual(len(levels) / 10, 10, delta=0.2)
            self.assertAlmostEqual(levels[20], 1.0, delta=0.05)
            self.assertAlmostEqual(levels[50], 0.0, delta=0.05)
            self.assertAlmostEqual(levels[80], 1.0, delta=0.05)

    def test_timeline_video_fades_between_joined_images(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stills = self.stills(Path(root))
            audio_path = Path(root) / "test.wav"
            sf.write(str(audio_path), np.zeros((8 * 8000, 2), dtype=np.float32), 8000)
            params = video.VideoParams(
                image=stills[0],
                clips=(
                    {"image": stills[0], "start": 0.0, "end": 4.0},
                    {"image": stills[1], "start": 4.0, "end": 8.0},
                ),
                slide_fade_s=2.0, width=32, height=18, fps=10,
            )
            levels = self.levels(video._timeline_video(audio_path, params))
            for moment, expected in ((3.5, 1.0), (4.5, .75), (5.0, .5),
                                     (5.5, .25), (6.5, 0.0)):
                self.assertAlmostEqual(levels[round(moment * 10)], expected,
                                       delta=.08)

    def test_timeline_fade_turns_portrait_bars_gradually_black(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            outgoing = folder / "landscape.ppm"
            incoming = folder / "portrait.ppm"
            outgoing.write_bytes(
                b"P6\n32 18\n255\n" + bytes([255, 0, 0]) * 32 * 18)
            incoming.write_bytes(
                b"P6\n8 18\n255\n" + bytes([255, 255, 255]) * 8 * 18)
            audio_path = folder / "test.wav"
            sf.write(str(audio_path), np.zeros((8 * 8000, 2), dtype=np.float32), 8000)
            params = video.VideoParams(
                image=str(outgoing),
                clips=(
                    {"image": str(outgoing), "start": 0.0, "end": 4.0},
                    {"image": str(incoming), "start": 4.0, "end": 8.0},
                ),
                slide_fade_s=2.0, width=32, height=18, fps=10,
            )
            rendered = video._timeline_video(audio_path, params)

            def frame_at(moment: float) -> np.ndarray:
                frame = subprocess.run([
                    video.find_ffmpeg(), "-v", "error", "-ss", str(moment),
                    "-i", str(rendered), "-frames:v", "1", "-f", "rawvideo",
                    "-pix_fmt", "rgb24", "-",
                ], capture_output=True, check=True).stdout
                return np.frombuffer(frame, dtype=np.uint8).reshape(18, 32, 3)

            early = frame_at(4.25)
            late = frame_at(5.75)
            # Les côtés ne sautent pas au noir au début : ils suivent le même
            # fondu que le contenu, puis sont presque noirs à son terme.
            self.assertGreater(float(early[:, 0, 0].mean()), 160)
            self.assertLess(float(late[:, 0, 0].mean()), 64)
            self.assertGreater(float(late[:, 16].mean()), 32)

    def test_a_long_timeline_is_encoded_in_invisible_slices(self) -> None:
        """Beaucoup de plans : même image à l'arrivée, par tranches raboutées."""
        with tempfile.TemporaryDirectory() as root:
            stills = self.stills(Path(root))
            audio_path = Path(root) / "test.wav"
            sf.write(str(audio_path), np.zeros((20 * 8000, 2), dtype=np.float32), 8000)
            params = video.VideoParams(
                image=stills[0],
                clips=tuple({"image": stills[index % 2], "start": index * 2.0,
                             "end": index * 2.0 + 2.0} for index in range(10)),
                slide_fade_s=1.0, width=32, height=18, fps=10,
            )
            whole = self.levels(video._timeline_video(audio_path, params))
            calls = []
            original = video._run
            with mock.patch.object(video, "SEQUENCE_BATCH", 3), \
                    mock.patch.object(video, "_run",
                                      side_effect=lambda *a, **k: (calls.append(a[0]),
                                                                   original(*a, **k))[1]):
                sliced = self.levels(video._timeline_video(audio_path, params))
            # Trois tranches de quatre entrées au plus, puis le raboutage.
            self.assertEqual(len(calls), 4)
            self.assertTrue(all(call.count("-i") <= 4 for call in calls[:-1]))
            self.assertEqual(len(sliced), len(whole))
            self.assertLess(float(np.abs(sliced - whole).max()), 0.05)

    def test_each_timeline_background_gets_its_own_file(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stills = self.stills(Path(root))
            audio_path = Path(root) / "test.wav"
            sf.write(str(audio_path), np.zeros((2 * 8000, 2), dtype=np.float32), 8000)
            params = video.VideoParams(
                image=stills[0], clips=({"image": stills[0], "start": 0.0, "end": 2.0},),
                width=32, height=18, fps=10)
            first = video._timeline_video(audio_path, params)
            second = video._timeline_video(audio_path, params)
            self.assertNotEqual(first, second)
            self.assertTrue(first.exists() and second.exists())

    def render_frames(self, durations: list[float], fade: float) -> np.ndarray:
        with tempfile.TemporaryDirectory() as root:
            stills = self.stills(Path(root))
            captions = video.captions_from_durations([""] * len(durations), durations)
            params = video.VideoParams(image=stills[0], images=tuple(stills),
                                       per_caption=True, slide_fade_s=fade,
                                       width=32, height=18, fps=10)
            path = video._chapters(captions, params)
            return self.levels(path)

    def render_slideshow_frames(self, hold: float, fade: float) -> np.ndarray:
        with tempfile.TemporaryDirectory() as root:
            stills = self.stills(Path(root))
            params = video.VideoParams(image=stills[0], images=tuple(stills),
                                       slide_s=hold, slide_fade_s=fade,
                                       width=32, height=18, fps=10)
            return self.levels(video._slideshow(params))

    @staticmethod
    def stills(root: Path) -> list[str]:
        stills = []
        for name, colour in (("white", 255), ("black", 0)):
            path = root / f"{name}.ppm"
            path.write_bytes(b"P6\n32 18\n255\n" + bytes([colour]) * 32 * 18 * 3)
            stills.append(str(path))
        return stills

    @staticmethod
    def levels(path: Path) -> np.ndarray:
        result = subprocess.run([
            video.find_ffmpeg(), "-v", "error", "-i", str(path),
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ], capture_output=True, check=True)
        frames = np.frombuffer(result.stdout, np.uint8).reshape(-1, 18, 32, 3)
        return frames.mean(axis=(1, 2, 3)) / 255


if __name__ == "__main__":
    unittest.main()
