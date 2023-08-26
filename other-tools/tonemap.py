#!/usr/bin/env python3
import json
import os
import shlex
from argparse import ArgumentParser
from pprint import pprint
from subprocess import run, PIPE, DEVNULL


# Assume a 4k HDR input
def main():
    parser = ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--debug", action="store_true")

    args = parser.parse_args()

    transcoder = Transcoder()
    transcoder.debug = args.debug
    transcoder.dryrun = args.dry_run

    transcoder.transcode(args.file)


class Transcoder:
    def __init__(self):
        self.debug = False
        self.dryrun = False
        self.crop = None

    def transcode(self, input_file):
        if not os.path.exists(input_file):
            exit(f"No such file: {input_file}")

        if os.path.isdir(input_file):
            exit("Folder inputs are not supported")

        output_file = os.path.splitext(os.path.basename(input_file))[0] + ".mkv"
        if not self.dryrun and os.path.exists(output_file):
            exit(f"Output file exists: {output_file}")

        media_info = self.__scan_media(input_file)

        if self.debug:
            pprint(media_info)

        command = [
            "ffmpeg",
            "-loglevel", "quiet",
            "-stats",
            "-i", input_file,
            *self.__picture_args(media_info),
            *self.__video_args(media_info),
            output_file]

        print(" ".join(map(lambda x: shlex.quote(x), command)))

        if self.dryrun:
            exit()

        run(command)

    @staticmethod
    def __scan_media(input_file):
        command = [
            "ffprobe",
            "-loglevel", "error",
            "-show_streams",
            "-show_format",
            "-show_frames",
            "-read_intervals", "%+#50",
            "-print_format", "json",
            input_file]

        return json.loads(run(command, stdout=PIPE, stderr=DEVNULL).stdout)

    def __picture_args(self, media_info):
        ## filters. Tonemap, crop, scale, overlay?

        first_frame = None
        for frame in media_info["frames"]:
            if frame["media_type"] == "video":
                first_frame = frame
                break

        if not first_frame:
            exit("Unable to read video frame data")

        try:
            signal_peak = int([x for x in first_frame["side_data_list"] if x["side_data_type"] == "Content light level metadata"][0]["max_content"])
            print(signal_peak)
        except:
            signal_peak = None

        if not signal_peak:
            try:
                signal_peak = int([x for x in first_frame["side_data_list"] if x["side_data_type"] == "Mastering display metadata"][0]["max_luminance"])
            except:
                signal_peak = None

        if not signal_peak or signal_peak < 1:
            signal_peak = 1000 if first_frame.get("color_transfer", "") == "smpte2084" else 100

        reference_white = 100
        signal_peak = signal_peak / reference_white

        tonemap_chain = [
            "zscale=transfer=linear:npl=100",
            "format=gbrpf32le",
            "zscale=primaries=bt709",
           f"tonemap=tonemap=hable:desat=0:peak={signal_peak}",
            "zscale=transfer=bt709:matrix=bt709:range=tv",
            "format=yuv420p10le"]

        scale_filter = "scale=1920:-1"

        filter_chain = [
            *tonemap_chain,
            scale_filter]

        return [
            "-vf", ",".join(filter_chain)]

    @staticmethod
    def __video_args(media_info):
        return [
            "-c:v", "libx265",
            "-crf", "24"]


if __name__ == "__main__":
    main()