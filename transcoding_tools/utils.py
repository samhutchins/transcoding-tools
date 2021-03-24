from typing import List
from subprocess import run, PIPE, DEVNULL
import json
import re
import sys


def verify_tools(commands):
    print("Verifying tools...", file=sys.stderr)

    for command in commands:
        try:
            run(command, stdout=PIPE, stderr=PIPE).check_returncode()
        except:
            exit(f"`{command[0]}` not found")


def scan_media(file):
    command = [
        "ffprobe",
        "-loglevel", "quiet",
        "-show_streams",
        "-show_format",
        "-print_format", "json",
        file
    ]

    output = run(command, stdout=PIPE, stderr=PIPE).stdout
    return json.loads(output)


def get_video_stream(media_info):
    return [s for s in media_info["streams"] if s["codec_type"] == "video"][0]


def get_audio_streams(media_info):
    return [s for s in media_info["streams"] if s["codec_type"] == "audio"]


def get_subtitle_streams(media_info):
    return [s for s in media_info["streams"] if s ["codec_type"] == "subtitle"]


def is_interlaced_encoding(media_info):
    video_stream = get_video_stream(media_info)
    return video_stream.get("field_order", "progressive") != "progressive"


# This algorithm is shamelessly taken from Don Melton's `other_video_transcoding` project: 
# https://github.com/donmelton/other_video_transcoding
def detect_crop(media_info):
    print("Detecting crop...", file=sys.stderr)
    duration = float(media_info["format"]["duration"])
    if duration < 2:
        exit(f"Duration too short: {duration}")

    steps = 10
    interval = int(duration / (steps + 1))
    target_interval = 5 * 60

    if interval == 0:
        steps = 1
        interval = 1
    elif interval > target_interval:
        steps = int((duration / target_interval) - 1)
        interval = int(duration / (steps + 1))

    video = [s for s in media_info["streams"] if s["codec_type"] == "video"][0]
    width = int(video["width"])
    height = int(video["height"])

    no_crop = {
        "width": width,
        "height": height,
        "x": 0,
        "y": 0
    }

    all_crop = {
        "width": 0,
        "height": 0,
        "x": width,
        "y": height
    }

    crop = all_crop.copy()
    last_crop = crop.copy()
    ignore_count = 0

    path = media_info["format"]["filename"]

    for step in range(1, steps + 1):
        s_crop = all_crop.copy()
        position = interval * step

        command = [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-noaccurate_seek",
            "-ss", str(position),
            "-i", path,
            "-frames:v", "15",
            "-filter:v", "cropdetect=24:2",
            "-an",
            "-sn",
            "-ignore_unknown",
            "-f", "null",
            "-"
        ]

        result = run(command, stdout=DEVNULL, stderr=PIPE).stderr.decode("utf-8")
        for line in result.splitlines():
            pattern = re.compile(".*crop=([0-9]+):([0-9]+):([0-9]+):([0-9]+)")
            match = pattern.match(line)
            if match:
                d_width, d_height, d_x, d_y = match.groups()
                if s_crop["width"] < int(d_width):
                    s_crop["width"] = int(d_width)

                if s_crop["height"] < int(d_height):
                    s_crop["height"] = int(d_height)

                if s_crop["x"] > int(d_x):
                    s_crop["x"] = int(d_x)

                if s_crop["y"] > int(d_y):
                    s_crop["y"] = int(d_y)

        if s_crop == no_crop and last_crop != no_crop:
            ignore_count += 1
        else:
            if crop["width"] < s_crop["width"]:
                crop["width"] = s_crop["width"]

            if crop["height"] < s_crop["height"]:
                crop["height"] = s_crop["height"]

            if crop["x"] > s_crop["x"]:
                crop["x"] = s_crop["x"]

            if crop["y"] > s_crop["y"]:
                crop["y"] = s_crop["y"]

        last_crop = s_crop.copy()

    if crop == all_crop or ignore_count > 2 or (ignore_count > 0 and (((crop["width"] + 2) == width and crop["height"] == height))):
        crop = no_crop
    
    top = crop["y"]
    bottom = height - top - crop["height"]
    left = crop["x"]
    right = width - left - crop["width"]

    return f"{top}:{bottom}:{left}:{right}"


def detect_interlacing_artefacts(media_info):
    print("Detecting interlacing artefacts...", file=sys.stderr)

    duration = float(media_info["format"]["duration"])
    if duration < 2:
        exit(f"Duration too short: {duration}")

    steps = 10
    interval = int(duration / (steps + 1))
    target_interval = 5 * 60

    if interval == 0:
        steps = 1
        interval = 1
    elif interval > target_interval:
        steps = int((duration / target_interval) - 1)
        interval = int(duration / (steps + 1))

    interlaced_votes = {"yes": 0, "no": 0, "und": 0}

    path = media_info["format"]["filename"]
    for step in range(1, steps + 1):
        position = interval * step
        command = [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-noaccurate_seek",
            "-ss", str(position),
            "-i", path,
            "-frames:v", "100",
            "-filter:v", "idet",
            "-an",
            "-sn",
            "-ignore_unknown",
            "-f", "null",
            "-"
        ]

        result = run(command, stdout=DEVNULL, stderr=PIPE).stderr.decode("utf8")
        for line in result.splitlines():
            pattern = re.compile(".*Multi frame detection:\s*TFF:\s*([0-9]+)\s*BFF:\s*([0-9]+)\s*Progressive:\s*([0-9]+)\s*Undetermined:\s*([0-9]+).*")
            match = pattern.match(line)
            if match:
                tff, bff, prog, und = map(lambda x: int(x), match.groups())
                if (tff > 2*prog and tff > 2* und) or (bff > 2*prog and bff > 2*und):
                    interlaced_votes["yes"] += 1
                elif prog > 2*tff and prog > 2*bff and prog > 2* und:
                    interlaced_votes["no"] +=1
                else:
                    interlaced_votes["und"] += 1
    if interlaced_votes["yes"] > interlaced_votes["no"] + interlaced_votes["und"]:
        return True
    elif interlaced_votes["no"] > interlaced_votes["yes"] + interlaced_votes["und"]:
        return False
    else:
        exit("Unable to determine if input is interlaced")