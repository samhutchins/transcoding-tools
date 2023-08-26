#!/usr/bin/env python3

import json
import os
import re
import shlex
from argparse import ArgumentParser
from subprocess import PIPE, Popen, TimeoutExpired, run, CalledProcessError
from sys import exit, stdout


def main():
    parser = ArgumentParser(
        description="Test encoders in HandBrake",
        usage="%(prog)s FILE [OPTION]...",
        epilog="Requires `HandBrakeCLI`. Uses `mkvpropedit` to add track statistics if found.",
        add_help=False)

    input_options = parser.add_argument_group("Input Options")
    input_options.add_argument("file", metavar="FILE", help="path to source file")

    output_options = parser.add_argument_group("Output Options")
    output_options.add_argument("-o", "--output", metavar="FILE", type=str, required=True)
    output_options.add_argument("--dry-run", action="store_true", default=False,
                                help="print `HandBrakeCLI` command and exit")
    output_options.add_argument("--crop", metavar="TOP:BOTTOM:LEFT:RIGHT", default=None, help="set crop geometry")
    output_options.add_argument("--preserve-field-rate", action="store_true",
                                help="Preserve the field rate when deinterlacing")

    other_options = parser.add_argument_group("Other Options")
    other_options.add_argument("-h", "--help", action="help", help="print this message and exit")

    args, video_args = parser.parse_known_args()

    transcoder = Transcoder()
    transcoder.crop = args.crop
    transcoder.preserve_field_rate = args.preserve_field_rate
    transcoder.dryrun = args.dry_run
    transcoder.video_args = video_args
    transcoder.transcode(args.file, args.output)


class Transcoder:
    def __init__(self):
        self.dryrun = False
        self.crop = None
        self.preserve_field_rate = False
        self.video_args = []

    def transcode(self, input_file, output_file):
        if not os.path.exists(input_file):
            exit(f"No such file: {input_file}")

        if os.path.isdir(input_file):
            exit("Folder inputs are not supported")

        output_file = os.path.splitext(output_file)[0] + ".mkv"
        if not self.dryrun and os.path.exists(output_file):
            exit(f"Output file exists: {output_file}")

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
        command += self.__get_audio_args(media_info)
        command += self.__get_subtitle_args(media_info)
        command += self.video_args

        print(" ".join(map(lambda x: shlex.quote(x), command)))

        if self.dryrun:
            exit()

        with open(f"{output_file}.log", "wb") as logfile:
            logfile.write((" ".join(map(lambda x: shlex.quote(x), command)) + "\n\n").encode("utf-8"))

            with Popen(command, stderr=PIPE) as p:
                for line in p.stderr:
                    stdout.buffer.write(line)
                    stdout.buffer.flush()
                    logfile.write(line)
                    logfile.flush()

                try:
                    p.wait()
                    if p.returncode != 0:
                        message = f"Command failed: {command[0]}, exit code: {p.returncode}"
                        print(message)
                        logfile.write(f"{message}\n".encode("utf-8"))
                except TimeoutExpired as e:
                    logfile.write(f"Encoding failed: {e}\n".encode("utf-8"))
                    exit(f"Encoding failed: {e}")

            if os.path.exists(output_file):
                try:
                    run(["mkvpropedit", "--add-track-statistics-tags", output_file]).check_returncode()
                except CalledProcessError:
                    pass

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
            interlaced = b"top first" in video_line or b"bottom first" in video_line

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
            "--non-anamorphic",
            "--maxWidth", "1920",
            "--maxHeight", "1080"]

        if media_info["InterlaceDetected"]:
            if self.preserve_field_rate:
                picture_args += ["--bwdif=bob"]
            else:
                picture_args += ["--comb-detect", "--decomb"]

        return picture_args

    def __get_audio_args(self, media_info):
        audio_track = media_info["AudioList"][0]
        audio_args = ["--audio", str(audio_track["TrackNumber"])]

        if audio_track["CodecName"] in ["ac3", "eac3", "aac", "opus"]:
            audio_args += ["--aencoder", "copy"]
        else:
            audio_args += self.__get_eac3_args(audio_track)

        return audio_args

    @staticmethod
    def __get_eac3_args(audio_track):
        if audio_track["ChannelCount"] > 2:
            bitrate = "448"
        elif audio_track["ChannelCount"] == 2:
            bitrate = "160"
        else:
            bitrate = "96"

        return [
            "--aencoder", "eac3",
            "--ab", bitrate]

    @staticmethod
    def __get_subtitle_args(media_info):
        added_subtitles = []
        forced_subtitle = None
        for subtitle in media_info["SubtitleList"]:
            added_subtitles.append(str(subtitle["TrackNumber"]))
            if not forced_subtitle and subtitle["Attributes"]["Forced"]:
                forced_subtitle = str(subtitle["TrackNumber"])

        if added_subtitles:
            subtitle_args = [
                "--subtitle", ",".join(added_subtitles),
                "--subtitle-default=none"]

            if forced_subtitle:
                subtitle_args += [f"--subtitle-burned={forced_subtitle}"]
        else:
            subtitle_args = []

        return subtitle_args


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        exit(1)
