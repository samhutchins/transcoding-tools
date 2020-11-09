#!/usr/bin/env python3

from argparse import ArgumentParser
from os.path import basename
from sys import exit
from subprocess import Popen, PIPE, run, DEVNULL, STDOUT, TimeoutExpired, CalledProcessError
from functools import reduce
from fractions import Fraction
import os
import json
import re
import pprint
import shlex
import sys

version = """\
transcode.py 2020.5
Copyright (c) 2020 Sam Hutchins\
"""

help = f"""\
Transcode Blu Ray and DVD rips to smaller, Plex friendly, versions.

Usage = {basename(__file__)} FILE [OPTION...]

Creates an `mkv` file in the current directory. The video will be converted to
h.264, averaging 8000kb/s. The first audio track will be transcoded with up to
6 channels (5.1) at 640kb/s surround AC3, 192kb/s stereo AAC, or 96kb/s mono
AAC. Any subtitles in the same language as the main audio will be included in
their original format, and forced subtitles will be burned in. If the input is
interlaced it will be deinterlaced, and the video will be cropped automatically
to remove black bars. Track selection, cropping, deinterlacing, and burning can
be controlled by the options documented below.

Input options:
    --scan          scan the input and exit
    --dry-run       print the HandBrakeCLI command and exit
    --position MM:SS
                    The time in the input file to start at

Output option:
    --small         Lower bitrate targets
    --quick         Trade off some quality for more speed

Video options:
    --crop TOP:BOTTOM:LEFT:RIGHT
                    Specify cropping values (default: auto detected)
    --no-crop       Disable cropping
    --deinterlace   Deinterlace the input (default: auto-applied on some inputs)
    --no-deinterlace
                    Disable deinterlacing
    --preserve-field-rate
                    Preserve field rate when deinterlacing. e.g., 50i -> 50p
    --par X:Y       Override the pixel aspect ratio (default: same as input)

Audio options:
    --audio TRACK[ TRACK...]|LANGUAGE[ LANGUAGE...]|all
                    Which audio tracks to include in the output. (default: 1)
    --stereo        Restrict the output to stereo

Subtitle options:
    --burn TRACK    Which subtitle track to burn into the video
                      (default: auto-applied for some inputs)
    --no-burn       Disable burning of subtitles
    --subtitles TRACK[ TRACK...]|LANGUAGE[ LANGUAGE...]|all
                    Which subtitle tracks to include in the output
                      (default: same language as main audio)
    --no-subtitles  Disable added subtitles

Other options:
-d, --debug         print debug information
-h, --help          print this message and exit
    --version       print version information and exit

Requires `HandBrakeCLI`, `ffprobe`, `ffmpeg`, `mkvpropedit`, and `mkvmerge`\
"""

