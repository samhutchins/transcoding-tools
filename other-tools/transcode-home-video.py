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
import pprint


def main():
    parser = ArgumentParser(
        description="Transcode home video, preserving metadata from the input",
        usage="%(prog)s FILE [OPTION]...",
        epilog="Requires `ffprobe` and `ffmpeg`.",
        add_help=False)

    input_options = parser.add_argument_group("Input Options")
    input_options.add_argument("file", nargs="+", metavar="FILE", help="path to source file")

    output_options = parser.add_argument_group("Output Options")
    output_options.add_argument("--dry-run", action="store_true", default=False,
                                help="print `ffmpeg` command and exit")

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

        stream_info, frame_info = self.__scan_media(input_file)

        command = [
            "ffmpeg",
            "-loglevel", "error",
            "-stats",
            "-hwaccel", "auto",
            "-i", input_file,
            "-map_metadata", "0",
            "-movflags", "use_metadata_tags",
            "-movflags", "+faststart",
            *self.__get_picture_args(stream_info, frame_info),
            *self.__get_video_args(),
            *self.__get_audio_args(stream_info),
            output_file
        ]

        print(" ".join(map(lambda x: shlex.quote(x), command)))

        if self.dry_run:
            return

        try:
            run(command).check_returncode()
        except CalledProcessError as e:
            exit(f"ffmpeg failed: {e}")

    def __scan_media(self, input_file):
        command = [
            "ffprobe",
            "-loglevel", "quiet",
            "-show_streams",
            "-print_format", "json",
            input_file
        ]

        stream_info = json.loads(run(command, stdout=PIPE, stderr=DEVNULL).stdout)
        if self.debug:
            print("Stream info")
            pprint.pprint(stream_info)
            print("---")

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

        if self.debug:
            print("Frame info")
            pprint.pprint(stream_info)
            print("---")

        return stream_info["streams"], frame_info["frames"][0]

    def __get_picture_args(self, stream_info, frame_info):
        video = [ x for x in stream_info if x["codec_type"] == "video"][0]
        interlaced = video.get("field_order", "progressive") != "progressive"
        hdr = frame_info.get("color_transfer", "unknown") in ["smpte2084", "arib-std-b67"] \
                or video["codec_tag_string"] in ["dvh1", "dvhe"]
        width = video["width"]
        height = video["height"]
        display_matrix = [ x for x in video.get("side_data_list", []) if x["side_data_type"] == "Display Matrix"]
        
        if display_matrix and display_matrix[0]["rotation"] in [-90, 90]:
            tmp = width
            width = height
            height = tmp
            
        landscape = width >= height

        filter_chain = []
        if interlaced:
            yadif_options = ["mode=send_frame", "parity=auto", "deint=interlaced"]
            
            filter_string = "yadif=" + ":".join(yadif_options)
            filter_chain.append(filter_string)

            if self.debug:
                print(f"Deinterlacing with {filter_string}")

        
        max_width = 1920 if landscape else 1080
        max_height = 1080 if landscape else 1920
        scale = min(max_width / width, max_height / height)
        
        libplacebo_options = []
        if scale < 1:
            if self.debug:
                print("Scaling output")

            width = int(width * scale)
            height = int(height * scale)
            libplacebo_options += [
                f"w={width}",
                f"h={height}",
                "downscaler=mitchell"]

        if hdr:
            if self.debug:
                print("Tonemapping output")

            libplacebo_options += [
                "colorspace=bt709",
                "color_primaries=bt709",
                "color_trc=bt709",
                "range=tv",
                "format=yuv420p"
            ]

        if libplacebo_options:
            filter_string = "libplacebo=" + ":".join(libplacebo_options)
            filter_chain.append(filter_string)
        
        picture_args = []
        if filter_chain:
            filter_string = ",".join(filter_chain)
            picture_args += ("-vf", filter_string)
        
        if self.debug:
            print(picture_args)
        
        return picture_args

    @staticmethod
    def __get_video_args():
        return [
            "-c:v", "libx264",
            "-preset:v", "medium",
            "-refs:v", "1",
            "-rc-lookahead:v", "30",
            "-partitions:v", "none",
            "-crf", "20",
            "-maxrate:v", "8000k",
            "-bufsize:v", "12000k"]

    def __get_audio_args(self, stream_info):
        audio_args = []

        audio_streams = [x for x in stream_info if x["codec_type"] == "audio"]

        for i, audio in enumerate(audio_streams):
            if audio["channels"] > 2:
                audio_args += [
                    f"-ac:a:{i}", "2",
                    f"-c:a:{i}", "aac_at"]
            elif audio["codec_name"] != "aac":
                audio_args += [f"-c:a:{i}", "aac_at"]
            else:
                audio_args += [f"-c:a:{i}", "copy"]
            
            audio_args += [f"-metadata:s:a:{i}", "language=eng"]
        
        if self.debug:
            print(audio_args)

        return audio_args


if __name__ == "__main__":
    main()
