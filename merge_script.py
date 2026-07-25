import os
import shutil
from pathlib import Path

source_dir = Path("artifacts/511f6c126e8c/scenes")
dest_dir = Path("heating_demands/convection")
dest_dir.mkdir(parents=True, exist_ok=True)

merged_code = "from manim import *\n\n"
seen_imports = set(["from manim import *"])

scenes = sorted(source_dir.glob("scene_*"), key=lambda p: int(p.name.split("_")[1]))

for i, scene_dir in enumerate(scenes, start=1):
    code_path = scene_dir / "code_final.py"
    audio_path = scene_dir / "audio.mp3"
    
    if code_path.exists():
        with open(code_path, "r") as f:
            lines = f.readlines()
            
        for line in lines:
            if line.startswith("from ") or line.startswith("import "):
                if line.strip() not in seen_imports:
                    merged_code = line + merged_code
                    seen_imports.add(line.strip())
            else:
                merged_code += line
        merged_code += "\n\n"
        
    if audio_path.exists():
        shutil.copy2(audio_path, dest_dir / f"scene_{i}_audio.mp3")

with open(dest_dir / "merged_scenes.py", "w") as f:
    f.write(merged_code)

print("Merged successfully to heating_demands/convection")
