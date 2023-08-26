#!/usr/bin/env python3

import json
import os
from subprocess import run, PIPE, DEVNULL


def main():
    queuemaker = QueueMaker()
    queuemaker.run()


class QueueMaker:
    def run(self):
        library_location = "X:\Plex Library\Films"
        source_locations = ["D:\Films", "E:\Films", "F:\Films", "G:\Films"]

        library_info = self.get_library_info(library_location)

        not_in_library = []
        needs_ripping = []
        needs_transcoding = []
        done = []

        for source in source_locations:
            for root, _, files in os.walk(source):
                for file in files:
                    if file[-3:] == "mkv":
                        full_path = os.path.join(root, file)
                        film_name = os.path.splitext(os.path.basename(file))[0]

                        if film_name not in library_info:
                            not_in_library.append(full_path)
                        else:
                            transcoded_vcodec, transcoded_acodec = library_info.pop(film_name)
                            media_info = self.scan_media(full_path)
                            audio_codec = [ x for x in media_info["streams"] if x["codec_type"] == "audio"][0]["codec_name"]

                            if audio_codec == "flac":
                                needs_ripping.append(full_path)
                            else:
                                if transcoded_vcodec != "hevc" or (audio_codec != "ac3" and transcoded_acodec != "eac3"):
                                    needs_transcoding.append(full_path)
                                else:
                                    done.append(full_path)

        
        if not_in_library:
            with open("not_in_library.txt", "w") as f:
                f.writelines(self.add_line_endings(not_in_library))

        if needs_ripping:
            with open("needs_ripping.txt", "w") as f:
                f.writelines(self.add_line_endings(needs_ripping))

        if needs_transcoding:
            with open("needs_transcoding.txt", "w") as f:
                f.writelines(self.add_line_endings(needs_transcoding))

        if done:
            with open("done.txt", "w") as f:
                f.writelines(self.add_line_endings(done))

        if library_info:
            with open("needs_buying.txt", "w") as f:
                f.writelines(self.add_line_endings(library_info.keys()))

        print("Done")

    
    def get_library_info(self, library_location):
        library_info = {}

        for root, _, files in os.walk(library_location):
            for file in files:
                if file[-3:] in ["mkv", "mp4", "m4v"]:
                    full_path = os.path.join(root, file)
                    film_name = os.path.splitext(os.path.basename(file))[0]
                    media_info = self.scan_media(full_path)

                    video_codec = [ x for x in media_info["streams"] if x["codec_type"] == "video" ][0]["codec_name"]
                    audio_codec = [ x for x in media_info["streams"] if x["codec_type"] == "audio"][0]["codec_name"]

                    library_info[film_name] = (video_codec, audio_codec)

        return library_info


    def scan_media(self, file):
        command = [
            "ffprobe",
            "-loglevel", "quiet",
            "-show_streams",
            "-show_format",
            "-print_format", "json",
            file
        ]

        output = run(command, stdout=PIPE, stderr=DEVNULL).stdout
        return json.loads(output)


    def add_line_endings(self, lines):
        for line in lines:
            yield line
            yield "\n"


if __name__ == "__main__":
    main()