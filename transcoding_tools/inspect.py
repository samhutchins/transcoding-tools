from argparse import ArgumentParser
from datetime import timedelta

from .__init__ import __version__
from . import utils

version = f"""\
inspect.py {__version__}
Copyright (c) 2021 Sam Hutchins\
"""

help = f"""\
Inspect Blu Ray or DVD rips to gain knowledge and power.

Usage: inspect [OPTION...] FILE

Options:
    --print-crop    Print just crop information and exit.

-h, --help          Print this message and exit
    --version       Print version information and exit

Requires `ffprobe` and `ffmpeg`\
"""


class Inspector:
    def __init__(self):
        self.print_crop = False


    def run(self):
        parser = ArgumentParser(add_help=False)
        parser.add_argument("file", nargs="?")
        parser.add_argument("--print-crop", action="store_true")

        parser.add_argument("-h", "--help", action="store_true")
        parser.add_argument("--version", action="store_true")

        args = parser.parse_args()

        if args.version:
            print(version)
            exit()

        if args.help:
            print(help)
            exit()

        self.validate_args(args)
        utils.verify_tools([["ffmpeg", "-version"], ["ffprobe", "-version"]])
        self.inspect(args.file)


    def validate_args(self, args):
        if not args.file:
            exit("Missing argument: file. Try `inspect --help` for more information")

        self.print_crop = args.print_crop


    def inspect(self, file):
        media_info = utils.scan_media(file)

        crop = utils.detect_crop(media_info)
        if self.print_crop:
            print(crop)
            exit()
        else:
            self.inspect_streams(media_info, crop)


    def inspect_streams(self, media_info, crop):
        format = media_info["format"]
        video = utils.get_video_stream(media_info)
        audio = utils.get_audio_streams(media_info)
        subtitles = utils.get_subtitle_streams(media_info)

        dimensions = f"{video['width']}x{video['height']}"
        codec_name = f", {video['codec_name']}"
        interlaced = ", interlaced" if utils.is_interlaced_encoding(media_info) else ""
        interlacing_artefacts = " with artefacts" if utils.detect_interlacing_artefacts(media_info) else ""
        duration = f", {timedelta(seconds=int(float(format['duration'])))}"
        crop_info = f", crop={crop}" if crop else ""
        print("Video:")
        print(f"     {dimensions}{codec_name}{interlaced}{interlacing_artefacts}{duration}{crop_info}")
        
        print("Audio streams:")
        for idx, audio_stream in enumerate(audio):
            tags = audio_stream.get("tags", {})
            language = tags.get("language", "undefined")
            layout = audio_stream.get("channel_layout", None)
            if not layout:
                if audio_stream["channels"] == 1:
                    layout = "mono"
                elif audio_stream["channels"] == 2:
                    layout = "stereo"
                else:
                    layout = "unknown"

            layout = f", {layout}"

            codec_name = audio_stream['codec_name']
            if codec_name == "dts":
                codec_name = audio_stream['profile'].lower()
            codec_name = f", {codec_name}"
            
            print(f"  {idx + 1}: {language}{layout}{codec_name}")

        print("Subtitle streams:")
        for idx, subtitle_stream in enumerate(subtitles):
            tags = subtitle_stream.get("tags", {})
            language = tags.get("language", "undefined")
            codec_name = f", {subtitle_stream['codec_name']}"
            count = f", {tags.get('NUMBER_OF_FRAMES-eng', 'unknown')} elements"
            default = ", default" if subtitle_stream['disposition']['default'] else ""
            forced = ", forced" if subtitle_stream['disposition']['forced'] else ""
            print(f"  {idx + 1}: {language}{codec_name}{count}{default}{forced}")


def main():
    Inspector().run()
