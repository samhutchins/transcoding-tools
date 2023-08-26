#!/usr/bin/env python3

# https://stackoverflow.com/questions/43650860/pipe-pil-images-to-ffmpeg-stdin-python

import os
import shlex
from argparse import ArgumentParser
from subprocess import Popen, PIPE, run, DEVNULL, CalledProcessError


def main():
    parser = ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("-r", "--frame-rate", type=int, default=25)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--debug", action="store_true")

    args = parser.parse_args()

    stitcher = Stitcher()
    stitcher.dryrun = args.dry_run
    stitcher.debug = args.debug
    stitcher.framerate = args.frame_rate
    stitcher.stitch(args.source)


class Stitcher:
    def __init__(self):
        self.dryrun = False
        self.debug = False
        self.framerate = 25

    def stitch(self, input_folder):
        if not os.path.exists(input_folder):
            exit(f"No such folder: {input_folder}")

        if not os.path.isdir(input_folder):
            exit(f"Input must be a folder")

        output = f"{os.path.basename(os.path.abspath(input_folder))}.mov"
        if not self.dryrun and os.path.exists(output):
            exit(f"Output file exists: {output}")

        self.__check_tools()
        frames: list[str] = self.__scan_media(input_folder)

        if not frames:
            exit("No frames found in input folder")

        self.__log_frames(frames)

        command = ["ffmpeg",
                   "-loglevel", "error",
                   "-stats",
                   "-f", "image2pipe",
                   "-r", str(self.framerate),
                   "-c:v", "mjpeg",
                   "-i", "-",
                   "-c:v", "copy",
                   output]

        print(" ".join(map(lambda x: shlex.quote(x), command)))
        if self.dryrun:
            exit()

        ffmpeg = Popen(command, stdin=PIPE)
        for frame in frames:
            with open(frame, "rb") as f:
                ffmpeg.stdin.write(f.read())

        ffmpeg.stdin.close()
        ffmpeg.wait()

    @staticmethod
    def __check_tools():
        command = ["ffmpeg", "-version"]
        try:
            run(command, stdout=DEVNULL, stderr=DEVNULL).check_returncode()
        except CalledProcessError:
            exit(f"Unable to run ffmpeg")

    def __scan_media(self, input_folder) -> list[str]:
        frames = list[str]()
        for root, dirs, files in os.walk(input_folder):
            dirs.sort()
            for file in sorted(files):
                extension = os.path.splitext(file)[1].lower()
                if extension in [".jpg", ".jpeg"]:
                    frames.append(os.path.join(root, file))
                elif self.debug:
                    print(f"Rejecting {os.path.join(root, file)}")

        return frames

    def __log_frames(self, frames):
        filtered_frames = frames

        if not self.debug and (num_frames := len(frames)) > 5:
            filtered_frames = [frames[0], frames[1], frames[2], "...", frames[num_frames-2], frames[num_frames-1]]

        print("\n".join(filtered_frames))


if __name__ == "__main__":
    main()
