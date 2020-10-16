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
remux.py 2020.5
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
-s, --select-subtitle TRACK [TRACK...]
                    select subtitle tracks by index to be included
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
    parser.add_argument("-a", "--select-audio", metavar="TRACK", nargs="+", type=int)
    parser.add_argument("-s", "--select-subtitle", metavar="TRACK", nargs="+", type=int)
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

    remux_file(args.file, args.select_audio, args.select_subtitle, args.force_subtitle, args.dry_run)


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

    if audio_tracks:
        for track in audio_tracks:
            if track <= 0 or len(audio) < track:
                exit(f"Selected audio track out of range: {track}.")

    if subtitle_tracks:
        for track in subtitle_tracks:
            if track <= 0 or len(subtitles) < track:
                exit(f"Selected subtitle track out of range: {track}")

    if forced_subtitle and (forced_subtitle <= 0 or len(subtitles) < forced_subtitle):
        exit(f"Forced subtitle out of range: {forced_subtitle}")

    selected_audio_streams = [stream for idx, stream in enumerate(audio) if idx + 1 in audio_tracks] if audio_tracks else audio
    selected_subtitle_streams = [stream for idx, stream in enumerate(subtitles) if idx + 1 in subtitle_tracks] if subtitle_tracks else subtitles
    forced_subtitle_stream = subtitles[forced_subtitle - 1] if forced_subtitle else None

    if forced_subtitle_stream and forced_subtitle_stream not in selected_subtitle_streams:
        selected_subtitle_streams.append(forced_subtitle_stream)
    
    title = os.path.splitext(basename(file))[0]
    output_file = f"{title}.mkv"

    # thanks Don!
    audio_arg = ""
    for audio_stream in selected_audio_streams:
        audio_arg += "," if audio_arg else ""
        audio_arg += str(audio_stream["index"])

    subtitle_arg = ""
    forced_options = []
    for subtitle_stream in selected_subtitle_streams:
        subtitle_arg += "," if subtitle_arg else ""
        stream_index = str(subtitle_stream["index"])
        subtitle_arg += stream_index

        if subtitle_stream != forced_subtitle_stream:
            forced_options += ["--default-track", f"{stream_index}:0"]
            forced_options += ["--forced-track", f"{stream_index}:0"]
        else:
            forced_options += ["--default-track", stream_index]
            forced_options += ["--forced-track", stream_index]

    video_index = str(video["index"])
    first_audio_index = str(selected_audio_streams[0]["index"])

    mkvmerge_command = [
        "mkvmerge",
        "--output", output_file,
        "--title", "",
        "--default-track", video_index,
        "--default-track", first_audio_index,
    ] + forced_options + [
        "--video-tracks", video_index,
        "--audio-tracks", audio_arg
    ] + (["--subtitle-tracks", subtitle_arg] if subtitle_arg else []) + [
        "--no-buttons",
        "--no-attachments",
        "--no-track-tags",
        "--no-global-tags",
        file
    ]

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