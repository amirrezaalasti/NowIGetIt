import sys
import subprocess
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.pipeline.compose import mux_scene_audio, compose_final_video

def main():
    base_dir = Path(__file__).resolve().parent
    script_path = base_dir / "merged_scenes.py"
    output_dir = base_dir / "rendered"
    output_dir.mkdir(exist_ok=True)
    
    scenes = [
        ("Scene1", base_dir / "scene_1_audio.mp3"),
        ("Scene2", base_dir / "scene_2_audio.mp3"),
        ("Scene3", base_dir / "scene_3_audio.mp3"),
        ("Scene4", base_dir / "scene_4_audio.mp3"),
    ]
    
    muxed_clips = []
    
    for idx, (scene_name, audio_path) in enumerate(scenes, start=1):
        print(f"--- Rendering {scene_name} (Scene {idx}/4) ---")
        
        render_cmd = [
            str(project_root / ".venv/bin/manim"),
            "-qh",
            "--media_dir", str(output_dir / "media"),
            str(script_path),
            scene_name,
        ]
        
        res = subprocess.run(render_cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Error rendering {scene_name}:\n{res.stderr}")
            continue
            
        rendered_mp4 = output_dir / "media" / "videos" / "merged_scenes" / "1080p60" / f"{scene_name}.mp4"
        if not rendered_mp4.exists():
            candidates = list((output_dir / "media").rglob(f"{scene_name}.mp4"))
            if candidates:
                rendered_mp4 = candidates[0]
            else:
                print(f"Could not find rendered mp4 for {scene_name}")
                continue
                
        muxed_output = output_dir / f"scene_{idx}_with_audio.mp4"
        print(f"--- Muxing audio for {scene_name} ---")
        muxed_path = mux_scene_audio(str(rendered_mp4), str(audio_path) if audio_path.exists() else None, muxed_output)
        
        if muxed_path:
            muxed_clips.append(muxed_path)
            
    print("--- Composing Final Full Video ---")
    final_output = base_dir / "Full_Introduction_Video_HQ.mp4"
    result = compose_final_video(muxed_clips, final_output)
    
    if result:
        print(f"\nSUCCESS! Full high-quality video composed without audio overlap:")
        print(f"Path: {final_output}")
    else:
        print("\nFailed to compose final video.")

if __name__ == "__main__":
    main()
