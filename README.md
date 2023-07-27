# Transcoding Tools

Tools to inspect, remux, and transcode Blu Ray or DVD rips

## Usage

There are currently 3 tools: `inspect`, `remux`, and `transcode`. Each command has a `--help` option that contains useful information, and a full break-down of all the options.

`inspect` is useful for understanding the source media, it will print stream information, including codec, channel layout, element counts, language, and disposition; and also scan for crop boundaries and interlacing artefacts. You can use this information to inform your decisions about how to transcode.

`remux` will let you normalise rips, adjusting disposition and track selection in the process.

`transcode` is where the good stuff is, and has the most options. It leverages `HandBrakeCLI` to transcode, and it has a lot of automatic behaviors. By default, the video stream will be h.264 at 8000kb/s. Cropping is applied automatically, as is basic deinterlacing. The first audio track is transcoded to up to 5.1 AC3 at 640kb/s, although stereo audio is encoded to AAC. Forced subtitles are burned in, and any other subtitles that match the language of the main audio track will be included. The tool provides _some_ configuration for track selection, codecs, and bitrates; but it's generally more of an "opinionated" tool (read: optimised for my workflow)

I strongly recommend taking a look at Lisa Melton's [other_video_transcoding](https://github.com/lisamelton/other_video_transcoding) project, as it's more flexible and better tested.

## Requirements

`transcode` depends on `HandBrakeCLI`, `ffprobe`, `ffmpeg`, `mkvmerge`, and `mkvpropedit`

`remux` depends on `ffprobe` and `mkvmerge`

`inspect` depends on `ffprobe` and `ffmpeg`


## Credits

I've written these tools with lots of inspiration from Lisa Melton's excellent [video_transcoding](https://github.com/lisamelton/video_transcoding) and [other_video_transcoding](https://github.com/lisamelton/other_video_transcoding) projects. The crop detection is from `other-transcode`, and a lot of inspiration on how to drive `HandBrakeCLI` was take from transcode-video