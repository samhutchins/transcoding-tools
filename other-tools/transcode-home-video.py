#!/usr/bin/env python3

import json
import os
import tempfile
from argparse import ArgumentParser
from collections import defaultdict
from subprocess import DEVNULL, PIPE, run, CalledProcessError
from sys import exit


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
    for file in args.file:
        transcoder.transcode(file)


class Transcoder:
    def __init__(self):
        self.debug = False

    def transcode(self, input_file):
        if not os.path.exists(input_file):
            exit(f"No such file: {input_file}")

        if os.path.isdir(input_file):
            exit("Folder inputs are not supported")

        output_file = os.path.splitext(os.path.basename(input_file))[0] + ".mp4"
        if os.path.exists(output_file):
            exit(f"Output file exists: {output_file}")

        media_info = self.__scan_media(input_file)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_out = os.path.join(tmp_dir, "intermediate.mp4")
            print(tmp_dir)

            handbrake_command = [
                "HandBrakeCLI",
                "--no-dvdnav",
                "--input", input_file,
                "--output", tmp_out,
                "--previews", "1",
                "--markers"
            ]

            handbrake_command += self.__get_picture_args()
            handbrake_command += self.__get_video_args(media_info)
            handbrake_command += self.__get_audio_args(media_info)

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

        return media_info

    @staticmethod
    def __get_picture_args():
        return [
            "--crop", "0:0:0:0",
            "--loose-anamorphic"]

    @staticmethod
    def __get_video_args(media_info):
        geometry = media_info["Geometry"]
        if geometry["Width"] > 1920 or geometry["Height"] > 1080:
            bitrate = 10000
        elif geometry["Width"] > 1280 or geometry["Height"] > 720:
            bitrate = 6000
        elif geometry["Width"] * geometry["Height"] > 720 * 576:
            bitrate = 3000
        else:
            bitrate = 1500

        vbv = bitrate * 3

        return [
            "--vb", str(bitrate),
            "--encoder", "x264",
            "--multi-pass", "--turbo",
            "--encoder-profile", "high",
            "--encoder-preset", "medium",
            "--encopts", f"vbv-maxrate={vbv}:vbv-bufsize={vbv}"]

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
        handbrake_help = run(["HandBrakeCLI", "--help"], stdout=PIPE, stderr=DEVNULL, universal_newlines=True).stdout
        handbrake_encoders = [x.strip() for x in handbrake_help.partition("Select audio encoder(s):")[2].partition("\"")[0].splitlines()]
        for encoder in ["ca_aac", "fdk_aac", "av_aac"]:
            if encoder in handbrake_encoders:
                aac_encoder = encoder
                break
        else:
            aac_encoder = "av_aac"

        if audio_track["ChannelCount"] > 2:
            bitrate = "384"
        elif audio_track["ChannelCount"] == 2:
            bitrate = "128"
        else:
            bitrate = "96"

        return aac_encoder, bitrate


if __name__ == "__main__":
    main()
