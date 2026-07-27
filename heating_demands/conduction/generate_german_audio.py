import sys
import os
from pathlib import Path
from backend.pipeline.tts import synthesize_narration

texts = [
    "Wärme fließt auf makroskopischer Ebene stets von warm zu kalt, bis ein thermisches Gleichgewicht erreicht ist. Auf mikroskopischer Ebene bedeutet dies, dass schnell schwingende Atome ihre kinetische Energie an langsamere Nachbarn weitergeben. Eine Dämmschicht nach DIN 4108 blockiert diesen Prozess durch Lufteinschlüsse.",
    "Der Wärmedurchlasswiderstand R-Wert gibt an, wie gut eine Schicht dämmt. Gemäß DIN 4108 berechnet er sich als Quotient aus der Schichtdicke und der Wärmeleitfähigkeit des Materials. Eine doppelte Dämmdicke verdoppelt somit direkt den Wärmewiderstand.",
    "Der U-Wert oder Wärmedurchgangskoeffizient ist der Kehrwert des R-Wertes gemäß Gebäudeenergiegesetz. Er misst den Wärmestrom pro Quadratmeter und Kelvin Temperaturunterschied. Je steiler der Temperaturgradient in der Wand, desto größer ist die Wärmeverlustrate nach außen.",
    "Die thermische Gebäudehülle nach GEG umfasst alle Bauteile, die beheizte von unbeheizten Bereichen trennen. Der gesamte Transmissionswärmeverlust gemäß DIN EN ISO 13789 ist die Summe der Verluste durch das Dach, die Fenster, die Wände, die Türen und das Fundament."
]

base_dir = Path(__file__).parent

for i, text in enumerate(texts, 1):
    out_path = base_dir / f"scene_{i}_german_audio.mp3"
    print(f"Generating scene {i}...")
    audio_path, skipped = synthesize_narration(text, out_path)
    if skipped:
        print(f"Failed to generate TTS for scene {i}. Check TTS_API_KEY.")
    else:
        print(f"Saved: {audio_path}")

print("Done.")
