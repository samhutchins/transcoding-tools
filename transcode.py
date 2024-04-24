#!/usr/bin/env python3

import json
import os
import re
import shlex
import shutil
from argparse import ArgumentParser
from subprocess import DEVNULL, PIPE, Popen, run
from sys import exit, stderr
from pathlib import Path


def main():
    parser = ArgumentParser(
        description="Transcode Blu Ray rips into 10-bit HEVC files using HandBrake.",
        usage="%(prog)s FILE [OPTION]...",
        epilog="Requires `HandBrakeCLI`. Uses `mkvpropedit` to add track statistics if found.",
        add_help=False)

    input_options = parser.add_argument_group("Input Options")
    input_options.add_argument("file", metavar="FILE", help="path to a source file")
    input_options.add_argument("-a", "--audio", nargs="+", type=int, help="Select audio tracks. Default: all tracks")
    input_options.add_argument("-s", "--subtitle", nargs="+", type=int, help="Select subtitle tracks. Default: all tracks")
    input_options.add_argument("-f", "--force-subtitle", type=int, help="Force (burn) a subtitle track. Default: based on input")

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
    output_options.add_argument("--af", dest="audio_format", metavar="FORMAT", choices=["ac3", "eac3", "aac", "opus", "copy"], default="aac", help="audio format used in output. Default: eac3. Note: ac3, eac3, aac, and opus are all passed through without transcoding")

    other_options = parser.add_argument_group("Other Options")
    other_options.add_argument("--debug", action="store_true", help="turn on debugging output")
    other_options.add_argument("-h", "--help", action="help", help="print this message and exit")

    args = parser.parse_args()

    if os.path.basename(args.file) == "title_info.json":
        with open(args.file, "r") as f:
            title_info = json.load(f)

        for title in title_info:
            transcoder = __create_transcoder(args)
            transcoder.output_name = title["name"]
            if not args.audio:
                transcoder.audio = title["audio"]
            
            if not args.subtitle:
                transcoder.subtitle = title["subtitle"]

            if not args.force_subtitle:
                transcoder.forced_subtitle = title["forced_subtitle"]

            if not args.crop:
                transcoder.crop = title["crop"]

            input_file = Path(args.file).parent / "BDMV" / "PLAYLIST" / f"{title['playlist']:05}.mpls"
            transcoder.transcode(str(input_file))
    else:
        transcoder = __create_transcoder(args)
        transcoder.transcode(args.file)


def __create_transcoder(args):
    transcoder = Transcoder()
    transcoder.audio = args.audio
    transcoder.subtitle = args.subtitle
    transcoder.forced_subtitle = args.force_subtitle
    transcoder.dryrun = args.dry_run
    transcoder.crop = args.crop
    transcoder.preserve_field_rate = args.preserve_field_rate
    transcoder.denoise = args.denoise
    transcoder.tonemap = args.tonemap
    transcoder.fit_1080 = args.fit_1080
    transcoder.debug = args.debug
    transcoder.video_format = args.video_format
    transcoder.audio_format = args.audio_format

    return transcoder


