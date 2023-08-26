#!/usr/bin/env python3

import os
from argparse import ArgumentParser
from contextlib import contextmanager
from subprocess import run


def main():
    parser = ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("-c", default="hevc-encode")

    args, other_args = parser.parse_known_args()

    if not os.path.isdir(args.directory):
        print("Not a folder")
        exit()

    transcode_folder(os.path.abspath(args.directory), args.c, other_args)


def transcode_folder(full_folder_path, command, args):
    relative_folder_path = os.path.basename(os.path.normpath(full_folder_path))

    if not os.path.exists(relative_folder_path):
        os.mkdir(relative_folder_path)

    with pushd(relative_folder_path):
        for item in os.listdir(full_folder_path):
            item_path = os.path.join(full_folder_path, item)
            if os.path.isdir(item_path):
                transcode_folder(item_path, command, args)
            elif os.path.isfile(item_path) and item_path.endswith(".mkv") and not os.path.exists(item):
                run([command, item_path, *args], shell=True).check_returncode()



@contextmanager
def pushd(new_dir):
    previous_dir = os.getcwd()
    os.chdir(new_dir)
    try:
        yield
    finally:
        os.chdir(previous_dir)


if __name__ == "__main__":
    main()