#!/usr/bin/env python3

# rip.py
# requires makemkvcon.exe

import csv
import shlex
from argparse import ArgumentParser
from asyncio.subprocess import DEVNULL, PIPE
from io import StringIO
from subprocess import Popen

TITLE_NAME = 2
DURATION = 9
SIZE = 10
PLAYLIST = 16


def main():
    parser = ArgumentParser()
    parser.add_argument("-d", "--debug", action="store_true")
    subparsers = parser.add_subparsers(required=True)

    list_parser = subparsers.add_parser("scan")
    list_parser.set_defaults(func=_scan_titles)

    rip_parser = subparsers.add_parser("rip")
    rip_parser.add_argument("title")
    rip_parser.set_defaults(func=_rip)

    args = parser.parse_args()
    args.func(args)


def _create_ripper(args):
    ripper = Ripper()
    ripper.debug = args.debug
    return ripper


def _scan_titles(args):
    ripper = _create_ripper(args)
    ripper.scan_titles()


def _rip(args):
    ripper = _create_ripper(args)
    ripper.rip_title(args.title)


class Ripper:
    def __init__(self):
        self.debug = False

    def scan_titles(self):
        command = [
            "makemkvcon", "-r",
            "--progress=-same",
            "info", "disc:0"]

        if self.debug:
            print(" ".join(map(lambda x: shlex.quote(x), command)))

        titles = []
        current_title = None
        with Popen(command, stdout=PIPE, stderr=DEVNULL) as p:
            while True:
                if p.poll() is not None:
                    break

                line = p.stdout.readline().decode().strip()
                if self.debug and line:
                    print(line)

                prefix, _, line = line.partition(":")
                if prefix == "TINFO":
                    title_num, message_type, _, value = [ int(x) if x.isdigit() else x for x in self.csv_split(line) ]
                    if not current_title or current_title.title_num != title_num:
                        current_title = Title(title_num)
                        titles.append(current_title)

                    if message_type == TITLE_NAME:
                        current_title.name = value
                    elif message_type == DURATION:
                        current_title.duration = value
                    elif message_type == SIZE:
                        current_title.size = value
                    elif message_type == PLAYLIST:
                        current_title.playlist = value
                else:
                    self.handle_progress(prefix, line)
            
            print("\n")
            
        for title in titles:
            print(str(title))


    def rip_title(self, title):
        command = [
            "makemkvcon", "-r",
            "--progress=-same",
            "--noscan",
            "mkv",
            "disc:0",
            str(title),
            "."]

        if self.debug:
            print(" ".join(map(lambda x: shlex.quote(x), command)))

        with Popen(command, stdout=PIPE, stderr=DEVNULL) as p:
            while True:
                if p.poll() is not None:
                    break

                line = p.stdout.readline().decode().strip()
                if self.debug and line:
                    print(line)

                prefix, _, line = line.partition(":")
                self.handle_progress(prefix, line)
                
        print("\nDone.")


    def handle_progress(self, prefix, line):
        if prefix in ["PRGC", "PRGT"]:
            _, _, message = self.csv_split(line)
            print(message)
        elif prefix == "PRGV":
            current, _, max = [ int(x) for x in self.csv_split(line) ]
            progress = current / max * 100
            print(f"Progress: {progress:.2f}%", end="\r")


    def csv_split(self, string):
        with StringIO(string) as s:
            reader = csv.reader(s)
            return next(reader)


class Title:
    def __init__(self, title_num):
        self.title_num = title_num
        self.name = None
        self.duration = None
        self.size = None
        self.playlist = None

    def __str__(self):
        return f"Title {self.title_num}:\n  Name: {self.name}\n  Duration: {self.duration}\n  Size: {self.size}\n  Playlist: {self.playlist}\n"
        


if __name__ == "__main__":
    main()