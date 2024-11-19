#!/usr/bin/env python3


# makemkvcon backup --decrypt --noscan -r --progress=-same disc:/dev/sr1 bar
# genisoimage -allow-limited-size -quiet -V "Ant Man" -o Ant\ Man.iso bar

# is there any benefit to making an ISO out of this?

from argparse import ArgumentParser
from subprocess import Popen, PIPE, DEVNULL, run
from io import StringIO
import csv
import shlex
import sys

def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("source", nargs="?", default="0")
    parser.add_argument("--dvd", action="store_true")

    args = parser.parse_args()

    ripper = Ripper()
    ripper.backup(args.source, args.dvd)


class Ripper:
    def backup(self, device: str, dvd: bool = False) -> None:
        filename = self.__get_filename(device, dvd)

        command = [
            "makemkvcon",
            "backup",
            "--noscan",
            "--decrypt",
            "-r",
            "--progress=-same",
            f"disc:{device}",
            f"./{filename}"
        ]

        print(" ".join(map(lambda x: shlex.quote(x), command)))

        with Popen(command, stdout=PIPE, stderr=DEVNULL) as p:
            while True:
                if p.poll() is not None:
                    break

                if p.stdout:
                    line = p.stdout.readline().decode().strip()
                    prefix, _, line = line.partition(":")
                    self.__handle_progress(prefix, line)
                
        print("\nDone.")

    def __get_filename(self, device: str, dvd: bool) -> str:
        command = ["makemkvcon", "-r", "info", "disc:9999"]
        command_output = run(command, stdout=PIPE, stderr=DEVNULL).stdout.decode()

        for line in command_output.splitlines():
            if line.startswith(f"DRV:{device}"):
                filename = self.__csv_split(line)[5]
                if dvd:
                    filename += ".iso"
                
                return filename
        else:
            exit("Dang")

    def __handle_progress(self, prefix, line):
        if prefix == "PRGT":
            _, _, message = self.__csv_split(line)
            print(message)
        elif prefix == "PRGV":
            _, total, max = [ int(x) for x in self.__csv_split(line) ]
            progress = total / max * 100
            print(f"Progress: {progress:.2f}%", end="\r")
    
    def __csv_split(self, string):
        with StringIO(string) as s:
            reader = csv.reader(s)
            return next(reader)


if __name__ == "__main__":
    main()