class Transcoder:
    def __init__(self):
        self.dry_run = False
        self.start_time = None
        
        self.small = False
        self.quick = False

        self.crop = "auto"
        self.deinterlace = "auto"
        self.preserve_field_rate = False
        self.par = None

        self.stereo = False
        self.audio = ["1"]

        self.burned_sub = "auto"
        self.subtitles = "auto"

        self.debug = False

    def run(self):
        parser = ArgumentParser(add_help=False)
        parser.add_argument("file", nargs="?")
        parser.add_argument("--scan", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--position", metavar="MM:SS")
        
        parser.add_argument("--small", action="store_true")
        parser.add_argument("--quick", action="store_true")

        parser.add_argument("--crop", metavar="TOP:BOTTOM:LEFT:RIGHT")
        parser.add_argument("--no-crop", action="store_true")
        parser.add_argument("--deinterlace", action="store_true")
        parser.add_argument("--no-deinterlace", action="store_true")
        parser.add_argument("--preserve-field-rate", action="store_true")
        parser.add_argument("--par", metavar="X:Y")

        parser.add_argument("--audio", metavar="TRACK[ TRACK...]|LANGUAGE[ LANGUAGE...]|all", nargs="+")
        parser.add_argument("--stereo", action="store_true")

        parser.add_argument("--burn", metavar="TRACK", type=int)
        parser.add_argument("--no-burn", action="store_true")
        parser.add_argument("--subtitles", metavar="TRACK[ TRACK...]|LANGUAGE[ LANGUAGE...]|all", nargs="+")
        parser.add_argument("--no-subtitles", action="store_true")

        parser.add_argument("-d", "--debug", action="store_true")
        parser.add_argument("-h", "--help", action="store_true")
        parser.add_argument("--version", action="store_true")

        args = parser.parse_args()
        self.validate_args(args)
        self.verify_tools()

        output_file = os.path.splitext(basename(args.file))[0] + ".mkv"
        if not self.dry_run and os.path.exists(output_file):
            exit(f"Output file exists: {output_file}")

        media_info = self.scan_media(args.file)

        if args.scan:
            pprint.pprint(media_info)
            exit()
        
        self.transcode(media_info, output_file)

    def validate_args(self, args):
        if args.version:
            print(version)
            exit()

        if args.help:
            print(help)
            exit()

        if not args.file:
            exit(f"Missing argument: file. Try `{basename(__file__)} --help` for more information")

        if not os.path.exists(args.file):
            exit(f"Input doesn't exist: {args.file}")
        
        if os.path.isdir(args.file):
            exit(f"Input cannot be a directory: {args.file}")

        self.dry_run = args.dry_run

        if args.position:
            pattern = re.compile("([0-9]{1,2}):([0-9]{2})")
            match = pattern.match(args.position)
            if match:
                minutes, seconds = map(lambda x: int(x), match.groups())
                start_time = minutes * 60
                start_time += seconds
                self.start_time = start_time
            else:
                exit(f"Invalid position: {args.position}")

        self.small = args.small
        self.quick = args.quick

        if args.crop:
            if re.match("[0-9]+:[0-9]+:[0-9]+:[0-9]+", args.crop):
                self.crop = args.crop
            else:
                exit(f"Invalid crop geometry: {args.crop}")

        if args.no_crop:
            self.crop = None

        if args.deinterlace:
            self.deinterlace = True
        
        if args.no_deinterlace:
            self.deinterlace = False

        self.preserve_field_rate = args.preserve_field_rate

        if args.par:
            if re.match("[0-9]+:[0-9]+", args.par):
                self.par = args.par
            else:
                exit(f"Invalid aspect ratio: {args.par}")
        
        self.stereo = args.stereo
        
        if args.audio:
            self.audio = []
            for track in args.audio:
                if re.match("[0-9]+|[a-z]{3}", track):
                    self.audio.append(track)
                else:
                    exit(f"Invalid audio track selector: {track}")

        if args.burn:
            self.burned_sub = args.burn

        if args.no_burn:
            self.burned_sub = None

        if args.subtitles:
            self.subtitles = []
            for track in args.subtitles:
                if re.match("[0-9]+|[a-z]{3}", track):
                    self.subtitles.append(track)
                else:
                    exit(f"Invalid subtitle track selector: {track}")

        if args.no_subtitles:
            self.subtitles = []

        self.debug = args.debug


    def transcode(self, media_info, output_file):
        input_file = media_info["filename"]
        command = ["HandBrakeCLI", "--input", input_file, "--output", output_file, "--markers"]
        command += (["--start-at", f"seconds:{self.start_time}"] if self.start_time else [])
        command += self.get_video_args(media_info)
        audio_args, audio_language = self.get_audio_args(media_info)
        command += audio_args
        subtitle_args, added_subs = self.get_subtitle_args(media_info, audio_language)
        command += subtitle_args

        print(" ".join(map(lambda x: shlex.quote(x), command)))
        if self.dry_run:
            exit()
        
        print("Transcoding...")
        log_file = open(f"{output_file}.log", "a")
        self.run_command(command, log_file)

        print("Postprocessing...")
        if added_subs:
            command = ["mkvpropedit", output_file]
            for index in range(len(added_subs)):
                command += ["--edit", f"track:s{index+1}", "--set", "flag-default=0"]
        
            self.run_command(command, log_file)

        os.rename(output_file, "tmp.mkv")
        self.run_command(["mkvmerge", "-o", output_file, "tmp.mkv"], log_file)
        os.remove("tmp.mkv")

        log_file.close()


    def get_video_args(self, media_info):
        args = ["--encoder", "x264"]

        if self.par:
            args += ["--pixel-aspect", self.par]

        if self.small:
            video_bitrates = {"1080p": 6000, "720p": 3000, "sd": 1500}
        else:
            video_bitrates = {"1080p": 8000, "720p": 4000, "sd": 2000}

        if media_info["video"]["width"] > 1280 or media_info["video"]["height"] > 720:
            target_bitrate = video_bitrates["1080p"]
        elif media_info["video"]["width"] * media_info["video"]["height"] > 720 * 576:
            target_bitrate = video_bitrates["720p"]
        else:
            target_bitrate = video_bitrates["sd"]

        args += ["--vb", str(target_bitrate)]

        encoder_options = "ratetol=inf:mbtree=0"
        if self.quick:
            encoder_options += ":analyse=none:ref=1:rc-lookahead=30"

        maxrate = target_bitrate * 3
        bufsize = int(maxrate * 1.25)
        encoder_options += f":vbv-maxrate={maxrate}:vbv-bufsize={bufsize}"

        args += ["--encopts", encoder_options]

        if self.crop:
            args += ["--crop", (media_info["video"]["detected_crop"] if self.crop == "auto" else self.crop)]

        interlacing_args = []
        if self.deinterlace == True or media_info["video"]["stored_interlaced"]:
            if self.preserve_field_rate:
                interlacing_args = ["--deinterlace=bob"]
            else:
                interlacing_args = ["--comb-detect", "--decomb"]

        args += interlacing_args
        
        return args


    def get_audio_args(self, media_info):
        if self.small:
            audio_bitrates = {"surround": 448, "stereo": 160, "mono": 80}
        else:
            audio_bitrates = {"surround": 640, "stereo": 192, "mono": 96}

        selected_tracks = []
        for track in self.audio:
            if re.match("[0-9]+", track):
                selected_tracks.append(int(track))
            elif track == "all":
                selected_tracks = [t["index"] for t in media_info["audio"]]
                break
            else:
                selected_tracks += [t["index"] for t in media_info["audio"] if t["language"] == track]

        selected_tracks = reduce(lambda x,y: x+[y] if not y in x else x, selected_tracks, [])

        args = ["--audio", ",".join(map(lambda x: str(x), selected_tracks))]

        passthrough = ["ac3", "aac"]
        encoders = []
        mixdowns = []
        bitrates = []

        for track in selected_tracks:
            if track > len(media_info["audio"]):
                exit(f"Invalid track index: {track}")
            source_channels = media_info["audio"][track-1]["channels"]
            source_codec = media_info["audio"][track-1]["codec_name"]
            source_bitrate = media_info["audio"][track-1]["bit_rate"]
            source_bitrate = int(source_bitrate) / 1000 if source_bitrate != "unknown" else sys.maxsize

            if self.stereo:
                if source_channels <= 2 and source_codec in passthrough and source_bitrate <= audio_bitrates["stereo"]:
                    encoders.append("copy")
                    mixdowns.append("")
                    bitrates.append("")
                else:
                    if source_channels > 2:
                        mixdowns.append("stereo")
                    else:
                        mixdowns.append("")
                    
                    encoders.append("fdk_aac")
                    bitrates.append(str(audio_bitrates["stereo"] if source_channels >= 2 else audio_bitrates["mono"]))
            else:
                if source_channels > 2:
                    key = "surround"
                elif source_channels == 2:
                    key = "stereo"
                else:
                    key = "mono"

                if source_codec in passthrough and source_bitrate <= audio_bitrates[key]:
                    encoders.append("copy")
                    mixdowns.append("")
                    bitrates.append("")
                else:
                    if source_channels > 2:
                        encoders.append("ac3")
                    else:
                        encoders.append("fdk_aac")
                    mixdowns.append("")
                    bitrates.append(str(audio_bitrates[key]))

        args += ["--aencoder", ",".join(encoders)]
        for mixdown in mixdowns:
            if mixdown:
                args += ["--mixdown", ",".join(mixdowns)]
                break

        for bitrate in bitrates:
            if bitrate:
                args += ["--ab", ",".join(bitrates)]
                break

        return args, media_info["audio"][selected_tracks[0]-1]["language"]


    def get_subtitle_args(self, media_info, audio_language):
        selected_tracks = []
        if self.subtitles == "auto":
            selected_tracks += [t["index"] for t in media_info["subtitles"] if t["language"] == audio_language]
        else:
            for track in self.subtitles:
                if re.match("[0-9]+", track):
                    selected_tracks.append(int(track))
                elif track == "all":
                    selected_tracks = [t["index"] for t in media_info["audio"]]
                    break
                else:
                    selected_tracks += [t["index"] for t in media_info["subtitles"] if t["language"] == track]

        burned_track = None
        if self.burned_sub == "auto":
            for sub in media_info["subtitles"]:
                if sub["forced"]:
                    if burned_track:
                        exit("Multiple forced subtitle tracks detected")
                    burned_track = sub["index"]
        elif self.burned_sub:
            burned_track = self.burned_sub

        if burned_track:
            selected_tracks.insert(0, burned_track)

        selected_tracks = reduce(lambda x,y: x+[y] if not y in x else x, selected_tracks, [])

        args = []
        if selected_tracks:
            args += ["--subtitle", ",".join(map(lambda x: str(x), selected_tracks))]

        if burned_track:
            args += ["--subtitle-burned"]
            selected_tracks.remove(burned_track)

        return args, selected_tracks


    def run_command(self, command, log_file):
        cmd_string = " ".join(map(lambda x: shlex.quote(x), command))
        log_file.write(cmd_string + "\n")
        with Popen(command, stdout=PIPE, stderr=STDOUT, bufsize=1, universal_newlines=True) as p:
            for line in p.stdout:
                if line.startswith("Encoding:"):
                    print(line.strip(), end='\r')
                elif line.startswith("Progress:"):
                    print(line.strip(), end="\r")
                else:
                    log_file.write(line)
                    log_file.flush()
            
            try:
                if returncode := p.wait() != 0:
                    raise CalledProcessError(returncode, cmd_string)
            except (TimeoutExpired, CalledProcessError) as e:
                log_file.write(f"Encoding failed: {e}\n")
                exit(f"Encoding failed: {e}")


    def verify_tools(self):
        print("Verifying tools...")
        commands = [
            ["ffprobe", "-version"],
            ["HandBrakeCLI", "--version"],
            ["mkvpropedit", "--version"],
            ["ffmpeg", "-version"],
            ["mkvmerge", "--version"]
        ]

        for command in commands:
            try:
                run(command, stdout=DEVNULL, stderr=DEVNULL).check_returncode()
            except:
                exit(f"`{command[0]}` not found")


    def scan_media(self, file):
        print("Scanning input...")
        command = [
            "ffprobe",
            "-loglevel", "quiet",
            "-show_format",
            "-show_streams",
            "-print_format", "json",
            file
        ]

        output = run(command, stdout=PIPE, stderr=DEVNULL).stdout
        ffprobe_result = json.loads(output)

        if self.debug:
            print(ffprobe_result)

        if self.crop and self.crop == "auto":
            detected_crop = self.detect_crop(ffprobe_result)
        else:
            detected_crop = "unknown"

        filename = ffprobe_result["format"]["filename"]
        video = [{"width": s["width"], "height": s["height"], "stored_interlaced": s.get("field_order", "progressive") != "progressive", "detected_crop": detected_crop, "fps": float(Fraction(s["avg_frame_rate"]))} for s in ffprobe_result["streams"] if s["codec_type"] == "video"][0]
        audio = [{"channels": s["channels"], "codec_name": s["codec_name"], "bit_rate": s.get("bit_rate", "unknown"), "index": s["index"], "language": s.get("tags", {}).get("language", "und")} for s in ffprobe_result["streams"] if s["codec_type"] == "audio"]
        audio.sort(key=lambda a: a["index"])
        for i, a in enumerate(audio):
            a["index"] = i+1
        subtitles = [{"language": s.get("tags", {}).get("language", "und"), "forced": s["disposition"]["forced"], "index": s["index"]} for s in ffprobe_result["streams"] if s["codec_type"] == "subtitle"]
        subtitles.sort(key=lambda s: s["index"])
        for i, s in enumerate(subtitles):
            s["index"] = i+1

        media_info = {
            "filename": filename,
            "video": video,
            "audio": audio,
            "subtitles": subtitles
        }

        return media_info


    # This algorithm is shamelessly taken from Don Melton's `other_video_transcoding` project: 
    # https://github.com/donmelton/other_video_transcoding
    def detect_crop(self, ffprobe_result):
        print("Detecting crop...")
        duration = float(ffprobe_result["format"]["duration"])
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

        if self.debug:
            print(f"Duration: {duration}. Steps: {steps}. Interval: {interval}.")

        video = [s for s in ffprobe_result["streams"] if s["codec_type"] == "video"][0]
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

        path = ffprobe_result["format"]["filename"]

        for step in range(1, steps + 1):
            s_crop = all_crop.copy()
            position = interval * step
            if self.debug:
                print(f"crop = {crop}")
                print(f"step = {step}. position = {position}")

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

                    if self.debug:
                        print(line)

            if s_crop == no_crop and last_crop != no_crop:
                ignore_count += 1
                if self.debug:
                    print(f"Ignore crop: {s_crop}")
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

        if self.debug:
            print(f"Ingore count: {ignore_count}")

        if crop == all_crop or ignore_count > 2 or (ignore_count > 0 and (((crop["width"] + 2) == width and crop["height"] == height))):
            crop = no_crop
        
        top = crop["y"]
        bottom = height - top - crop["height"]
        left = crop["x"]
        right = width - left - crop["width"]

        return f"{top}:{bottom}:{left}:{right}"


if __name__ == "__main__":
    Transcoder().run()