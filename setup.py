#!/usr/bin/env python3

import setuptools
import transcoding_tools

with open("README.md", "r") as f:
    long_description = f.read()

setuptools.setup(
    name="transcoding-tools",
    version=transcoding_tools.__version__,
    author="Sam Hutchins",
    description="Tools to inspect, remux, and transcode Blu Ray rips",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/samhutchins/transcoding-tools",
    packages=["transcoding_tools"],
    license="MIT",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.7',
    entry_points={
        "console_scripts": [
            'transcode=transcoding_tools.transcode:main',
            'remux=transcoding_tools.remux:main',
            'inspect=transcoding_tools.inspect:main'
        ]
    }
)