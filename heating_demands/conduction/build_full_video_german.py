#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

# Important: Make sure backend module is in path so we can import compose
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.pipeline.compose import compose_final_video

def main():
    base_dir = Path(__file__).parent
    output_video = base_dir / "Full_Conduction_Video_German_HQ.mp4"
    script_file = base_dir / "merged_scenes_german.py"

    print(f"--- Building Full Conduction German Video HQ ---")
    
    # Check if audio files exist
    for i in range(1, 5):
        audio_path = base_dir / f"scene_{i}_german_audio.mp3"
        if not audio_path.exists():
            print(f"Warning: {audio_path.name} not found. Ensure audio has been generated.")

    # 1. Render manim scenes from merged_scenes_german.py using high quality (1080p60)
    # The FullConductionVideo class will sequentially render all 4 scenes and mux the audio automatically.
    print("\nRunning Manim render...")
    cmd = [
        sys.executable, "-m", "manim",
        str(script_file),
        "FullConductionVideo",
        "--quality", "h",
        "--format", "mp4",
        "--media_dir", str(base_dir / "media")
    ]
    
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("Error during Manim rendering. Exiting.")
        sys.exit(result.returncode)

    # 2. Find the output video and rename/move it
    # Manim places output in media/videos/merged_scenes_german/1080p60/FullConductionVideo.mp4
    rendered_vid = base_dir / "media" / "videos" / "merged_scenes_german" / "1080p60" / "FullConductionVideo.mp4"
    
    if rendered_vid.exists():
        rendered_vid.rename(output_video)
        print(f"\nSUCCESS! High-quality video saved to: {output_video}")
    else:
        print(f"\nCould not find expected output at {rendered_vid}.")

if __name__ == "__main__":
    main()
