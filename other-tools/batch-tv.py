#!/usr/bin/env python3

import asyncio
import json
from pathlib import Path
from argparse import ArgumentParser
from subprocess import PIPE, DEVNULL


async def main():
    parser = ArgumentParser()
    parser.add_argument("input_folder")
    args = parser.parse_args()

    input_folder = Path(args.input_folder)

    queue = asyncio.Queue()
    for file in input_folder.rglob("*.mkv"):
        cwd = file.relative_to(input_folder).parent
        await queue.put((file, cwd))
    
    tasks = []
    for i in range(2):
        tasks.append(asyncio.create_task(worker(f"worker-{i}", queue)))
    
    await queue.join()
    await asyncio.gather(*tasks)

    print("Done")

async def worker(name: str, queue: asyncio.Queue):
    while not queue.empty():
        file, cwd = await queue.get()
        print(f"{name} is transcoding {file}...")
        await transcode_file(file, cwd)
        queue.task_done()
     

async def transcode_file(input_file: Path, cwd: Path):
    command = [
        "hevc-encode.py",
        input_file,
        "--crop", "auto"]
     
    if not await is_hd(input_file):
        command += ["--vf", "avc"]
        
    cwd.mkdir(parents=True, exist_ok=True)

    process = await asyncio.create_subprocess_exec(*command, cwd=cwd, stdout=DEVNULL, stderr=DEVNULL)
    await process.wait()


async def is_hd(input_file):
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