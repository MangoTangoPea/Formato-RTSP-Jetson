#!/usr/bin/env python3
"""
Clase para interfaz con la cámara Intel RealSense D435.

Extraída SIN MODIFICACIONES de realsense_monitor_jetson.py.
NO MODIFICAR esta clase bajo ninguna circunstancia.
"""

import pyrealsense2 as rs
from config import CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS


class RealSenseCamera:
    def __init__(self):
        self.width = CAMERA_WIDTH
        self.height = CAMERA_HEIGHT
        self.fps_config = CAMERA_FPS

        self.pipeline=rs.pipeline()
        self.config=rs.config()

        self.config.enable_stream(rs.stream.color,self.width,self.height,rs.format.bgr8,self.fps_config)
        self.config.enable_stream(rs.stream.depth,self.width,self.height,rs.format.z16,self.fps_config)
        self.config.enable_stream(rs.stream.infrared,1,self.width,self.height,rs.format.y8,self.fps_config)
        self.config.enable_stream(rs.stream.infrared,2,self.width,self.height,rs.format.y8,self.fps_config)

        profile=self.pipeline.start(self.config)
        self.depth_sensor=profile.get_device().first_depth_sensor()
        self.depth_sensor.set_option(rs.option.emitter_enabled,1)

    def get_frames(self):
        f=self.pipeline.wait_for_frames()
        return (f.get_color_frame(),
                f.get_depth_frame(),
                f.get_infrared_frame(1),
                f.get_infrared_frame(2))

    def stop(self):
        self.pipeline.stop()
