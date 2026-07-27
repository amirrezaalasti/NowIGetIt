from manim import *
from manim_physics import *

# Configure for vertical format (9:16) - 1080x1920
config.pixel_width = 1080
config.pixel_height = 1920
config.frame_width = 9.0
config.frame_height = 16.0

class MultiPendulumVertical(SpaceScene):
    def construct(self):
        # Black background
        self.camera.background_color = BLACK
        
        # Neon vibrant colors
        neon_colors = [
            "#FF1493",  # Deep pink
            "#00FFFF",  # Cyan
            "#FF6600",  # Bright orange
            "#39FF14",  # Neon green
            "#FF073A",  # Neon red
            "#BF00FF",  # Electric purple
            "#FFFF00",  # Yellow
            "#00FF7F",  # Spring green
        ]
        
        # Create multi-pendulum with only 2 points
        p = MultiPendulum(
            RIGHT * 2, 
            LEFT * 2,
            bob_style={
                "color": WHITE,
                "fill_opacity": 1,
                "radius": 0.4
            }
        )
        # Move the entire pendulum higher up
        p.shift(UP * 5)
        
        # Color the bobs with neon colors and glow effect
        for i, bob in enumerate(p.bobs):
            color = neon_colors[i % len(neon_colors)]
            bob.set_color(color)
            bob.set_fill(color, opacity=1)
            bob.set_sheen(0.5, UL)
            
            # Add glow ring around each bob
            glow = Circle(radius=0.55, color=color, stroke_width=8, stroke_opacity=0.4)
            glow.move_to(bob.get_center())
            glow.add_updater(lambda m, b=bob: m.move_to(b.get_center()))
            self.add(glow)
            
            # Add inner glow
            inner_glow = Circle(radius=0.48, color=WHITE, stroke_width=3, stroke_opacity=0.3)
            inner_glow.move_to(bob.get_center())
            inner_glow.add_updater(lambda m, b=bob: m.move_to(b.get_center()))
            self.add(inner_glow)
        
        # Color the rods with gradient effect
        for i, rod in enumerate(p.rods):
            color = neon_colors[i % len(neon_colors)]
            rod.set_color(color)
            rod.set_stroke(width=6, opacity=0.9)
        
        self.add(p)
        self.make_rigid_body(*p.bobs)
        p.start_swinging()
        
        # Add thick glowing traced paths for each bob
        for i, bob in enumerate(p.bobs):
            color = neon_colors[i % len(neon_colors)]
            # Main trace
            self.add(
                TracedPath(
                    bob.get_center, 
                    stroke_color=color,
                    stroke_width=5,
                    stroke_opacity=0.9
                )
            )
            # Glow trace (wider, more transparent)
            self.add(
                TracedPath(
                    bob.get_center, 
                    stroke_color=color,
                    stroke_width=12,
                    stroke_opacity=0.3
                )
            )
        
        self.wait(15)
