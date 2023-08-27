# Simple transcoding tools

Intentionally simple transcoding scripts

## Usage

1. Inspect your source material with `inspect.py`. It will print stream information that should help you decide which streams you want to keep

1. Remux your source to normalise it using `remux.py`. Use `-a` to select audio tracks, `-s` to select subtitle tracks, and `-f` for force a subtitle track, if desired. 

1. Check cropping with `preview-crop.py`. It will open `mpv` with the `drawbox` filter to show what the detected crop is, and it will put a `crop.txt` file with the detected crop in the current working directory.

1. Transcode with `hevc-encode.py`. If `crop.txt` is found next to the source, it will automatically be used for crop information. Use `--dry-run` to see the HandBrakeCLI command. For a rough idea: it'll take the video track and transcode it to a 10-bit HEVC video using x265; it'll select the first audio track and convert it to E-AC3, at varying bitrates depending on channels. It will add all subtitles in their current format, burning the first forced track

## Dependencies

Each tool has its own dependencies, I've tried to keep them as minimal as possible. Each command needs to be accessible on your `$PATH`

 - `inspect.py` depends on `ffprobe` and `mkvmerge`
 - `remux.py` depends on `mkvmerge`
 - `preview-crop.py` depends on `ffprobe`, `ffmpeg`, and `mpv`
 - `hevc-encode.py` depends on `HandBrakeCLI`, and optionally `mkvpropedit`

 ## Installation

 - Drop the `.py` files somewhere in your `$PATH`.
 - Get `HandBrakeCLI` from here: https://handbrake.fr/downloads2.php, drop it in your `$PATH`
 - Get `ffmpeg` and `ffprobe` from here: https://ffmpeg.org/download.html, drop them in your `$PATH` (look for static builds)
 - Get `mkvmerge` and `mkvpropedit` from here: https://mkvtoolnix.download/downloads.html, drop them into your `$PATH`
 - Get `mpv` from here: https://mpv.io/installation/, drop it in your `$PATH`