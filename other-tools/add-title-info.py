#!/usr/bin/env python3

import json
import os.path
from argparse import ArgumentParser


def main():
    parser = ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--playlist", type=int, required=True)
    parser.add_argument("--audio", type=int)
    parser.add_argument("--subtitle", type=int)
    parser.add_argument("--force-subtitle", type=int)
    parser.add_argument("--crop")

    args = parser.parse_args()

    if os.path.exists("title_info.json"):
        with open("title_info.json", "r") as f:
            title_info = json.load(f)
    else:
        title_info = list()

    title = dict()
    title["name"] = args.name
    title["playlist"] = args.playlist
    title["audio"] = args.audio
    title["subtitle"] = args.subtitle
    title["forced_subtitle"] = args.force_subtitle
    title["crop"] = args.crop

    title_info.append(title)

    with open("title_info.json", "w") as f:
        json.dump(title_info, f)

    print("Done.")


if __name__ == "__main__":
    main()
