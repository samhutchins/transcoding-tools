#!/usr/bin/env python3
# detect-crop.py
# requires ffprobe, ffmpeg, and mpv

from argparse import ArgumentParser
from subprocess import run, DEVNULL, PIPE
import json
import re
import os
from pathlib import Path

def main():
    parser = ArgumentParser()
    parser.add_argument("file")

    args = parser.parse_args()

    detector = CropDetector()
    crop = detector.detect_crop(args.file)

    mpv_command = [
        "mpv",
        "--no-audio",
        f"--vf=lavfi=[drawbox={crop.get_mpv_crop()}:invert:1]"]

    if args.file.endswith(".mpls"):
        input_folder = Path(args.file).parent.parent.parent
        playlist = int(os.path.splitext(os.path.basename(args.file))[0])
        mpv_command += [
            f"bd://mpls/{playlist}",
            f"--bluray-device={input_folder}"]
    else:
        mpv_command += [args.file]

    run(mpv_command, stdout=DEVNULL, stderr=DEVNULL)

    if args.file.endswith(".mpls"):
        print(crop.get_handbrake_crop())
    else:
        if not os.path.exists("crop.txt"):
            with open("crop.txt", "w") as f:
                f.write(crop.get_handbrake_crop())
        else:
            print(f"crop.txt already exists. Detected crop: {crop.get_handbrake_crop()}")


class CropDetector:
    def detect_crop(self, file):
        if not os.path.exists(file):
            exit(f"No such file: {file}")

        if os.path.isdir(file):
            exit("Folder inputs are not supported")

        self.__verify_tools()
        media_info = self.__scan_media(file)

        # This algorithm is shamelessly taken from Lisa Melton's `other_video_transcoding` project: 
        # https://github.com/lisamelton/other_video_transcoding
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
        if path.startswith("bluray:"):
            playlist = int(os.path.splitext(os.path.basename(file))[0])

        for step in range(1, steps + 1):
            s_crop = all_crop.copy()
            position = interval * step

            # ffmpeg ... -playlist <number> -i bluray:// ...
            command = [
                "ffmpeg",
                "-hide_banner",
                "-nostdin",
                "-noaccurate_seek",
                "-ss", str(position),
                *(["-playlist", str(playlist)] if path.startswith("bluray") else []),
                "-i", path,
                "-frames:v", "15",
                "-filter:v", "cropdetect=24.0/255:2",
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

        return Crop(width, height, crop["width"], crop["height"], crop["x"], crop["y"])

    def __verify_tools(self):
        commands = [
            ["ffprobe", "-version"],
            ["ffmpeg", "-version"],
            ["mpv", "-version"]
        ]

        for command in commands:
            try:
                run(command, stdout=DEVNULL, stderr=DEVNULL).check_returncode()
            except:
                exit(f"Unable to run {command[0]}")

    def __scan_media(self, input_file):
        command = [
            "ffprobe",
            "-loglevel", "quiet",
            "-show_streams",
            "-show_format",
            "-print_format", "json"
        ]

        if input_file.endswith(".mpls"):
            input_folder = Path(input_file).parent.parent.parent
            playlist = int(os.path.splitext(os.path.basename(input_file))[0])
            
            command += [
                "-playlist", str(playlist),
                f"bluray:{input_folder}"
            ]
        else:
            command += [
                input_file
            ]

        output = run(command, stdout=PIPE, stderr=DEVNULL).stdout
        return json.loads(output)


class Crop:
    def __init__(self, video_width, video_height, crop_width, crop_height, crop_x, crop_y):
        self.video_width = video_width
        self.video_height = video_height
        self.crop_width = crop_width
        self.crop_height = crop_height
        self.crop_x = crop_x
        self.crop_y = crop_y

    def get_handbrake_crop(self):
        top = self.crop_y
        bottom = self.video_height - top - self.crop_height
        left = self.crop_x
        right = self.video_width - left - self.crop_width
        return f"{top}:{bottom}:{left}:{right}"

    def get_mpv_crop(self):
        return f"{self.crop_x}:{self.crop_y}:{self.crop_width}:{self.crop_height}"


if __name__ == "__main__":
    main()
    