#!/usr/bin/env python3
# inspect.py
# requires ffprobe and mkvmerge
import json
import os
import pprint
from argparse import ArgumentParser
from datetime import timedelta
from pathlib import Path
from subprocess import DEVNULL, PIPE, run, CalledProcessError
from sys import exit
import pickle


def main():
    parser = ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--debug", action="store_true")

    args = parser.parse_args()

    inspector = Inspector()
    inspector.debug = args.debug
    inspector.inspect(args.file)


class Inspector:
    def __init__(self):
        self.debug = False

    def inspect(self, file):
        if not os.path.exists(file):
            exit(f"No such file: {file}")

        if os.path.isdir(file):
            exit("Folder inputs are not supported")
        
        self.__verify_tools()

        if file.endswith("bdmv"):
            return self.__bluray_inspect(file)
        elif file.endswith("mpls"):
            return self.__mpls_inspect(file)
        else:
            return self.__single_file_inspect(file)

    def __single_file_inspect(self, file):
        format_info, stream_info, frame_info = self.__ffprobe(file)
        if self.debug:
            print(f"Format info: \n{pprint.pformat(format_info)}\n\n")
            print(f"Stream info: \n{pprint.pformat(stream_info)}\n\n")
            print(f"Frame info: \n{pprint.pformat(frame_info)}")
        inspection_result = InspectionResult()
        audio_index = 0
        subtitle_index = 0
        for stream in stream_info:
            if stream["codec_type"] == "video":
                inspection_result.video.append(Video.from_single_file(stream, format_info, frame_info))
            elif stream["codec_type"] == "audio":
                audio_index += 1
                inspection_result.audio.append(Audio.from_single_file(stream, audio_index))
            elif stream["codec_type"] == "subtitle":
                subtitle_index += 1
                inspection_result.subtitles.append(Subtitle.from_single_file(stream, subtitle_index))

        print(inspection_result)

    def __bluray_inspect(self, file):
        cache_file, ffprobe_cache = self.__get_ffprobe_cache(file)

        playlist_info = dict()
        playlist_folder = Path(file).parent / "PLAYLIST"
        for playlist in playlist_folder.glob("*.mpls"):
            inspection_result = self.__inspect_mpls(ffprobe_cache, playlist)
            playlist_info[playlist] = inspection_result

        with open(cache_file, "wb") as f:
            pickle.dump(ffprobe_cache, f)

        for key in sorted(playlist_info, key=lambda k: playlist_info[k].video[0].duration):
            print(key)
            print(playlist_info[key])

    def __mpls_inspect(self, file):
        cache_file, ffprobe_cache = self.__get_ffprobe_cache(file)
        inspection_result = self.__inspect_mpls(ffprobe_cache, file)
        with open(cache_file, "wb") as f:
            pickle.dump(ffprobe_cache, f)

        print(inspection_result)

    def __get_ffprobe_cache(self, file):
        if file.endswith("bdmv"):
            cache_file = Path(file).parent.parent / "ffprobe_cache"
        elif file.endswith("mpls"):
            cache_file = Path(file).parent.parent.parent / "ffprobe_cache"
        else:
            exit("Unexpected file for ffprobe_cache")

        if cache_file.exists():
            with open(cache_file, "rb") as f:
                try:
                    ffprobe_cache = pickle.load(f)
                except:
                    ffprobe_cache = dict()
        else:
            ffprobe_cache = dict()
        return cache_file, ffprobe_cache

    def __inspect_mpls(self, ffprobe_cache, playlist):
        command = ["mkvmerge", "-J", str(playlist)]
        mkvmerge_info = json.loads(run(command, stdout=PIPE).stdout)
        all_audio_mkvmerge_info = list()
        all_subtitle_mkvmerge_info = list()
        all_stream_info = list()
        all_format_info = list()
        all_frame_info = list()
        for track in mkvmerge_info["tracks"]:
            if track["type"] == "audio":
                all_audio_mkvmerge_info.append(track)
            elif track["type"] == "subtitles":
                all_subtitle_mkvmerge_info.append(track)

        for segment in set(mkvmerge_info["container"]["properties"]["playlist_file"]):
            if segment in ffprobe_cache:
                format_info, stream_info, frame_info = ffprobe_cache[segment]
            else:
                format_info, stream_info, frame_info = self.__ffprobe(segment)
                subtitle_stats = self.__read_track_statistics(segment)
                stream_info[:] = [stream for stream in stream_info if stream["codec_type"] != "subtitle"]
                stream_info.extend(subtitle_stats)
                ffprobe_cache[segment] = (format_info, stream_info, frame_info)

            all_format_info.append(format_info)
            all_stream_info.append(stream_info)
            all_frame_info.append(frame_info)

        # all_stream_info is a 2d matrix
        # [ [seg1_vid1, seg1_aud1, seg1_aud2, seg1_sub1], [seg2_vid1, seg2_aud1, seg2_aud2, seg2_sub1] ]
        # We need to rotate it counter-clockwise, so it looks like this:
        # [ [seg1_vid1, seg2_vid1], [seg1_aud1, seg2_aud1], [seg1_aud2, seg2_aud2], [seg1_sub1, seg2_sub1] ]
        all_stream_info[:] = list(zip(*all_stream_info))[::-1]
        # sort by stream index, so everything's in the right order
        all_stream_info.sort(key=lambda x: x[0]["index"])
        inspection_result = InspectionResult()
        audio_index = 0
        subtitle_index = 0
        for stream in all_stream_info:
            if stream[0]["codec_type"] == "video":
                inspection_result.video.append(Video.from_bluray(stream, all_format_info, all_frame_info))
            elif stream[0]["codec_type"] == "audio":
                audio_index += 1
                inspection_result.audio.append(
                    Audio.from_bluray(stream, all_audio_mkvmerge_info[audio_index - 1], audio_index))
            elif stream[0]["codec_type"] == "subtitle":
                subtitle_index += 1
                inspection_result.subtitles.append(
                    Subtitle.from_bluray(stream, all_subtitle_mkvmerge_info[subtitle_index - 1], subtitle_index))

        return inspection_result

    @staticmethod
    def __verify_tools():
        commands = [["ffprobe", "-version"], ["mkvmerge", "--version"]]
        for command in commands:
            try:
                run(command, stdout=DEVNULL, stderr=DEVNULL).check_returncode()
            except FileNotFoundError or CalledProcessError:
                exit(f"Unable to run {command[0]}")

    @staticmethod
    def __ffprobe(input_file):
        command = [
            "ffprobe",
            "-loglevel", "quiet",
            "-show_streams",
            "-print_format", "json",
            input_file
        ]

        stream_info = json.loads(run(command, stdout=PIPE, stderr=DEVNULL).stdout)

        command = [
            "ffprobe",
            "-loglevel", "quiet",
            "-show_format",
            "-print_format", "json",
            input_file
        ]

        format_info = json.loads(run(command, stdout=PIPE, stderr=DEVNULL).stdout)

        command = [
            "ffprobe",
            "-loglevel", "quiet",
            "-select_streams", "v:0",
            "-show_frames",
            "-read_intervals", "%+#1",
            "-print_format", "json",
            input_file
        ]

        frame_info = json.loads(run(command, stdout=PIPE, stderr=DEVNULL).stdout)

        return format_info["format"], stream_info["streams"], frame_info["frames"][0]

    @staticmethod
    def __read_track_statistics(input_file) -> list:
        command = [
            "ffprobe",
            "-loglevel", "quiet",
            "-select_streams", "s",
            "-count_frames",
            "-show_streams",
            "-print_format", "json",
            input_file]

        ffprobe_result = json.loads(run(command, stdout=PIPE, stderr=DEVNULL).stdout)

        return ffprobe_result["streams"]


