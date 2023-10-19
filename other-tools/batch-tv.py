#!/usr/bin/env python3

import asyncio
import json
from pathlib import Path
from argparse import ArgumentParser
from subprocess import PIPE, DEVNULL


async def main():
    parser = ArgumentParser()
    parser.add_argument("input_folder", type=Path)
    parser.add_argument("-w", "--workers", type=int, default=2)
    parser.add_argument("-m", "--monitor", action="store_true", help="monitor the input folder for new files")
    args, transcode_command = parser.parse_known_args()

    transcoder = BatchTranscoder(args.input_folder, args.monitor, transcode_command)
    await transcoder.run_batch(args.workers)

class BatchTranscoder:
    def __init__(self, input_folder: Path, monitor_input: bool, transcode_command) -> None:
        self.input_folder = input_folder
        self.monitor_input = monitor_input
        self.seen_files = []
        self.transcode_command = transcode_command if transcode_command else ["transcode.py", "--crop", "auto"]
        self.queue = asyncio.Queue()


    async def run_batch(self, num_workers: int):
        await self.fill_queue()
        
        async with asyncio.TaskGroup() as tg:
            for i in range(num_workers):
                tg.create_task(self.worker(f"worker-{i}"))

        await self.validate_duration()


    async def worker(self, name: str):
        while not self.queue.empty():
            file, cwd = await self.queue.get()
            print(f"{name} is transcoding {file}...")
            await self.transcode_file(file, cwd)
            if self.monitor_input:
                await self.fill_queue()
            self.queue.task_done()


    async def fill_queue(self):
        for file in self.input_folder.rglob("*.mkv"):
            if file not in self.seen_files:
                self.seen_files.append(file)
                cwd = file.relative_to(self.input_folder).parent
                await self.queue.put((file, cwd))
        

    async def transcode_file(self, input_file: Path, cwd: Path):
        command = list(self.transcode_command)
        command.append(str(input_file))
        
        if not await self.is_hd(input_file):
            command += ["--vf", "avc"]

        cwd.mkdir(parents=True, exist_ok=True)

        process = await asyncio.create_subprocess_exec(*command, cwd=cwd, stdout=DEVNULL, stderr=DEVNULL)
        await process.wait()

    async def validate_duration(self, num_workers: int):
        validation_queue = asyncio.Queue()

        async def do_validate():
            while not validation_queue.empty():
                input_file = await validation_queue.get()
                output_file = input_file.relative_to(self.input_folder)
                input_duration = await self.get_file_duration(input_file)
                output_duration = await self.get_file_duration(output_file)
                if abs(input_duration - output_duration) > 1:
                    print(f"WARNING: {input_file} and {output_file} have different durations! {input_duration} vs {output_duration}")
                validation_queue.task_done()

        for file in self.input_folder.rglob("*.mkv"):
            await validation_queue.put(file)

        with asyncio.TaskGroup() as tg:
            for _ in range(num_workers):
                tg.create_task(do_validate())


    async def is_hd(self, input_file):
            command = [
                "ffprobe",
                "-loglevel", "quiet",
                "-show_streams",
                "-show_format",
                "-print_format", "json",
                input_file
            ]

            process = await asyncio.create_subprocess_exec(*command, stdout=PIPE, stderr=DEVNULL)
            output, _ = await process.communicate()
            media_info = json.loads(output)

            video = [ x for x in media_info["streams"] if x["codec_type"] == "video" ][0]

            return video["width"] >= 1280
    
    async def get_file_duration(self, file):
        command = [
            "ffprobe",
            "-loglevel", "quiet",
            "-show_streams",
            "-show_format",
            "-print_format", "json",
            file
        ]

        process = await asyncio.create_subprocess_exec(*command, stdout=PIPE, stderr=DEVNULL)
        output, _ = await process.communicate()
        media_info = json.loads(output)

        return float(media_info.get("format", {}).get("duration", 0))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass