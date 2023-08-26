#!/usr/bin/env python3

import collections
import json
import os
from argparse import ArgumentParser
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from multiprocessing import Pool
from subprocess import run, DEVNULL, PIPE

import math

unit_base = 1000
verbose = False

def main():
    parser = ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("-b", "--buffer", type=float, nargs="+")
    parser.add_argument("--initial-buffer-fill", type=str)
    parser.add_argument("--plex", action="store_true")
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()
    global verbose
    verbose = args.verbose

    if args.plex and (args.buffer or args.initial_buffer_fill):
        exit("--plex is mutually exclusive with --buffer and --initial-buffer-fill")

    if args.plex:
        args.buffer = [4.5, 9, 22.5, 45, 67.5, 90, 225, 450]
        args.initial_buffer_fill = "5s"
    else:
        if not args.buffer:
            args.buffer = [50]

        if not args.initial_buffer_fill:
            args.initial_buffer_fill = "0s"
        elif args.initial_buffer_fill[-1:] in ["s", "%"]:
            try:
                number = int(args.initial_buffer_fill[:-1])
            except ValueError:
                exit("Invalid value for --initial-buffer-fill: must be numerical")
            
            if number < 0:
                exit("Invalid value for --initial-buffer-fill: must be greater than 0")

            if args.initial_buffer_fill[-1:] == "%" and number > 100:
                exit("Invalid value for --initial-buffer-fill: can't be more than 100%")
        else:
            exit(f"--initial-buffer-fill must be a percentage or a value in seconds")

    all_frame_sizes = []
    bitrate_samples = []

    print("Reading file, this might take a while...")
    media_info = scan_media(args.file)

    fps = float(Fraction(media_info["streams"][0]["avg_frame_rate"]))
    rounded_fps = round(fps)
    last_second_of_frame_sizes = collections.deque(maxlen=rounded_fps)

    for packet in media_info["packets"]:
        frame_size = int(packet["size"]) * 8 # ffmpeg counts in bytes, we want bits
        last_second_of_frame_sizes.append(frame_size)
        all_frame_sizes.append(frame_size)

        if len(last_second_of_frame_sizes) == rounded_fps:
            bitrate_samples.append(sum(last_second_of_frame_sizes))

    bitrate_samples.sort()
    max_bitrate = max(bitrate_samples)
    min_bitrate = min(bitrate_samples)
    average_bitrate = sum(bitrate_samples) / len(bitrate_samples)
    bitrate_95_percentile = get_nth_percentile(bitrate_samples, 95)

    network_speeds = get_network_requirements(all_frame_sizes, fps, args.buffer, args.initial_buffer_fill, average_bitrate, max_bitrate)
    filename = os.path.basename(args.file)

    print(filename)
    if args.plex:
        rates = ",".join([ str(x[1]) for x in network_speeds])
        print("{" + rates + "}")
    else:
        print("  Bitrate:")
        print(f"    min: {human_readable_bitrate(min_bitrate)}, max: {human_readable_bitrate(max_bitrate)}, avg: {human_readable_bitrate(average_bitrate)}, 95th percentile: {human_readable_bitrate(bitrate_95_percentile)}")
        print(f"    Required network speed: {', '.join([ str(x[0]) + ' MB: ' + str(x[1]) + ' Kb/s' for x in network_speeds ])}")


def get_network_requirements(frame_sizes, fps, buffer_sizes_mb, initial_buffer_fill, average_bitrate, max_bitrate):
    print("Simulating playback...")

    args = [ (frame_sizes, fps, x, initial_buffer_fill, average_bitrate, max_bitrate) for x in buffer_sizes_mb ]
    if len(args) > 1 and not verbose:
        with Pool(len(args)) as p:
            network_speeds = p.map(get_network_requirements_impl, args)
    else:
        network_speeds = list(map(get_network_requirements_impl, args))

    return network_speeds


