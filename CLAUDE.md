# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CLI tool for transcribing audio/video files using OpenAI's transcription API. Supports parallel processing of chunks, automatic retries with fallback, and caching.

## Requirements

- Python 3.7+
- ffmpeg/ffprobe in PATH
- OpenAI API key in `.env` file (`OPENAI_API_KEY=...`)

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Basic usage
python transcribir_controlt.py --input "path/to/file.mp4"

# Full options
python transcribir_controlt.py --input "file.mp4" --model "gpt-4o-mini-transcribe" --chunk-seconds 600 --max-workers 5 --use-cache --keep-chunks
```

## Architecture

Single-file Python script (`transcribir_controlt.py`) with the following flow:

1. **Audio extraction**: Uses ffmpeg to extract audio as WAV mono 16kHz
2. **Segmentation**: For files longer than chunk duration, segments directly during extraction using ffmpeg's segment filter
3. **Parallel transcription**: Uses `ThreadPoolExecutor` to transcribe chunks concurrently
4. **Fallback**: If primary model fails, automatically retries with `whisper-1`
5. **Output**: Generates `.txt` (plain text) and `.json` (with metadata/metrics) files

Key components:
- `extract_and_segment_directly()`: Single ffmpeg call for extraction + segmentation
- `transcribe_chunk_parallel()`: Per-chunk transcription with fallback logic
- `retry_with_backoff`: Decorator for exponential backoff retries
- `PerformanceMetrics`: Dataclass tracking extraction/transcription times

## Models

- `gpt-4o-mini-transcribe` (default, recommended)
- `whisper-1` (faster, used as fallback)

## Output Structure

```
salida_transcripcion/
└── video_name/
    ├── video_name_transcripcion.txt
    ├── video_name_transcripcion.json
    └── chunks/  (if --keep-chunks)
```
