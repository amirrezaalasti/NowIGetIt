from manim import *
from manim_physics import Charge, ElectricField


class ElectricFieldPhysics(Scene):
    def construct(self) -> None:
        # Title
        title = Text("Electric Field Physics", font_size=48, color=BLUE)
        title.to_edge(UP, buff=0.5)
        self.play(Write(title), run_time=1.5)
        self.wait(0.5)
        
        # Create a single positive charge first
        positive_charge = Charge(2, ORIGIN)
        
        # Show the positive charge
        self.play(FadeIn(positive_charge, scale=0.5), run_time=1.0)
        self.wait(0.5)
        
        # Create electric field for single charge
        field = ElectricField(positive_charge)
        
        # Animate field appearance
        self.play(Create(field), run_time=2.5)
        self.wait(1.5)
        
        # Add explanation
        explanation = Text("Positive charge radiates field outward", 
                          font_size=28, color=YELLOW)
        explanation.to_edge(DOWN, buff=0.8)
        self.play(FadeIn(explanation, shift=UP), run_time=1.0)
        self.wait(2)
        
        # Fade out field and explanation
        self.play(
            FadeOut(field),
            FadeOut(explanation),
            run_time=1.0
        )
        self.wait(0.5)
        
        # Add a negative charge
        negative_charge = Charge(-1.5, RIGHT * 3)
        self.play(
            positive_charge.animate.shift(LEFT * 1.5),
            FadeIn(negative_charge, scale=0.5),
            run_time=1.5
        )
        self.wait(0.5)
        
        # Create field for both charges
        charges = VGroup(positive_charge, negative_charge)
        field = ElectricField(positive_charge, negative_charge)
        
        self.play(Create(field), run_time=2.5)
        self.wait(1.5)
        
        # New explanation
        explanation2 = Text("Field lines connect opposite charges", 
                           font_size=28, color=GREEN)
        explanation2.to_edge(DOWN, buff=0.8)
        self.play(FadeIn(explanation2, shift=UP), run_time=1.0)
        self.wait(2)
        
        # Move charges around to show dynamic field
        self.play(
            FadeOut(field),
            FadeOut(explanation2),
            run_time=1.0
        )
        
        # Create a third charge to make it more interesting
        third_charge = Charge(-1, UP * 2.5)
        self.play(FadeIn(third_charge, scale=0.5), run_time=1.0)
        self.wait(0.5)
        
        # Create field with all three charges
        field = ElectricField(positive_charge, negative_charge, third_charge)
        self.play(ShowIncreasingSubsets(field, run_time=2.5))
        self.wait(2)
        
        # Animate charges moving
        self.play(
            positive_charge.animate.move_to(LEFT * 2 + DOWN),
            negative_charge.animate.move_to(RIGHT * 2 + DOWN),
            third_charge.animate.move_to(UP * 1.5),
            FadeOut(field, scale=0.9),
            run_time=2.5
        )
        
        # Update field with new positions
        field = ElectricField(positive_charge, negative_charge, third_charge)
        self.play(Create(field), run_time=2.0)
        self.wait(1.5)
        
        # Final explanation
        explanation3 = Text("Complex field patterns emerge", 
                           font_size=28, color=PURPLE)
        explanation3.to_edge(DOWN, buff=0.8)
        self.play(Write(explanation3), run_time=1.5)
        self.wait(3)
        
        # Dramatic final animation
        all_objects = VGroup(charges, field, title, explanation3)
        self.play(
            all_objects.animate.scale(1.05),
            run_time=1.5
        )
        self.wait(2)