class Transcoder:
    def __init__(self):
        self.output_name = None
        self.audio = None
        self.subtitle = None
        self.forced_subtitle = None
        self.dryrun = False
        self.crop = None
        self.preserve_field_rate = False
        self.denoise = None
        self.tonemap = False
        self.fit_1080 = False
        self.video_format = "hevc"
        self.audio_format = "aac"

        self.debug = False

    def transcode(self, input_file):
        if not os.path.exists(input_file):
            exit(f"No such file: {input_file}")

        if os.path.isdir(input_file):
            exit("Folder inputs are not supported")

        if self.output_name:
            output_file = f"{self.output_name}.mkv"
        else:
            output_file = os.path.splitext(os.path.basename(input_file))[0] + ".mkv"
        
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
            "--output", output_file,
            "--previews", "1",
            "--markers"
        ]

        if input_file.endswith(".mpls"):
            input_folder = Path(input_file).parent.parent.parent
            title = self.__get_handbrake_title(input_file)
            command += [
                "--input", str(input_folder),
                "-t", str(title)]
        else:
            command += ["--input", input_file]

        command += self.__get_picture_args(media_info)
        command += self.__get_video_args(media_info)
        audio_args, audio_lang = self.__get_audio_args(media_info)
        command += audio_args
        command += self.__get_subtitle_args(media_info, audio_lang)

        print(" ".join(map(lambda x: shlex.quote(x), command)))

        if self.dryrun:
            return

        with open(f"{output_file}.log", "wb+") as logfile:
            self.__run_handbrake(media_info, command, output_file, logfile)
            self.__run_mkvpropedit(output_file)

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
        if input_file.endswith(".mpls"):
            input_folder = Path(input_file).parent.parent.parent
            title = self.__get_handbrake_title(input_file)

        def basic_scan(previews=10):
            scan_command = ["HandBrakeCLI",
                            "--json",
                            "--scan",
                            "--crop-mode", "conservative",
                            "--previews", str(previews)]
            
            if input_file.endswith(".mpls"):
                scan_command += [
                    "-t", str(title),
                    "--input", input_folder]
            else:
                scan_command += ["--input", input_file]

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
            duration = self.__get_duration_seconds(media_info)
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

    def __get_handbrake_title(self, playlist_file):
        input_folder = Path(playlist_file).parent.parent.parent
        playlist_file = os.path.basename(playlist_file)

        command = [
            "HandBrakeCLI",
            "--scan",
            "-t", "0",
            "--min-duration", "9000",  # large number to stop HandBrake from _actually_ scanning anything
            "--input", input_folder
        ]

        command_output = run(command, stdout=DEVNULL, stderr=PIPE).stderr.splitlines()

        index = 0
        for line in command_output:
            if playlist_file.upper().encode() in line:
                index = index - 1
                break
            
            index += 1
        else:
            exit("Can't find playlist in HandBrake scan")

        return int(command_output[index].split(b' ')[-1])

    def __get_duration_seconds(self, media_info):
        duration = media_info["Duration"]
        return (duration["Hours"] * 60 * 60) + (duration["Minutes"] * 60) + duration["Seconds"]

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
            "-q", "24",
            "--encoder", "svt_av1_10bit",
            "--encoder-level", level,
            "--encoder-profile", "main",
            "--encoder-preset", "5",
            "--encopts", "enable-qm=1:qm-min=0"]

    def __get_audio_args(self, media_info):
        audio_tracks = media_info["AudioList"]

        if audio_tracks:
            audio_track_index = self.audio if self.audio else 1
            selected_audio_track = audio_tracks[audio_track_index - 1]
            language = selected_audio_track["LanguageCode"]
            if self.audio_format == "copy" or selected_audio_track["CodecName"] in ["ac3", "eac3", "aac", "opus"]:
                encoder, bitrate, quality = "copy", "", ""
            elif self.audio_format == "ac3":
                encoder, bitrate, quality = self.__get_ac3_args(selected_audio_track)
            elif self.audio_format == "eac3":
                encoder, bitrate, quality = self.__get_eac3_args(selected_audio_track)
            elif self.audio_format == "aac":
                encoder, bitrate, quality = self.__get_aac_args()
            elif self.audio_format == "opus":
                encoder, bitrate, quality = self.__get_opus_args(selected_audio_track)
            else:
                exit(f"Unknown audio format: {self.audio_format}")

            audio_args = [
                "--audio", str(selected_audio_track["TrackNumber"]),
                "--aencoder", encoder]

            if quality:
                audio_args += [
                    "--aq", quality]
            elif bitrate:
                audio_args += [
                    "--ab", bitrate]
        else:
            audio_args = []
            language = None

        return audio_args, language

    @staticmethod
    def __get_ac3_args(audio_track):
        if audio_track["ChannelCount"] > 2:
            bitrate = "640"
        elif audio_track["ChannelCount"] == 2:
            bitrate = "192"
        else:
            bitrate = "96"

        return "ac3", bitrate, None

    @staticmethod
    def __get_eac3_args(audio_track):
        if audio_track["ChannelCount"] > 2:
            bitrate = "448"
        elif audio_track["ChannelCount"] == 2:
            bitrate = "160"
        else:
            bitrate = "96"

        return "eac3", bitrate, None

    @staticmethod
    def __get_aac_args():
        handbrake_help = run(["HandBrakeCLI", "--help"], stdout=PIPE, stderr=DEVNULL, universal_newlines=True).stdout
        handbrake_encoders = [x.strip() for x in handbrake_help.partition("Select audio encoder(s):")[2].partition("\"")[0].splitlines()]
        for encoder in ["ca_aac", "fdk_aac", "av_aac"]:
            if encoder in handbrake_encoders:
                aac_encoder = encoder
                break
        else:
            exit("No AAC encoder found")

        if aac_encoder == "ca_aac":
            quality = "90"
        else:
            quality = "4"

        return aac_encoder, None, quality

    @staticmethod
    def __get_opus_args(audio_track):
        return "opus", str(64 * audio_track["ChannelCount"]), None

    def __get_subtitle_args(self, media_info, audio_lang):
        subtitle_tracks = media_info["SubtitleList"]

        def find_forced_subtitle():
            if self.forced_subtitle:
                return self.forced_subtitle

            for track in subtitle_tracks:
                if track["Attributes"]["Forced"]:
                    return track["TrackNumber"]

            if audio_lang != "eng":
                for track in subtitle_tracks:
                    if track["LanguageCode"] == "eng":
                        return track["TrackNumber"]

            return None

        def find_added_subtitle():
            if self.subtitle:
                return self.subtitle

            for track in subtitle_tracks:
                if track["LanguageCode"] == "eng":
                    return track["TrackNumber"]

            return None

        forced_subtitle = find_forced_subtitle()
        print(forced_subtitle)
        added_subtitle = find_added_subtitle()

        subtitles = []
        if forced_subtitle:
            subtitles.append(forced_subtitle)

        if added_subtitle and added_subtitle != forced_subtitle:
            subtitles.append(added_subtitle)

            if not forced_subtitle:
                subtitles.append(added_subtitle)

        subtitle_args = []

        if subtitles:
            subtitle_args += ["--subtitle", ",".join(map(str, subtitles)), "--subtitle-default=none"]
            if len(subtitles) == 2 or forced_subtitle:
                subtitle_args.append("--subtitle-burned")

            if len(subtitles) == 2 and not forced_subtitle:
                # this makes HandBrake filter the subtitle track to only include forced subsections
                subtitle_args.append("--subtitle-forced")

        return subtitle_args
    
    def __run_handbrake(self, media_info, command, output_file, logfile):
        logfile.write((" ".join(map(lambda x: shlex.quote(x), command)) + "\n\n").encode("utf-8"))

        with Popen(command, stderr=PIPE) as p:
            last_line = None
            for line in p.stderr:
                last_line = line
                stderr.buffer.write(line)
                stderr.buffer.flush()
                logfile.write(line)
                logfile.flush()
            
            p.wait()
            clean_exit = b"HandBrake has exited.\n" == last_line
            if not clean_exit or p.returncode != 0:
                message = f"\nCommand failed: {command[0]}, exit code: {p.returncode}, clean exit: {clean_exit}"
                print(message)
                logfile.write(f"{message}\n".encode("utf-8"))
                exit(1) 
        
        media_info_out = self.__scan_media(output_file)
        input_duration = self.__get_duration_seconds(media_info)
        output_duration = self.__get_duration_seconds(media_info_out)

        if input_duration != output_duration:
            print(f"WARNING: Output file duration doesn't match input file duration. {input_duration} vs {output_duration}")

    @staticmethod
    def __run_mkvpropedit(output_file):
        if os.path.exists(output_file) and shutil.which("mkvpropedit"):
            run(["mkvpropedit", "--add-track-statistics-tags", output_file])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        exit(1)
