#!/usr/bin/env python3

import json
import os
import tempfile
from argparse import ArgumentParser
from collections import defaultdict
from subprocess import DEVNULL, PIPE, run, CalledProcessError
from sys import exit
import shlex
import re


def main():
    parser = ArgumentParser(
        description="Transcode home video, preserving metadata from the input",
        usage="%(prog)s FILE [OPTION]...",
        epilog="Requires `HandBrakeCLI` and `ffmpeg`.",
        add_help=False)

    input_options = parser.add_argument_group("Input Options")
    input_options.add_argument("file", nargs="+", metavar="FILE", help="path to source file")

    output_options = parser.add_argument_group("Output Options")
    output_options.add_argument("--dry-run", action="store_true", default=False,
                                help="print `HandBrakeCLI` command and exit")

    other_options = parser.add_argument_group("Other Options")
    other_options.add_argument("--debug", action="store_true", help="turn on debugging output")
    other_options.add_argument("-h", "--help", action="help", help="print this message and exit")

    args = parser.parse_args()

    transcoder = Transcoder()
    transcoder.debug = args.debug
    transcoder.dry_run = args.dry_run
    for file in args.file:
        transcoder.transcode(file)


class Transcoder:
    def __init__(self):
        self.debug = False
        self.dry_run = False

    def transcode(self, input_file):
        if not os.path.exists(input_file):
            exit(f"No such file: {input_file}")

        if os.path.isdir(input_file):
            exit("Folder inputs are not supported")

        output_file = os.path.splitext(os.path.basename(input_file))[0] + ".mp4"
        if os.path.exists(output_file) and not self.dry_run:
            exit(f"Output file exists: {output_file}")

        media_info = self.__scan_media(input_file)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_out = os.path.join(tmp_dir, "intermediate.mp4")

            handbrake_command = [
                "HandBrakeCLI",
                "--no-dvdnav",
                "--input", input_file,
                "--output", tmp_out,
                "--previews", "1",
                "--markers"
            ]

            handbrake_command += self.__get_picture_args(media_info)
            handbrake_command += self.__get_video_args()
            handbrake_command += self.__get_audio_args(media_info)

            print(" ".join(map(lambda x: shlex.quote(x), handbrake_command)))

            if self.dry_run:
                return

            try:
                run(handbrake_command, stderr=DEVNULL).check_returncode()
            except CalledProcessError as e:
                exit(f"HandBrakeCLI failed: {e}")

            if os.path.exists(output_file):
                exit(f"Output file exists: {output_file}")

            if os.path.exists(tmp_out):
                ffmpeg_command = [
                    "ffmpeg",
                    "-i", input_file,
                    "-i", tmp_out,
                    "-map", "1",
                    "-map_metadata", "0",
                    "-movflags", "use_metadata_tags",
                    "-movflags", "+faststart",
                    "-c", "copy",
                    output_file]
                try:
                    run(ffmpeg_command).check_returncode()
                except CalledProcessError as e:
                    exit(f"ffmpeg failed: {e}")

    def __scan_media(self, input_file):
        scan_command = ["HandBrakeCLI",
                        "--json",
                        "--scan",
                        "--crop-mode", "conservative",
                        "--previews", "10",
                        "--input", input_file]

        command_output = run(scan_command, stdout=PIPE, stderr=PIPE)
        json_scan_result = command_output.stdout.partition(b"JSON Title Set:")[2]

        if self.debug:
            print("Json output: " + json_scan_result.decode())

        if not json_scan_result:
            exit("Scan failed")

        full_media_info = json.loads(json_scan_result)
        main_title = full_media_info["MainFeature"]

        media_info = full_media_info["TitleList"][main_title]

        # Can't trust HandBrake's default InterlaceDetected behaviour, we need to check ourselves
        interlaced = False
        video_line_regex = re.compile(b"^.*?Stream.*?Video.*$", re.MULTILINE)
        regex_result = video_line_regex.search(command_output.stderr)
        if regex_result:
            start, end = regex_result.span()
            video_line = command_output.stderr[start:end]
            if self.debug:
                print("Video Line: " + video_line.decode())
            interlaced = b"top first" in video_line or b"bottom first" in video_line
        elif self.debug:
            print("Video line regex didn't find anything")

        if self.debug:
            print(f"Interlace detected: {interlaced}")

        media_info["InterlaceDetected"] = interlaced

        # detecting HDR properly is a bit involved, but for what I'm doing I only need to detect HDR in videos from an iPhone
        # If the video line contains arib-std-b67, it's HDR
        media_info["HdrDetected"] = b"arib-std-b67" in video_line
        if self.debug:
            print(f"HdrDetected: {media_info['HdrDetected']}")

        return media_info

    @staticmethod
    def __get_picture_args(media_info):
        geometry = media_info["Geometry"]
        is_landscape = geometry["Width"] >= geometry["Height"]

        if is_landscape:
            max_dimension_args = ["--maxWidth", "1920", "--maxHeight", "1080"]
        else:
            max_dimension_args = ["--maxWidth", "1080", "--maxHeight", "1920"]
        
        filters = []
        if media_info["InterlaceDetected"]:
            filters.extend(["--comb-detect", "--decomb"])

        if media_info["HdrDetected"]:
            filters.extend(["--colorspace", "bt709"])

        return [
            "--crop", "0:0:0:0",
            "--non-anamorphic",
            *max_dimension_args,
            *filters]

    @staticmethod
    def __get_video_args():
        return [
            "-r", "30",
            "-b", "6000",
            "--enable-hw-decoding", "videotoolbox",
            "--encoder", "vt_h264",
            "--encoder-profile", "high",
            "--encoder-preset", "quality"]

    def __get_audio_args(self, media_info):
        audio_tracks = media_info["AudioList"]
        audio_args = defaultdict(list)

        for audio_track in audio_tracks:
            if audio_track["CodecName"] in ["aac"]:
                encoder, bitrate = "copy", ""
            else:
                encoder, bitrate = self.__get_aac_args(audio_track)

            audio_args["track"].append(str(audio_track["TrackNumber"]))
            audio_args["encoder"].append(encoder)
            audio_args["bitrate"].append(bitrate)

        tracks = ",".join(audio_args["track"])
        encoders = ",".join(audio_args["encoder"])
        bitrates = ",".join(audio_args["bitrate"])

        audio_args = [
            "--audio", tracks,
            "--aencoder", encoders,
            *(["--ab", bitrates] if bitrates else [])]

        return audio_args

    @staticmethod
    def __get_aac_args(audio_track):
        if audio_track["ChannelCount"] > 2:
            bitrate = "384"
        elif audio_track["ChannelCount"] == 2:
            bitrate = "128"
        else:
            bitrate = "96"

        return "ca_aac", bitrate


if __name__ == "__main__":
    main()
