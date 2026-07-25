import os
import re
import shutil
from pathlib import Path

source_dir = Path("artifacts/15f2ccbfc110/scenes")
dest_dir = Path("heating_demands/conduction")
dest_dir.mkdir(parents=True, exist_ok=True)

scenes = sorted(source_dir.glob("scene_*"), key=lambda p: int(p.name.split("_")[1]))

merged_code = "import os\nimport numpy as np\nimport math\nfrom manim import *\n\n"
seen_imports = set(["import os", "import numpy as np", "import math", "from manim import *"])

class_info = []

for i, scene_dir in enumerate(scenes, start=1):
    # Prefer code_final.py, fallback to highest code_r*.py
    code_path = scene_dir / "code_final.py"
    if not code_path.exists():
        revs = sorted(scene_dir.glob("code_r*.py"), key=lambda p: int(re.search(r"r(\d+)", p.name).group(1)))
        if revs:
            code_path = revs[-1]
            
    audio_path = scene_dir / "audio.mp3"
    
    if code_path.exists():
        text = code_path.read_text(encoding="utf-8")
        
        # Find class name
        match = re.search(r"class\s+([A-Za-z0-9_]+)\s*\(\s*Scene\s*\)\s*:", text)
        class_name = match.group(1) if match else f"Scene{i}"
        class_info.append((class_name, f"scene_{i}_audio.mp3"))
        
        lines = text.splitlines()
        for line in lines:
            line_str = line.strip()
            if line_str.startswith("from ") or line_str.startswith("import "):
                if line_str not in seen_imports:
                    merged_code = line + "\n" + merged_code
                    seen_imports.add(line_str)
            else:
                merged_code += line + "\n"
        merged_code += "\n\n"
        
    if audio_path.exists():
        shutil.copy2(audio_path, dest_dir / f"scene_{i}_audio.mp3")

# Add Master FullConductionVideo class
merged_code += """
class FullConductionVideo(Scene):
    def construct(self):
        scenes = [""" + ", ".join([c[0] for c in class_info]) + """]
        base_dir = os.path.dirname(os.path.abspath(__file__))
        audio_files = [
            os.path.join(base_dir, f"scene_{i}_audio.mp3")
            for i in range(1, """ + str(len(scenes) + 1) + """)
        ]
        
        for scene_cls, audio_path in zip(scenes, audio_files):
            if os.path.exists(audio_path):
                self.add_sound(audio_path)
            scene_cls.construct(self)
            self.clear()
"""

(dest_dir / "merged_scenes.py").write_text(merged_code, encoding="utf-8")
print(f"Merged scenes for Conduction successfully. Scene classes: {[c[0] for c in class_info]}")

# Create build_full_video.py for Conduction
build_script = f"""import sys
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
"""
for i, (cls_name, aud_name) in enumerate(class_info, start=1):
    build_script += f'        ("{cls_name}", base_dir / "{aud_name}"),\n'

build_script += """    ]
    
    muxed_clips = []
    
    for idx, (scene_name, audio_path) in enumerate(scenes, start=1):
        print(f"--- Rendering {scene_name} (Scene {idx}/""" + str(len(class_info)) + """) ---")
        
        render_cmd = [
            str(project_root / ".venv/bin/manim"),
            "-qh",
            "--media_dir", str(output_dir / "media"),
            str(script_path),
            scene_name,
        ]
        
        res = subprocess.run(render_cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Error rendering {scene_name}:\\n{res.stderr}")
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
    final_output = base_dir / "Full_Conduction_Video_HQ.mp4"
    result = compose_final_video(muxed_clips, final_output)
    
    if result:
        print(f"\\nSUCCESS! Full high-quality video composed without audio overlap:")
        print(f"Path: {final_output}")
    else:
        print("\\nFailed to compose final video.")

if __name__ == "__main__":
    main()
"""

(dest_dir / "build_full_video.py").write_text(build_script, encoding="utf-8")
print("build_full_video.py created for Conduction.")