class InspectionResult:
    def __init__(self):
        self.video = []
        self.audio = []
        self.subtitles = []

    def __str__(self):
        string = "Video:\n"
        for video in self.video:
            string += "  " + str(video) + "\n"
        string += "Audio Streams:\n"
        for audio in self.audio:
            string += "  " + str(audio) + "\n"

        string += "Subtitle Streams:\n"
        for subtitle in self.subtitles:
            string += "  " + str(subtitle) + "\n"

        return string


class Video:
    def __init__(self):
        self.dimensions = None
        self.codec = None
        self.interlaced = None
        self.duration = None
        self.bitrate = None
        self.hdr = None
        self.hlg = None
        self.hdr10 = None
        self.hdr10plus = None
        self.dolbyvision = None

    @staticmethod
    def from_single_file(stream_info, format_info, frame_info):
        video = Video()
        video.dimensions = f"{stream_info['width']}x{stream_info['height']}"
        video.codec = stream_info["codec_name"]
        video.interlaced = stream_info.get("field_order", "progressive") != "progressive"
        video.duration = float(format_info["duration"])
        video.bitrate = get_bitrate(stream_info.get("tags", {}))
        video.hdr = Video._is_hdr(stream_info, frame_info)
        video.hlg = Video._is_hlg(frame_info)
        video.hdr10 = Video._is_hdr10(frame_info)
        video.hdr10plus = Video._is_hdr10_plus(frame_info)
        video.dolbyvision = Video._is_dolby_vision(stream_info)

        return video

    @staticmethod
    def from_bluray(stream: list, all_format_info, all_frame_info):
        video = Video()

        video.dimensions = f"{stream[0]['width']}x{stream[0]['height']}"
        video.codec = stream[0]["codec_name"]
        video.interlaced = stream[0].get("field_order", "progressive") != "progressive"
        video.duration = sum([float(info["duration"]) for info in all_format_info])
        video.hdr = Video._is_hdr(stream[0], all_frame_info[0])
        video.hlg = Video._is_hlg(all_frame_info[0])
        video.hdr10 = Video._is_hdr10(all_frame_info[0])
        video.hdr10plus = Video._is_hdr10(all_frame_info[0])
        video.dolbyvision = Video._is_dolby_vision(stream[0])

        return video

    def __str__(self):
        string = self.dimensions
        string += ", " + self.codec
        string += ", " + ("interlaced" if self.interlaced else "progressive")
        string += ", " + str(timedelta(seconds=int(self.duration)))
        string += (", " + self.bitrate) if self.bitrate else ""
        string += ", " + ("HDR" if self.hdr else "SDR")
        string += " (HLG)" if self.hlg else ""
        string += " (HDR10)" if self.hdr10 else ""
        string += " (HDR10+)" if self.hdr10plus else ""
        string += f" ({self.dolbyvision})" if self.dolbyvision else ""
        return string

    @staticmethod
    def _is_hdr(stream_info, frame_info):
        return frame_info.get("color_transfer", "unknown") in ["smpte2084", "arib-std-b67"] \
                or stream_info["codec_tag_string"] in ["dvh1", "dvhe"]

    @staticmethod
    def _is_hlg(frame_info):
        return frame_info.get("color_transfer", "unknown") == "arib-std-b67"

    @staticmethod
    def _is_hdr10(frame_info):
        for side_data in frame_info.get("side_data_list", []):
            if side_data["side_data_type"] == "Mastering display metadata":
                has_primaries = {"red_x", "red_y", "green_x", "green_y", "blue_x", "blue_y", "white_point_x", "white_point_y"}\
                    .issubset(side_data.keys())
                has_luminance = {"min_luminance", "max_luminance"}.issubset(side_data.keys())

                return has_primaries and has_luminance
        else:
            return False

    @staticmethod
    def _is_hdr10_plus(frame_info):
        for side_data in frame_info.get("side_data_list", []):
            if side_data["side_data_type"] == "HDR Dynamic Metadata SMPTE2094-40 (HDR10+)":
                return True
        else:
            return False

    @staticmethod
    def _is_dolby_vision(stream_info):
        for side_data in stream_info.get("side_data_list", []):
            if side_data["side_data_type"] == "DOVI configuration record":
                profile = side_data.get("dv_profile", "unknown profile")
                signal_compat_id = side_data.get("dv_bl_signal_compatibility_id", "unknown")
                return f"Dolby Vision {profile}.{signal_compat_id}"
        else:
            return None


