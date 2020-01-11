# remux.py

A tool to inspect and remux Blu Ray or DVD rips to prepare them for transcoding

## Usage

`remux.py` usage can be as simple as `remux.py path/to/file`. This will remux the file into an `mkv` container, and preserve all the tracks in the input while cleaning up the default/forced tags

To see which tracks are available, use `remux.py --inspect`. This will print track information, such as codec, channel layout, and the forced attribute.

You can select audio tracks, subtitle tracks, and forced subtitles with the `--select-audio`, `--select-subtitles`, and `--force-subtitle` options respectively. These options use the track index indicated by the `--inspect` option.

## Requirements

`remux.py` depends on `ffprobe` and `mkvmerge`, from the [ffmpeg](https://ffmpeg.org/) and [MKVToolNix](https://mkvtoolnix.download/) projects respectively.

## Credits

I've written this tool to help with pre-processing files for Don Melton's excellent [video_transcoding](https://github.com/donmelton/video_transcoding) and [other_video_transcoding](https://github.com/donmelton/other_video_transcoding) projects, and much inspiration for the implementation of `remux.py` has come from inspecting those tools.