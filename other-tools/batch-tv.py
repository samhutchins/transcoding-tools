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
    args = parser.parse_args()

    transcoder = BatchTranscoder(args.input_folder)
    await transcoder.run_batch(args.workers)

class BatchTranscoder:
    def __init__(self, input_folder: Path) -> None:
        self.input_folder = input_folder
        self.seen_files = []
        self.queue = asyncio.Queue()


    async def run_batch(self, num_workers: int):
        await self.fill_queue()
        
        workers = []
        for i in range(num_workers):
            workers.append(asyncio.create_task(self.worker(f"worker-{i}")))
        
        await self.queue.join()
        await asyncio.gather(*workers)


    async def fill_queue(self):
        for file in self.input_folder.rglob("*.mkv"):
            if file not in self.seen_files:
                self.seen_files.append(file)
                cwd = file.relative_to(self.input_folder).parent
                await self.queue.put((file, cwd))
    

    async def worker(self, name: str):
        while not self.queue.empty():
            file, cwd = await self.queue.get()
            print(f"{name} is transcoding {file}...")
            await self.transcode_file(file, cwd)
            await self.fill_queue()
            self.queue.task_done()
        

    async def transcode_file(self, input_file: Path, cwd: Path):
        command = [
            "hevc-encode.py",
            input_file,
            "--crop", "auto"]
        
        if not await self.is_hd(input_file):
            command += ["--vf", "avc"]
            
        cwd.mkdir(parents=True, exist_ok=True)

        process = await asyncio.create_subprocess_exec(*command, cwd=cwd, stdout=DEVNULL, stderr=DEVNULL)
        await process.wait()


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


if __name__ == "__main__":
    asyncio.run(main())