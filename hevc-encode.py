#!/usr/bin/env python3

import json
import os
import re
import shlex
import shutil
from argparse import ArgumentParser
from collections import defaultdict
from subprocess import DEVNULL, PIPE, Popen, TimeoutExpired, run, CalledProcessError
from sys import exit, stderr


def main():
    parser = ArgumentParser(
        description="Transcode Blu Ray rips into 10-bit HEVC files using HandBrake.",
        usage="%(prog)s FILE [OPTION]...",
        epilog="Requires `HandBrakeCLI`. Uses `mkvpropedit` to add track statistics if found.",
        add_help=False)

    input_options = parser.add_argument_group("Input Options")
    input_options.add_argument("file", metavar="FILE", help="path to source file")

    output_options = parser.add_argument_group("Output Options")
    output_options.add_argument("--dry-run", action="store_true", default=False,
                                help="print `HandBrakeCLI` command and exit")
    output_options.add_argument("--crop", metavar="TOP:BOTTOM:LEFT:RIGHT", default=None, help="set crop geometry")
    output_options.add_argument("--preserve-field-rate", action="store_true",
                                help="Preserve the field rate when deinterlacing")
    output_options.add_argument("--denoise", choices=["ultralight", "light", "medium", "strong"],
                                help="apply de-noising with nlmeans. Only recommended for very grainy sources")
    output_options.add_argument("--tonemap", action="store_true", default=False,
                                help="Add a colourspace filter to tonemap HDR to SDR")
    output_options.add_argument("--1080p", dest="fit_1080", action="store_true", default=False,
                                help="Restrict output to a 1080p frame")
    output_options.add_argument("--vf",  dest="video_format", metavar="FORMAT", choices=["hevc", "avc", "av1"], default="hevc", help="video format used in output. Default: hevc")
    output_options.add_argument("--af", dest="audio_format", metavar="FORMAT", choices=["ac3", "eac3", "aac", "opus", "copy"], default="eac3", help="audio format used in output. Default: eac3. Note: ac3, eac3, aac, and opus are all passed through without transcoding")
    output_options.add_argument("-c", "--container", metavar="CONTAINER", choices=["mp4", "mkv"], default="mkv", help="Container format for output")

    other_options = parser.add_argument_group("Other Options")
    other_options.add_argument("--no-log", dest="log", action="store_false", help="suppress creation of .log file")
    other_options.add_argument("--debug", action="store_true", help="turn on debugging output")
    other_options.add_argument("-h", "--help", action="help", help="print this message and exit")

    args = parser.parse_args()

    transcoder = Transcoder()
    transcoder.dryrun = args.dry_run
    transcoder.crop = args.crop
    transcoder.preserve_field_rate = args.preserve_field_rate
    transcoder.denoise = args.denoise
    transcoder.tonemap = args.tonemap
    transcoder.fit_1080 = args.fit_1080
    transcoder.create_log = args.log
    transcoder.debug = args.debug
    transcoder.video_format = args.video_format
    transcoder.audio_format = args.audio_format
    transcoder.container = args.container
    transcoder.transcode(args.file)


class Transcoder:
    def __init__(self):
        self.dryrun = False
        self.crop = None
        self.preserve_field_rate = False
        self.denoise = None
        self.tonemap = False
        self.fit_1080 = False
        self.create_log = True
        self.video_format = "hevc"
        self.audio_format = "eac3"
        self.container = "mkv"

        self.debug = False

    def transcode(self, input_file):
        if not os.path.exists(input_file):
            exit(f"No such file: {input_file}")

        if os.path.isdir(input_file):
            exit("Folder inputs are not supported")

        output_file = os.path.splitext(os.path.basename(input_file))[0] + f".{self.container}"
        if not self.dryrun and os.path.exists(output_file):
            exit(f"Output file exists: {output_file}")

        self.__check_tools()
        media_info = self.__scan_media(input_file)

        if not self.crop:
            crop_file = os.path.join(os.path.dirname(input_file), "crop.txt")
            if os.path.exists(crop_file):
                with open(crop_file, "r") as f:
                    self.crop = f.readline().strip()

                print("Taking crop from crop.txt")

        command = [
            "HandBrakeCLI",
            "--no-dvdnav",
            "--input", input_file,
            "--output", output_file,
            "--previews", "1",
            "--markers"
        ]

        command += self.__get_picture_args(media_info)
        command += self.__get_video_args(media_info)
        command += self.__get_audio_args(media_info)
        command += self.__get_subtitle_args(media_info)

        print(" ".join(map(lambda x: shlex.quote(x), command)))

        if self.dryrun:
            exit()

        logfile = open(f"{output_file}.log", "wb") if self.create_log else None

        try:
            if logfile:
                logfile.write((" ".join(map(lambda x: shlex.quote(x), command)) + "\n\n").encode("utf-8"))

            with Popen(command, stderr=PIPE) as p:
                for line in p.stderr:
                    stderr.buffer.write(line)
                    stderr.buffer.flush()
                    if logfile:
                        logfile.write(line)
                        logfile.flush()

                try:
                    p.wait()
                    if p.returncode != 0:
                        message = f"Command failed: {command[0]}, exit code: {p.returncode}"
                        print(message)
                        if logfile:
                            logfile.write(f"{message}\n".encode("utf-8"))
                except TimeoutExpired as e:
                    if logfile:
                        logfile.write(f"Encoding failed: {e}\n".encode("utf-8"))
                    exit(f"Encoding failed: {e}")

            if os.path.exists(output_file) and shutil.which("mkvpropedit"):
                try:
                    run(["mkvpropedit", "--add-track-statistics-tags", output_file]).check_returncode()
                except CalledProcessError:
                    pass

        finally:
            if logfile:
                logfile.close()

    def __check_tools(self):
        # Require HandBrake 1.6.1+
        # Allow nightlies, but behaviour with them is undefined

        version_command = ["HandBrakeCLI", "--version"]
        hb_version = run(version_command, stdout=PIPE, stderr=DEVNULL, universal_newlines=True).stdout.removeprefix(
            "HandBrake").strip()
        if self.debug:
            print("HandBrake version line: " + hb_version)

        if re.match("\\d\\.\\d\\.\\d", hb_version):
            major, minor, patch = 1, 6, 1
            hb_major, hb_minor, hb_patch = [int(x) for x in hb_version.split(".")]
            if hb_major > major or (hb_major == major and hb_minor > minor) or (
                    hb_major == major and hb_minor == minor and hb_patch >= patch):
                print(f"Found HandBrake {hb_version}")
            else:
                exit(f"Unsupported version of HandBrake: {hb_version}, requires version >= {major}.{minor}.{patch}")
        elif re.match("\\d{14}-.*", hb_version):
            year, month, day = 2023, 1, 4  # df57d7b5a5d344f6e85cc398ea5c67cf8de9e05c
            hb_year, hb_month, hb_day = int(hb_version[:4]), int(hb_version[4:6]), int(hb_version[6:8])
            if hb_year > year or (hb_year == year and hb_month > month) or (hb_year == year and hb_month == month and hb_day >= day):
                print(f"Found HandBrake {hb_version}")
            else:
                exit(f"Unsupported nightly: {hb_version}, requires builds since {year}-{month}-{day}")
        else:
            print(f"WARN: Unable to check HandBrake version ({hb_version})")

    def __scan_media(self, input_file):
        def basic_scan(previews=10):
            scan_command = ["HandBrakeCLI",
                            "--json",
                            "--scan",
                            "--crop-mode", "conservative",
                            "--previews", str(previews),
                            "--input", input_file]

            command_output = run(scan_command, stdout=PIPE, stderr=PIPE)
            json_scan_result = command_output.stdout.partition(b"JSON Title Set:")[2]

            if self.debug:
                print("Json output: " + json_scan_result.decode())

            if not json_scan_result:
                exit("Scan failed")

            full_media_info = json.loads(json_scan_result)
            main_title = full_media_info["MainFeature"]
            return command_output, full_media_info["TitleList"][main_title]

        hb_scan_info, media_info = basic_scan()
        if self.crop == "auto":
            print("Detecting crop...")
            duration = media_info["Duration"]
            duration = (duration["Hours"] * 60 * 60) + (duration["Minutes"] * 60) + duration["Seconds"]
            num_previews = int(duration / 60 * 5)
            hb_scan_info, media_info = basic_scan(num_previews)

        # Can't trust HandBrake's default InterlaceDetected behaviour, we need to check ourselves
        interlaced = False
        video_line_regex = re.compile(b"^.*?Stream.*?Video.*$", re.MULTILINE)
        regex_result = video_line_regex.search(hb_scan_info.stderr)
        if regex_result:
            start, end = regex_result.span()
            video_line = hb_scan_info.stderr[start:end]
            if self.debug:
                print("Video Line: " + video_line.decode())
            interlaced = b"top first" in video_line or b"bottom first" in video_line
        elif self.debug:
            print("Video line regex didn't find anything")

        if self.debug:
            print(f"Interlace detected: {interlaced}")

        media_info["InterlaceDetected"] = interlaced
        return media_info

    def __get_picture_args(self, media_info):
        if self.crop == "auto":
            crop = ":".join([str(x) for x in media_info["Crop"]])
        elif self.crop:
            crop = self.crop
        else:
            crop = "0:0:0:0"

        picture_args = [
            "--crop", crop,
            "--loose-anamorphic"]

        if self.fit_1080:
            picture_args += [
                "--maxWidth", "1920",
                "--maxHeight", "1080"]

        if media_info["InterlaceDetected"]:
            if self.preserve_field_rate:
                picture_args += ["--bwdif=bob"]
            else:
                picture_args += ["--comb-detect", "--decomb"]

        if self.denoise:
            picture_args += [f"--nlmeans={self.denoise}",
                             "--nlmeans-tune", "film",
                             f"--lapsharp={self.denoise}",
                             "--lapsharp-tune", "film"]

        if self.tonemap:
            picture_args += ["--colorspace", "bt709"]

        return picture_args

    def __get_video_args(self, media_info):
        if self.video_format == "avc":
            return self.__get_avc_args(media_info)
        elif self.video_format == "hevc":
            return self.__get_hevc_args(media_info)
        elif self.video_format == "av1":
            return self.__get_av1_args(media_info)
        else:
            exit(f"Unknown format: {self.video_format}")

    def __get_avc_args(self, media_info):
        geometry = media_info["Geometry"]
        if not self.fit_1080 and (geometry["Width"] > 1920 or geometry["Height"] > 1080):
            level = "5.1" if not self.preserve_field_rate else "5.2"
            bitrate = "12000" if not self.preserve_field_rate else "14000"
        elif geometry["Width"] > 1280 or geometry["Height"] > 720:
            level = "4.0" if not self.preserve_field_rate else "4.2"
            bitrate = "6000" if not self.preserve_field_rate else "7000"
        elif geometry["Width"] * geometry["Height"] > 720 * 576:
            level = "3.1" if not self.preserve_field_rate else "3.2"
            bitrate = "3000" if not self.preserve_field_rate else "3500"
        else:
            level = "3.0" if not self.preserve_field_rate else "3.1"
            bitrate = "1500" if not self.preserve_field_rate else "1750"

        return [
            "--vb", bitrate,
            "--encoder", "x264",
            "--encoder-level", level,
            "--encoder-profile", "high",
            "--encoder-preset", "medium",
            "--encopts", "ratetol=inf:mbtree=0"]

    def __get_hevc_args(self, media_info):
        geometry = media_info["Geometry"]
        if not self.fit_1080 and (geometry["Width"] > 1920 or geometry["Height"] > 1080):
            level = "5.0" if not self.preserve_field_rate else "5.1"
        elif geometry["Width"] > 1280 or geometry["Height"] > 720:
            level = "4.0" if not self.preserve_field_rate else "4.1"
        elif geometry["Width"] * geometry["Height"] > 720 * 576:
            level = "3.1" if not self.preserve_field_rate else "4.0"
        else:
            level = "3.0" if not self.preserve_field_rate else "3.1"

        return [
            "-q", "24",
            "--encoder", "x265_10bit",
            "--encoder-level", level,
            "--encoder-profile", "main10",
            "--encoder-preset", "slow",
            "--encopts", "cutree=0:sao=0:aq-mode=1:rskip=2:rskip-edge-threshold=2"]

    def __get_av1_args(self, media_info):
        geometry = media_info["Geometry"]
        if not self.fit_1080 and (geometry["Width"] > 1920 or geometry["Height"] > 1080):
            level = "5.0" if not self.preserve_field_rate else "5.1"    
        elif geometry["Width"] > 1280 or geometry["Height"] > 720:
            level = "4.0" if not self.preserve_field_rate else "4.1"
        elif geometry["Width"] * geometry["Height"] > 720 * 576:
            level = "3.1" if not self.preserve_field_rate else "4.0"
        else:
            level = "3.0" if not self.preserve_field_rate else "3.1"

        return [
            "-q", "26",
            "--encoder", "svt_av1_10bit",
            "--encoder-level", level,
            "--encoder-profile", "main",
            "--encoder-preset", "6"]

    def __get_audio_args(self, media_info):
        audio_tracks = media_info["AudioList"]
        audio_args = defaultdict(list)

        for audio_track in audio_tracks:
            if self.audio_format == "copy" or audio_track["CodecName"] in ["ac3", "eac3", "aac", "opus"]:
                encoder, bitrate = "copy", ""
            elif self.audio_format == "ac3":
                encoder, bitrate = self.__get_ac3_args(audio_track)
            elif self.audio_format == "eac3":
                encoder, bitrate = self.__get_eac3_args(audio_track)
            elif self.audio_format == "aac":
                encoder, bitrate = self.__get_aac_args(audio_track)
            elif self.audio_format == "opus":
                encoder, bitrate = self.__get_opus_args(audio_track)
            else:
                exit(f"Unknown audio format: {self.audio_format}")

            audio_args["track"].append(str(audio_track["TrackNumber"]))
            audio_args["encoder"].append(encoder)
            audio_args["bitrate"].append(bitrate)

        tracks = ",".join(audio_args["track"])
        encoders = ",".join(audio_args["encoder"])
        bitrates = ",".join(audio_args["bitrate"])

        audio_args = [
            "--audio", tracks,
            "--aencoder", encoders,
            *(["--ab", bitrates] if bitrates else [])]

        return audio_args

    @staticmethod
    def __get_ac3_args(audio_track):
        if audio_track["ChannelCount"] > 2:
            bitrate = "640"
        elif audio_track["ChannelCount"] == 2:
            bitrate = "192"
        else:
            bitrate = "96"

        return "ac3", bitrate

    @staticmethod
    def __get_eac3_args(audio_track):
        if audio_track["ChannelCount"] > 2:
            bitrate = "448"
        elif audio_track["ChannelCount"] == 2:
            bitrate = "160"
        else:
            bitrate = "96"

        return "eac3", bitrate

    @staticmethod
    def __get_aac_args(audio_track):
        handbrake_help = run(["HandBrakeCLI", "--help"], stdout=PIPE, stderr=DEVNULL, universal_newlines=True).stdout
        handbrake_encoders = [x.strip() for x in handbrake_help.partition("Select audio encoder(s):")[2].partition("\"")[0].splitlines()]
        for encoder in ["ca_aac", "fdk_aac", "av_aac"]:
            if encoder in handbrake_encoders:
                aac_encoder = encoder
                break
        else:
            exit("No AAC encoder found")

        if audio_track["ChannelCount"] > 2:
            bitrate = "384"
        elif audio_track["ChannelCount"] == 2:
            bitrate = "128"
        else:
            bitrate = "96"

        return aac_encoder, bitrate

    @staticmethod
    def __get_opus_args(audio_track):
        if audio_track["ChannelCount"] > 2:
            bitrate = "320"
        elif audio_track["ChannelCount"] == 2:
            bitrate = "96"
        else:
            bitrate = "64"

        return "opus", bitrate

    def __get_subtitle_args(self, media_info):
        added_subtitles = []
        forced_subtitle = None
        for subtitle in media_info["SubtitleList"]:
            added_subtitles.append(str(subtitle["TrackNumber"]))
            if not forced_subtitle and subtitle["Attributes"]["Forced"]:
                forced_subtitle = str(subtitle["TrackNumber"])

        if self.container == "mkv" and added_subtitles:
            subtitle_args = [
                "--subtitle", ",".join(added_subtitles),
                "--subtitle-default=none"]

            if forced_subtitle:
                subtitle_args += [f"--subtitle-burned={forced_subtitle}"]
        elif self.container == "mp4" and added_subtitles and forced_subtitle:
            subtitle_args = [
                "--subtitle", forced_subtitle,
                "--subtitle-burned"]
        else:
            subtitle_args = []

        return subtitle_args


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        exit(1)
