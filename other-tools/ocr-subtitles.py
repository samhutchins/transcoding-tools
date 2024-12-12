#!/usr/bin/env uv run -q

# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "typer==0.15.1",
#     "rich==13.9.4",
#     "pydantic==2.10.3",
# ]
# ///

from __future__ import annotations

import typer
import shlex
import shutil
from typing import Annotated
from pathlib import Path
from tempfile import TemporaryDirectory
from subprocess import run, PIPE, DEVNULL
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from pydantic import BaseModel
from dataclasses import dataclass

std_err = Console(stderr=True)

app = typer.Typer()


@app.command()
def main(
    file: Annotated[
        Path,
        typer.Argument(
            help="Path to a video file",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ],
    track: Annotated[
        int,
        typer.Option(
            "--track",
            "-t",
            help="Which subtitle track",
        ),
    ] = 1,
    debug: Annotated[bool, typer.Option(help="Turn on debug logging")] = False,
) -> None:
    subtitle_ocr = SubtitleOCR(debug=debug)
    subtitle_ocr.extract_srt(file, track)


class SubtitleOCR:
    def __init__(self, *, debug: bool) -> None:
        self.debug = debug

    def extract_srt(self, file: Path, track: int) -> None:
        with (
            TemporaryDirectory() as tmp_dir,
            Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True,
            ) as progress,
        ):
            media_info = self.__ffprobe(file)
            try:
                track_index = media_info.streams[track - 1].index
                track_language = media_info.streams[track - 1].tags.language
            except IndexError:
                std_err.print(f"Track index out of range: {track}")
                raise typer.Abort()

            output = file.with_name(f"{file.stem}.{track_language}.srt")
            if output.exists():
                std_err.print(f"Output file already exists: {shlex.quote(str(output))}")
                raise typer.Abort()

            task = progress.add_task(
                description="Extracting subtitle track...", total=None
            )
            subtitle_file = self.__extract_subtitle_track(file, track_index, tmp_dir)

            progress.update(task, description="Running macSubtitleOCR...")
            srt_file = self.__ocr_subtitles(subtitle_file, tmp_dir)

            shutil.move(srt_file, output)

    def __ffprobe(self, file: Path) -> FfprobeResult:
        command: list[str | Path] = [
            "ffprobe",
            "-select_streams",
            "s",
            "-show_streams",
            "-print_format",
            "json",
            file,
        ]

        return FfprobeResult.model_validate_json(
            run(command, stdout=PIPE, stderr=DEVNULL).stdout
        )

    def __extract_subtitle_track(
        self, file: Path, track: int, output_dir: str | Path
    ) -> Path:
        if isinstance(output_dir, str):
            output_dir = Path(output_dir)

        subtitle_file: Path = output_dir / "subtitles.mkv"
        command: list[str | Path] = [
            "ffmpeg",
            "-i",
            file,
            "-map",
            f"0:{track}",
            "-c",
            "copy",
            subtitle_file,
        ]

        if self.debug:
            std_err.print(" ".join(map(lambda x: shlex.quote(str(x)), command)))

        run(command, stdout=DEVNULL, stderr=DEVNULL)

        return subtitle_file

    def __ocr_subtitles(self, subtitle_file: Path, output_dir: str | Path) -> Path:
        if isinstance(output_dir, str):
            output_dir = Path(output_dir)

        command: list[str | Path] = ["macSubtitleOCR", subtitle_file, output_dir, "-i"]

        if self.debug:
            std_err.print(" ".join(map(lambda x: shlex.quote(str(x)), command)))

        run(command)
        srt_file = output_dir / "track_1.srt"
        if not srt_file.exists():
            raise typer.Abort()

        return srt_file


class FfprobeResult(BaseModel):
    streams: list[Stream]


@dataclass
class Stream:
    index: int
    tags: Tags


@dataclass
class Tags:
    language: str = "und"


if __name__ == "__main__":
    app()