class Audio:
    def __init__(self):
        self.index = None
        self.language = None
        self.bitrate = None
        self.title = None
        self.layout = None
        self.codec = None

    @staticmethod
    def from_single_file(stream_info, index):
        audio = Audio()
        audio.index = index
        audio.language = stream_info.get("tags", {}).get("language", "undefined")
        audio.bitrate = get_bitrate(stream_info.get("tags", {}))
        audio.title = stream_info.get("tags", {}).get("title", None)
        audio.layout = Audio.__get_layout(stream_info)
        audio.codec = Audio.__get_codec(stream_info)

        return audio

    @staticmethod
    def from_bluray(stream: list, mkvmerge_info, index):
        audio = Audio()
        audio.index = index
        audio.language = mkvmerge_info["properties"]["language"]
        audio.layout = Audio.__get_layout(stream[0])
        audio.codec = Audio.__get_codec(stream[0])

        return audio

    @staticmethod
    def __get_layout(stream_info):
        layout = stream_info.get("channel_layout", None)
        if not layout:
            if stream_info["channels"] == 1:
                layout = "mono"
            elif stream_info["channels"] == 2:
                layout = "stereo"
            else:
                layout = "unknown"
        return layout

    @staticmethod
    def __get_codec(stream_info):
        codec = stream_info["codec_name"]
        if codec == "dts":
            codec = stream_info["profile"].lower()
        return codec

    def __str__(self):
        string = str(self.index)
        string += ": " + self.language
        string += ", " + self.layout
        string += ", " + self.codec
        string += f", {self.bitrate}" if self.bitrate else ""
        string += f", '{self.title}'" if self.title else ""

        return string


