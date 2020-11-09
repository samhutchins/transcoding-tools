#!/usr/bin/env python3

from argparse import ArgumentParser
from os.path import basename
from sys import exit
from subprocess import run, PIPE
from datetime import timedelta
import os
import json
import shlex

version = """\
remux.py 2020.6
Copyright (c) 2020 Sam Hutchins\
"""

help = f"""\
Inspect and remux Blu Ray or DVD rips to prepare them for transcoding.

Usage: {basename(__file__)} [OPTION...] FILE

Creates an `mkv` file in the current directory

Output options:
    --inspect       print stream information and exit
    --dry-run       print the `mkvmerge` command and exit

Remux options:
-a, --select-audio TRACK [TRACK...]
                    select audio tracks by index to be included
    --an            Disable audio output
-s, --select-subtitle TRACK [TRACK...]
                    select subtitle tracks by index to be included
    --sn            Disable subtitle output
-f, --force-subtitle TRACK
                    select a subtitle track to be forced

Other options:
-h, --help          print this message and exit
    --version       print version information and exit

Requires `ffprobe` and `mkvmerge`\
"""

def main():
    parser = ArgumentParser(add_help=False)
    parser.add_argument("file", nargs="?")
    parser.add_argument("--inspect", action="store_true")
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

    if not args.file:
        exit(f"Missing argument: file. Try `{basename(__file__)} --help` for more information")

    verify_tools()
    
    if args.inspect:
        inspect_file(args.file)
        exit()

    audio_tracks = args.select_audio if not args.an else None
    subtitle_tracks = args.select_subtitle if not args.sn else None
    forced_subtitle = args.force_subtitle if not args.sn else None
    remux_file(args.file, audio_tracks, subtitle_tracks, forced_subtitle, args.dry_run)


def verify_tools():
    commands = [
        ["ffprobe", "-version"],
        ["mkvmerge", "--version"]]

    for command in commands:
        try:
            run(command, stdout=PIPE, stderr=PIPE).check_returncode()
        except:
            exit(f"`{command[0]}` not found")


def inspect_file(file):
    format, video, audio, subtitles = scan_media(file)

    # duration in whole seconds
    duration = int(float(format["duration"]))
    print("Video:")
    print(f"     {video['width']}x{video['height']}, {video['codec_name']}, {timedelta(seconds=duration)}")
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

        codec_name = audio_stream['codec_name']
        if codec_name == "dts":
            codec_name = audio_stream['profile'].lower()
        
        print(f"  {idx + 1}: {language}, {layout}, {codec_name}")

    print("Subtitle streams:")
    for idx, subtitle_stream in enumerate(subtitles):
        tags = subtitle_stream.get("tags", {})
        language = tags.get("language", "undefined")
        count = tags.get("NUMBER_OF_FRAMES-eng", "unknown")
        forced = ", forced" if subtitle_stream['disposition']['forced'] else ""
        print(f"  {idx + 1}: {language}, {subtitle_stream['codec_name']}, {count} elements{forced}")


def remux_file(file, audio_tracks, subtitle_tracks, forced_subtitle, dry_run):
    _, video, audio, subtitles = scan_media(file)

    if audio_tracks != None:
        for track in audio_tracks:
            if track <= 0 or len(audio) < track:
                exit(f"Selected audio track out of range: {track}.")

    if subtitle_tracks != None:
        for track in subtitle_tracks:
            if track <= 0 or len(subtitles) < track:
                exit(f"Selected subtitle track out of range: {track}")

    if forced_subtitle and (forced_subtitle <= 0 or len(subtitles) < forced_subtitle):
        exit(f"Forced subtitle out of range: {forced_subtitle}")

    if audio_tracks == []:
        selected_audio_streams = audio
    elif audio_tracks == None:
        selected_audio_streams = None
    else:
        selected_audio_streams = [stream for idx, stream in enumerate(audio) if idx + 1 in audio_tracks]
    
    if subtitle_tracks == []:
        selected_subtitle_streams = subtitles
    elif subtitle_tracks == None:
        selected_subtitle_streams = None
    else:
        selected_subtitle_streams = [stream for idx, stream in enumerate(subtitles) if idx + 1 in subtitle_tracks]

    forced_subtitle_stream = subtitles[forced_subtitle - 1] if forced_subtitle else None

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
        subtitle_arg += ["--subtitle-tracks"]
        for subtitle_stream in selected_subtitle_streams:
            stream_index = str(subtitle_stream["index"])
            subtitle_arg += [str(stream_index)]

            if subtitle_stream != forced_subtitle_stream:
                forced_options += ["--default-track", f"{stream_index}:0"]
                forced_options += ["--forced-track", f"{stream_index}:0"]
            else:
                forced_options += ["--default-track", stream_index]
                forced_options += ["--forced-track", stream_index]
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

    mkvmerge_command += forced_options
    mkvmerge_command += audio_arg
    mkvmerge_command += subtitle_arg
    mkvmerge_command += [file]

    if dry_run:
        escaped = [shlex.quote(s) for s in mkvmerge_command]
        print(" ".join(escaped))
        return

    if os.path.exists(output_file):
        exit(f"Output file already exists: {output_file}")
    
    print(f"Remuxing {file}...")
    run(mkvmerge_command)


def scan_media(file):
    command = [
        "ffprobe",
        "-loglevel", "quiet",
        "-show_streams",
        "-show_format",
        "-print_format", "json",
        file]

    output = run(command, stdout=PIPE, stderr=PIPE).stdout
    media_info = json.loads(output)

    format = media_info["format"]
    video = [s for s in media_info["streams"] if s["codec_type"] == "video"][0]
    audio = [s for s in media_info["streams"] if s["codec_type"] == "audio"]
    audio.sort(key=lambda a: a["index"])
    subtitles = [s for s in media_info["streams"] if s["codec_type"] == "subtitle"]
    subtitles.sort(key=lambda s: s["index"])

    return format, video, audio, subtitles

if __name__ == "__main__":
    main()