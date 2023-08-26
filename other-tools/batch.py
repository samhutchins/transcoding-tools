#!/usr/bin/env python3

from argparse import ArgumentParser
from subprocess import run

parser = ArgumentParser()
parser.add_argument("queue")

args, other_args = parser.parse_known_args()

while True:
    with open(args.queue, "r") as queue:
        items = queue.readlines()

    if items:
        item = items[0].strip()

    if not item or not items:
        break

    command = ["hevc-encode", item, *other_args]
    run(command, shell=True).check_returncode()

    with open(args.queue, "r") as queue:
        items = queue.readlines()

    if items and items[0].strip() == item:
        items = items[1:]

    with open(args.queue, "w") as queue:
        queue.writelines(items)