class Subtitle:
    def __init__(self):
        self.index = None
        self.language = None
        self.codec = None
        self.count = None
        self.default = None
        self.forced = None

    @staticmethod
    def from_single_file(stream_info, index):
        subtitle = Subtitle()

        subtitle.index = index
        tags = stream_info.get("tags", {})
        subtitle.language = tags.get("language", "undefined")
        subtitle.codec = stream_info["codec_name"]
        subtitle.count = tags.get("NUMBER_OF_FRAMES-eng", tags.get("NUMBER_OF_FRAMES", None))
        subtitle.default = stream_info["disposition"]["default"]
        subtitle.forced = stream_info["disposition"]["forced"]

        return subtitle

    @staticmethod
    def from_bluray(stream, mkvmerge_info, index):
        subtitle = Subtitle()
        subtitle.index = index
        subtitle.language = mkvmerge_info["properties"]["language"]
        subtitle.codec = stream[0]["codec_name"]
        subtitle.count = sum([int(stream["nb_read_frames"]) for stream in stream])

        return subtitle

    def __str__(self):
        string = str(self.index)
        string += ": " + self.language
        string += ", " + self.codec
        string += (", " + str(self.count) + " elements") if self.count else ""
        string += ", default" if self.default else ""
        string += ", forced" if self.forced else ""

        return string


def get_bitrate(tags):
    bps = tags.get("BPS", tags.get("BPS-eng", None))
    if bps:
        kbps = int(bps) / 1000
        return f"{kbps:,.0f} kb/s"
    else:
        return None


if __name__ == "__main__":
    main()
