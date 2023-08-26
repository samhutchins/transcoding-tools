#!/usr/bin/env python3
# remux.py
# requires mkvmerge

import json
import os
import shlex
from argparse import ArgumentParser
from subprocess import DEVNULL, PIPE, run


def main():
    parser = ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("-a", "--audio", nargs="+", type=int, default=[])
    parser.add_argument("-s", "--subtitle", nargs="+", type=int, default=[])
    parser.add_argument("-f", "--force-subtitle", type=int)
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    remuxer = Remuxer()
    remuxer.dryrun = args.dry_run
    remuxer.audio_tracks = args.audio
    remuxer.subtitle_tracks = args.subtitle
    remuxer.forced_subtitle = args.force_subtitle
    remuxer.remux(args.file)


class Remuxer:
    def __init__(self):
        self.dryrun = False
        self.audio_tracks = []
        self.subtitle_tracks = []
        self.forced_subtitle = None

    def remux(self, input_file):
        if not os.path.exists(input_file):
            exit(f"No such file: {input_file}")

        if os.path.isdir(input_file):
            exit("Folder inputs are not supported")

        output_file = os.path.splitext(os.path.basename(input_file))[0] + ".mkv"
        if not self.dryrun and os.path.exists(output_file):
            exit(f"Output file exists: {output_file}")

        self.__verify_tools()

        media_info = self.__scan_media(input_file)
        video_tracks = [ x for x in media_info["tracks"] if x["type"] == "video" ]

        command = [
            "mkvmerge",
            "--output", output_file,
            "--title", "",
            "--video-tracks", str(video_tracks[0]["id"])]

        command += self.__get_audio_args(media_info)
        command += self.__get_subtitle_args(media_info)

        command += [input_file]

        print(" ".join(map(lambda x: shlex.quote(x), command)))

        if not self.dryrun:
            run(command)

    @staticmethod
    def __verify_tools():
        command = ["mkvmerge", "--version"]
        try:
            run(command, stdout=PIPE, stderr=PIPE).check_returncode()
        except:
            exit(f"Failed to run {command[0]}")

    @staticmethod
    def __scan_media(file):
        command = ["mkvmerge", "-J", file]

        mkvmerge_result = run(command, stdout=PIPE, stderr=DEVNULL, universal_newlines=True).stdout
        return json.loads(mkvmerge_result)

    def __get_audio_args(self, media_info):
        audio_tracks = [x for x in media_info["tracks"] if x["type"] == "audio"]
        
        selected_tracks = []
        for idx in self.audio_tracks:
            if idx < 1 or len(audio_tracks) < idx:
                exit(f"Index out of range for audio tracks. Index: {idx}, size: {len(audio_tracks)}")

            selected_tracks.append(str(audio_tracks[idx-1]["id"]))
        
        if selected_tracks:
            args = ["--audio-tracks", ",".join(selected_tracks)]

        else:
            args = ["--no-audio"]

        return args

    def __get_subtitle_args(self, media_info):
        subtitle_tracks = [ x for x in media_info["tracks"] if x["type"] == "subtitles"]

        selected_tracks = []
        for idx in self.subtitle_tracks:
            if idx < 1 or len(subtitle_tracks) < idx:
                exit(f"Index out of range for subtitle tracks. Index {idx}, size: {len(subtitle_tracks)}")
            
            selected_tracks.append(str(subtitle_tracks[idx-1]["id"]))

        if self.forced_subtitle:
            if self.forced_subtitle < 1 or len(subtitle_tracks) < self.forced_subtitle:
                exit(f"Index out of range for forced subtitle track. Index {idx}, size: {len(subtitle_tracks)}")

            forced_id = str(subtitle_tracks[self.forced_subtitle-1]["id"])
            if forced_id not in selected_tracks:
                selected_tracks.append(forced_id)

        if selected_tracks:
            args = ["--subtitle-tracks", ",".join(selected_tracks)]
            if self.forced_subtitle:
                args += [
                    "--default-track", f"{forced_id}:1",
                    "--forced-track", f"{forced_id}:1"]
        else:
            args = ["--no-subtitles"]

        return args


if __name__ == "__main__":
    main()
