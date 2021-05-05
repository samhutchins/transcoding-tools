from argparse import ArgumentParser
from subprocess import run
from . import utils

def main():
    parser = ArgumentParser()
    parser.add_argument("file")
    
    args = parser.parse_args()

    media_info = utils.scan_media(args.file)
    subtitles = [s["index"] for s in utils.get_subtitle_streams(media_info) if s["codec_name"] == "hdmv_pgs_subtitle"]
    if not subtitles:
        print("No subtitles to convert!")
        exit()

    print("Extracting subtitles")
    command = ["mkvextract", args.file, "tracks"]
    for sub in subtitles:
        command.append(f"{sub}:{sub}.sup")

    run(command)

    print("Converting subtitles")
    for sub in subtitles:
        command = ["bdsup2sub.bat", f"{sub}.sup", "-o", f"{sub}.sub"]
        run(command)


    print("Muxing together")
    subtitle_tracks = [s["index"] for s in utils.get_subtitle_streams(media_info) if s["index"] not in subtitles]
    command = ["mkvmerge", "-o", "tmp.mkv"]
    if subtitle_tracks:
        command += ["--subtitle-tracks", ",".join(subtitle_tracks)]
    else:
        command += ["--no-subtitles"]
    command += [args.file]

    for sub in subtitles:
        command += [f"{sub}.idx"]

    run(command)

