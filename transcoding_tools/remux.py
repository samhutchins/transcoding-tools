from argparse import ArgumentParser
from os.path import basename
from sys import exit
from subprocess import run
import os
import shlex

from .__init__ import __version__
from . import utils

version = f"""\
remux.py {__version__}
Copyright (c) 2020,2021 Sam Hutchins\
"""

help = f"""\
Remux Blu Ray or DVD rips to prepare them for transcoding.

Usage: remux.py [OPTION...] FILE

Creates an `mkv` file in the current directory

Output options:
    --dry-run       print the `mkvmerge` command and exit

Remux options:
-a, --select-audio TRACK [TRACK...]
                    Select audio tracks by index to be included
    --an            Disable audio output
-s, --select-subtitle TRACK [TRACK...]
                    Select subtitle tracks by index to be included
    --sn            Disable subtitle output
-f, --force-subtitle TRACK
                    Select a subtitle track to be forced

Other options:
-h, --help          Print this message and exit
    --version       Print version information and exit

Requires `ffprobe` and `mkvmerge`\
"""

class Remuxer:
    def __init__(self):
        self.dry_run = False

        self.audio_tracks = None
        self.subtitle_tracks = None
        self.forced_subtitle = None
        
    
    def run(self):
        parser = ArgumentParser(add_help=False)
        parser.add_argument("file", nargs="?")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("-a", "--select-audio", metavar="TRACK", nargs="+", type=int, default=[])
        parser.add_argument("--an", action="store_true")
        parser.add_argument("-s", "--select-subtitle", metavar="TRACK", nargs="+", type=int, default=[])
        parser.add_argument("--sn", action="store_true")
        parser.add_argument("-f", "--force-subtitle", metavar="TRACK", type=int)
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
        utils.verify_tools([["ffprobe", "-version"], ["mkvmerge", "--version"]])

        self.remux(args.file)


    def validate_args(self, args):
        if not args.file:
            exit(f"Missing argument: file. Try `{basename(__file__)} --help` for more information")

        self.dry_run = args.dry_run
        self.audio_tracks = args.select_audio if not args.an else None
        self.subtitle_tracks = args.select_subtitle if not args.sn else None
        self.forced_subtitle = args.force_subtitle if not args.sn else None


    def remux(self, file):
        media_info = utils.scan_media(file)
        video = utils.get_video_stream(media_info)
        audio = utils.get_audio_streams(media_info)
        subtitles = utils.get_subtitle_streams(media_info)

        if self.audio_tracks != None:
            for track in self.audio_tracks:
                if track <= 0 or len(audio) < track:
                    exit(f"Selected audio track out of range: {track}.")

        if self.subtitle_tracks != None:
            for track in self.subtitle_tracks:
                if track <= 0 or len(subtitles) < track:
                    exit(f"Selected subtitle track out of range: {track}")

        if self.forced_subtitle and (self.forced_subtitle <= 0 or len(subtitles) < self.forced_subtitle):
            exit(f"Forced subtitle out of range: {self.forced_subtitle}")

        if self.audio_tracks == []:
            selected_audio_streams = audio
        elif self.audio_tracks == None:
            selected_audio_streams = None
        else:
            selected_audio_streams = [stream for idx, stream in enumerate(audio) if idx + 1 in self.audio_tracks]
        
        if self.subtitle_tracks == []:
            selected_subtitle_streams = subtitles
        elif self.subtitle_tracks == None:
            selected_subtitle_streams = None
        else:
            selected_subtitle_streams = [stream for idx, stream in enumerate(subtitles) if idx + 1 in self.subtitle_tracks]

        forced_subtitle_stream = subtitles[self.forced_subtitle - 1] if self.forced_subtitle else None

        if forced_subtitle_stream and forced_subtitle_stream not in selected_subtitle_streams:
            selected_subtitle_streams.append(forced_subtitle_stream)
        
        title = os.path.splitext(basename(file))[0]
        output_file = f"{title}.mkv"

        # thanks Don!
        audio_arg = []
        if selected_audio_streams != None:
            audio_arg += ["--audio-tracks", ",".join(map(lambda x: str(x["index"]), selected_audio_streams))]
            first_audio_index = str(selected_audio_streams[0]["index"])
            audio_arg += ["--default-track", first_audio_index]
        else:
            audio_arg = ["--no-audio"]
        
        subtitle_arg = []
        forced_options = []
        if selected_subtitle_streams != None:
            subtitle_arg += ["--subtitle-tracks", ",".join(map(lambda x: str(x["index"]), selected_subtitle_streams))]
            for subtitle_stream in selected_subtitle_streams:
                stream_index = str(subtitle_stream["index"])
                if subtitle_stream == forced_subtitle_stream:
                    forced_options += ["--default-track", f"{stream_index}:1"]
                    forced_options += ["--forced-track", f"{stream_index}:1"]
                else:
                    forced_options += ["--default-track", f"{stream_index}:0"]
                    forced_options += ["--forced-track", f"{stream_index}:0"]
        else:
            subtitle_arg = ["--no-subtitles"]

        video_index = str(video["index"])

        mkvmerge_command = [
            "mkvmerge",
            "--output", output_file,
            "--title", "",
            "--default-track", video_index,
            "--video-tracks", video_index,
            "--no-buttons",
            "--no-attachments",
            "--no-track-tags",
            "--no-global-tags"]

        mkvmerge_command += audio_arg
        mkvmerge_command += subtitle_arg
        mkvmerge_command += forced_options
        mkvmerge_command += [file]

        print(" ".join(map(lambda x: shlex.quote(x), mkvmerge_command)))
        if self.dry_run:
            exit()

        if os.path.exists(output_file):
            exit(f"Output file already exists: {output_file}")
        
        print(f"Remuxing {file}...")
        run(mkvmerge_command)

def main():
    Remuxer().run()