def get_network_requirements_impl(args):
    frame_sizes, fps, buffer_size_mb, initial_buffer_fill, average_bitrate, max_bitrate = args

    buffer_size_bits = buffer_size_mb * 8 * unit_base * unit_base
    if initial_buffer_fill[:-1] == "%":
        initial_buffer_fill_bits = buffer_size_bits * (int(initial_buffer_fill[:-1]) / 100)
    else:
        initial_buffer_fill_bits = sum(frame_sizes[0:int(initial_buffer_fill[:-1])*round(fps)])

    if verbose:
        print(f"Getting network requirements for {human_readable_size(buffer_size_bits)} buffer...")
        print(f"{initial_buffer_fill} buffer fill is {human_readable_size(initial_buffer_fill_bits)}")

    lowest_successful_network_speed = int(max_bitrate / unit_base) #kbps
    highest_failed_network_speed = 0 #kbps
    network_speed = int(average_bitrate / unit_base) #kbps

    while lowest_successful_network_speed - highest_failed_network_speed > 1:
        playback_successful = simulate_playback(frame_sizes, fps, buffer_size_bits, network_speed, initial_buffer_fill_bits)
        if playback_successful:
            lowest_successful_network_speed = min(network_speed, lowest_successful_network_speed)
        else:
            highest_failed_network_speed = max(network_speed, highest_failed_network_speed)
        
        network_speed = round((lowest_successful_network_speed + highest_failed_network_speed) / 2)
    
    if verbose:
        print(f"{network_speed} Kb/s")
        print()
    return buffer_size_mb, network_speed


def simulate_playback(frame_sizes, fps, buffer_size_bits, network_speed_kbps, init_buffer_bits):
    network_speed_bps = network_speed_kbps * unit_base

    total_frames = len(frame_sizes)
    frames_played = 0
    stream = collections.deque(frame_sizes)
    bits_per_tick = int(network_speed_bps / fps)
    buffer = collections.deque()
    partial_frame_in_buffer = False
    playback_begun = False
    buffer_fullness = 0
    while total_frames > frames_played:
        # simulate download
        bits_remaining_in_tick = bits_per_tick
        while bits_remaining_in_tick > 0 and buffer_fullness < buffer_size_bits:
            try:
                frame_to_download = stream.popleft()
            except IndexError:
                break
                
            if frame_to_download <= bits_remaining_in_tick and buffer_fullness + frame_to_download <= buffer_size_bits:
                buffer_fullness += frame_to_download
                bits_remaining_in_tick -= frame_to_download

                if partial_frame_in_buffer:
                    frame_to_download += buffer.pop()
                buffer.append(frame_to_download)
                partial_frame_in_buffer = False
            else:
                amount_downloaded = min(bits_remaining_in_tick, buffer_size_bits - buffer_fullness)
                buffer_fullness += amount_downloaded
                bits_remaining_in_tick -= amount_downloaded
                stream.appendleft(frame_to_download - amount_downloaded)
                if partial_frame_in_buffer:
                    amount_downloaded += buffer.pop()
                buffer.append(amount_downloaded)
                partial_frame_in_buffer = True

            if buffer_fullness > buffer_size_bits:
                exit("Buffer overflow")

        # simulate playback

        frames_in_buffer = len(buffer)
        if not playback_begun:
            playback_begun = frames_in_buffer == total_frames or buffer_fullness == buffer_size_bits or buffer_size_bits >= init_buffer_bits
        elif frames_in_buffer > 0 and not (frames_in_buffer == 1 and partial_frame_in_buffer) :                    
            buffer_fullness -= buffer.popleft()
            frames_played += 1
        else:
            return False

    return True


def get_nth_percentile(values, percentile):
    index = int(percentile / 100 * len(values))
    return values[index]


def human_readable_bitrate(bitrate):
    if bitrate == 0:
        return "0 b/s"

    units = ["b/s", "Kb/s", "Mb/s", "Gb/s"]
    exponent = int(math.log(bitrate) / math.log(unit_base))
    unit = units[exponent]
    value = bitrate / math.pow(unit_base, exponent)

    return f"{value:.2f} {unit}"


def human_readable_size(size_in_bits):
    if size_in_bits == 0:
        return "0 B"
    
    units = ["B", "KB", "MB", "GB"]
    size_in_bytes = size_in_bits / 8

    exponent = int(math.log(size_in_bytes) / math.log(unit_base))
    unit = units[exponent]
    value = size_in_bytes / math.pow(unit_base, exponent)

    return f"{value:.2f} {unit}"


def scan_media(input_file):
    command = [
        "ffprobe",
        "-loglevel", "quiet",
        "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate:packet=size",
        "-print_format", "json",
        input_file
    ]

    output = run(command, stdout=PIPE, stderr=DEVNULL).stdout
    return json.loads(output)


def round(number):
    # Python rounds half even by default, which is good for statistics but it means the calculated required bitrate will be 1kbps too low half the time
    return int(Decimal(number).quantize(Decimal("1."), ROUND_HALF_UP))


if __name__ == "__main__":
    main()