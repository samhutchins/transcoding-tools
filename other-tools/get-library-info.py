#!/usr/bin/env python3

import json
import os
from argparse import ArgumentParser
from collections import defaultdict
from subprocess import run, PIPE, DEVNULL


def main():
    parser = ArgumentParser()
    parser.add_argument("-l", "--library", default="X:\\Plex Library\\Films")

    args = parser.parse_args()

    codecs = defaultdict(list)
    sizes = defaultdict(list)
    for root, _, files in os.walk(args.library):
        for file in map(lambda x: os.path.join(root, x), files):
            media_info = scan_media(file)
            codec = get_codec(media_info)
            size = get_dimensions(media_info)

            codecs[codec].append(file)
            sizes[size].append(file)


    for size in sizes:
        print(f"{size}: {len(sizes[size])}")

    for codec in codecs:
        print(f"{codec}: {len(codecs[codec])}")


def get_codec(media_info):
    if "streams" in media_info and media_info["streams"]:
        return media_info["streams"][0]["codec_name"]
    else:
        return "unknown"


def get_dimensions(media_info):
    if "streams" in media_info and media_info["streams"]:
        return f"{media_info['streams'][0]['width']}x{media_info['streams'][0]['height']}"
    else:
        return "unknown"


def scan_media(file):
    command = ["ffprobe", 
                "-loglevel", "quiet",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,width,height",
                "-print_format", "json",
                file]

    result = run(command, stdout=PIPE, stderr=DEVNULL).stdout

    return json.loads(result)

if __name__ == "__main__":
    main()