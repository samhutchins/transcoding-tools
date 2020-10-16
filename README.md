# Transcoding Tools

Tools to inspect, remux, and transcode Blu Ray or DVD rips

## Usage

`remux.py` usage can be as simple as `remux.py path/to/file`. This will remux the file into an `mkv` container, and preserve all the tracks in the input while cleaning up the default/forced tags

To see which tracks are available, use `remux.py --inspect`. This will print track information, such as codec, channel layout, and the forced attribute.

You can select audio tracks, subtitle tracks, and forced subtitles with the `--select-audio`, `--select-subtitles`, and `--force-subtitle` options respectively. These options use the track index indicated by the `--inspect` option.

`transcode.py` is also very simple, `transcode.py path/to/file` should be enough for most cases. The tool automatically applies cropping, deinterlacing, subtitle selection, and subtitle burning. This behaviour can be overridden or refined with the various options. See `transcode.py --help` for more information.

## Requirements

`remux.py` depends on `ffprobe` and `mkvmerge`, from the [ffmpeg](https://ffmpeg.org/) and [MKVToolNix](https://mkvtoolnix.download/) projects respectively.

`transcode.py` depends on `HandBrakeCLI`, `ffprobe`, `ffmpeg`, `mkvmerge`, and `mkvpropedit`

## Credits

I've written these tools with lots of inspiration from Don Melton's excellent [video_transcoding](https://github.com/donmelton/video_transcoding) and [other_video_transcoding](https://github.com/donmelton/other_video_transcoding) projects. While I'm making my tools public, Don's are likely to be more flexible, and I highly recommend using them.