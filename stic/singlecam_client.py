import numpy as np
import cv2
import threading
import time
import argparse
import sys
import os
FileDirPath = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(FileDirPath, '..'))
import uvc
from sticradio.utilities import getCurrentEpochTime, makeCollage, StreamingMovingAverage
from sticradio import sticradio as sr
import struct
import asyncio
import websockets

Parser = argparse.ArgumentParser(description='Example singlecam client.')
Parser.add_argument('-o', '--hostname', help='Hostname or IP address.', type=str, default='localhost')
Parser.add_argument('-p', '--port', help='Port number on host.', type=str, default='8080')
Parser.add_argument('-i', '--id', help='Which camera ID to use.', type=int, required=False, default=0)

Cam = None
class SingleCamClient(sr.STICRadioClient):
    def __init__(self, Args):
        self.Args = Args
        super().__init__(Args.hostname, Args.port)
        self.init()

    def init(self):
        global Cam
        self.Lock = threading.Lock()
        self.FPS = 0
        self.Latency = 0
        self.Stop = False
        self.Cam = None
        self.WindowSize = 200
        self.FPSMovingAvg = StreamingMovingAverage(window_size=self.WindowSize)

        self.DeviceList = uvc.device_list()
        # random.shuffle(dev_list)
        self.nCams = len(self.DeviceList)
        assert self.nCams > 0
        self.CamIdx = list(range(self.nCams))
        assert self.Args.id in self.CamIdx
        print('Found {} cameras with indices: {}. Using camera with index {}.'.format(self.nCams, self.CamIdx, self.Args.id))
        Cam = uvc.Capture(self.DeviceList[self.Args.id]['uid'])
        # self.Cam = uvc.Capture(self.DeviceList[self.Args.id]['uid'])
        # controls_dict = dict([(c.display_name, c) for c in Cam.controls])
        print('Camera in Bus:ID -', self.DeviceList[self.Args.id]['uid'], 'supports the following modes:', Cam.available_modes)
        for Key in self.DeviceList[self.Args.id].keys():
            print(Key + ':', self.DeviceList[self.Args.id][Key])
        Cam.frame_mode = Cam.available_modes[1]
        print('Original camera bandwidth factor:', Cam.bandwidth_factor)
        Cam.bandwidth_factor = 0.5
        print('New camera bandwidth factor:', Cam.bandwidth_factor)

        self.ImagePayload = np.zeros((Cam.frame_mode[1], Cam.frame_mode[0], 3))

    async def event_loop(self):
        global Cam
        async with websockets.connect(self.URI) as websocket:
            print('[ INFO ]: Successfully connected to websocket server at', self.URI)

            while True:
                startTime = getCurrentEpochTime()
                Frame = Cam.get_frame_robust()
                ImageBytes = Frame.tobytes()
                SendData = struct.pack('Qs', startTime, ImageBytes)
                # print('Sending data at:', startTime)
                await websocket.send(SendData)
                ReceivedData = await websocket.recv()
                # print('Received Data:', ReceivedData)
                self.Latency = (getCurrentEpochTime() - int(ReceivedData))/2000
                print('Latency: {} milliseconds'.format(self.Latency))

                self.Lock.acquire()
                self.ImagePayload = np.copy(Frame.img)
                self.Lock.release()
                # CapturedFrames[num] = Cams[num].get_frame()
                # print("Cam: {} shape: {}".format(num, CapturedFrames[num].img.shape))
                endTime = getCurrentEpochTime()
                ElapsedTime = (endTime - startTime)
                if ElapsedTime < 1000:
                    time.sleep(0.001)  # Prevent CPU throttling
                    ElapsedTime += 1000
                self.Lock.acquire()
                CurrentFPS = 1e6 / (ElapsedTime)
                self.FPS = self.FPSMovingAvg + CurrentFPS
                self.Lock.release()
                # print('FPS:', num, math.floor(FPS[num]), flush=True)

                if self.Stop:
                    break


if __name__ == '__main__':
    # if len(sys.argv) == 1:
    #     Parser.print_help()
    #     exit()
    Args = Parser.parse_args()

    CamServer = SingleCamClient(Args)
    CamServer.start()