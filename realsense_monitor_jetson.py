# realsense_monitor.py
import cv2
import time
import numpy as np
import pyrealsense2 as rs
from datetime import datetime

import glob

class JetsonMonitor:
    def __init__(self):
        self.sensors={}
        for path in glob.glob('/sys/class/thermal/thermal_zone*'):
            try:
                self.sensors[open(path+'/type').read().strip()]=path+'/temp'
            except: pass
    def temperatures(self):
        d={}
        for n,f in self.sensors.items():
            try:d[n]=int(open(f).read())/1000
            except: pass
        return d

GREEN=(0,255,0)
WHITE=(255,255,255)
YELLOW=(0,255,255)
GRAY=(70,70,70)

class RealSenseCamera:
    def __init__(self, record_bag_path: str = None):
        self.width=640
        self.height=480
        self.fps_config=30

        self.pipeline=rs.pipeline()
        self.config=rs.config()

        if record_bag_path:
            self.config.enable_record_to_file(record_bag_path)

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

class DisplayManager:
    def __init__(self):
        self.font=cv2.FONT_HERSHEY_SIMPLEX
        self.fps=0
        self.counter=0
        self.start=time.time()

        cv2.namedWindow("Intel RealSense D435",
                        cv2.WINDOW_NORMAL|cv2.WINDOW_KEEPRATIO|cv2.WINDOW_GUI_NORMAL)
        cv2.resizeWindow("Intel RealSense D435",1600,900)

    def update_fps(self):
        self.counter+=1
        if time.time()-self.start>=1:
            self.fps=self.counter/(time.time()-self.start)
            self.counter=0
            self.start=time.time()

    def convert_depth(self,img):
        img=cv2.convertScaleAbs(img,alpha=0.03)
        return cv2.applyColorMap(img,cv2.COLORMAP_JET)

    def convert_ir(self,img):
        return cv2.cvtColor(img,cv2.COLOR_GRAY2BGR)

    def draw_title(self,img,text,color):
        cv2.putText(img,text,(20,42),self.font,1,color,2,cv2.LINE_AA)

    def create_panel(self,height,camera,jetson):
        panel=np.zeros((height,260,3),dtype=np.uint8)
        now=datetime.now()
        temps=jetson.temperatures()
        info=[
            "Intel RealSense D435","",
            f"Fecha   {now:%d/%m/%Y}",
            f"Hora    {now:%H:%M:%S}",
            f"FPS     {self.fps:.2f}",
            f"Resol.  {camera.width}x{camera.height}",
            f"Config. {camera.fps_config} FPS"
        ]
        try:
            t=camera.depth_sensor.get_option(rs.option.asic_temperature)
            info.append(f"ASIC    {t:.1f} C")
        except Exception:
            pass
        info.append('')
        info.append('Jetson')
        
        for k,l in [('CPU-therm','CPU'),('GPU-therm','GPU'),('SOC0-therm','SOC'),('Tboard_tegra','Board')]:
            if k in temps: info.append(f'{l:<7} {temps[k]:.1f} C')
        y=30
        for txt in info:
            if txt=="Intel RealSense D435":
                cv2.putText(panel,txt,(10,y),self.font,0.65,YELLOW,2,cv2.LINE_AA)
                y+=25
                cv2.line(panel,(10,y),(245,y),GRAY,1)
                y+=25
            else:
                cv2.putText(panel,txt,(10,y),self.font,0.5,WHITE,1,cv2.LINE_AA)
                y+=28
        return panel

    def show(self,camera,jetson,color_f,depth_f,irl_f,irr_f):
        self.update_fps()
        color=np.asanyarray(color_f.get_data())
        depth=self.convert_depth(np.asanyarray(depth_f.get_data()))
        irl=self.convert_ir(np.asanyarray(irl_f.get_data()))
        irr=self.convert_ir(np.asanyarray(irr_f.get_data()))

        self.draw_title(color,"RGB",GREEN)
        self.draw_title(depth,"DEPTH",WHITE)
        self.draw_title(irl,"IR LEFT",GREEN)
        self.draw_title(irr,"IR RIGHT",GREEN)

        top=np.hstack((color,depth))
        bottom=np.hstack((irl,irr))
        streams=np.vstack((top,bottom))
        panel=self.create_panel(streams.shape[0],camera,jetson)
        window=np.hstack((panel,streams))
        cv2.imshow("Intel RealSense D435",window)

class App:
    def __init__(self):
        self.camera=RealSenseCamera()
        self.display=DisplayManager()
        self.jetson=JetsonMonitor()

    def run(self):
        print("Presione 'q' para salir.")
        try:
            while True:
                frames=self.camera.get_frames()
                if not all(frames):
                    continue
                self.display.show(self.camera,self.jetson,*frames)
                if cv2.waitKey(1)&0xFF==ord("q"):
                    break
        finally:
            self.camera.stop()
            cv2.destroyAllWindows()

if __name__=="__main__":
    App().run()
