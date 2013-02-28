import sys
import time
import ctypes
import logging
import Queue
import multiprocessing as mp
import numpy as np
import pyglet
import simple_tif
from arrayimage import ArrayInterfaceImage

"""
Add a real description here!
"""


log = mp.get_logger()
info = log.info
debug = log.debug
if sys.platform == 'win32':
    clock = time.clock
else:
    clock = time.time

class Image_Data_Pipeline:
    def __init__(
        self,
        num_data_buffers=100,
        buffer_shape=(60, 256, 512),
        ):
        """
        Allocate a bunch of 16-bit buffers for image data, and a few
        8-bit buffers for display data.
        """
        self.buffer_shape = buffer_shape
        self.num_data_buffers = num_data_buffers
        
        pix_per_buf = np.prod(buffer_shape)
        self.data_buffers = [mp.Array(ctypes.c_uint16, pix_per_buf)
                             for b in range(num_data_buffers)]
        self.idle_buffers = range(num_data_buffers)
        
        self.accumulation_buffers = [mp.Array(ctypes.c_uint16, pix_per_buf)
                                     for b in range(2)]

        pix_per_display_buf = np.prod(buffer_shape[1:])
        self.display_buffers = [mp.Array(ctypes.c_uint16, pix_per_display_buf)
                                for b in range(2)]

        """
        Lauch the child processes that make up the pipeline
        """
        self.camera = Data_Pipeline_Camera(
            data_buffers=self.data_buffers, buffer_shape=self.buffer_shape)
        self.accumulation = Data_Pipeline_Accumulation(
            data_buffers=self.data_buffers, buffer_shape=self.buffer_shape,
            accumulation_buffers=self.accumulation_buffers,
            input_queue=self.camera.output_queue)
        self.file_saving = Data_Pipeline_File_Saving(
            data_buffers=self.data_buffers, buffer_shape=self.buffer_shape,
            input_queue=self.accumulation.output_queue)
        
        self.projection = Data_Pipeline_Projection(
            buffer_shape=self.buffer_shape,
            display_buffers=self.display_buffers,
            accumulation_buffers=self.accumulation_buffers,
            accumulation_buffer_input_queue=
            self.accumulation.accumulation_buffer_output_queue,
            accumulation_buffer_output_queue=
            self.accumulation.accumulation_buffer_input_queue)
        self.display = Data_Pipeline_Display(
            display_buffers=self.display_buffers,
            buffer_shape=self.buffer_shape,
            display_buffer_input_queue=
            self.projection.display_buffer_output_queue,
            display_buffer_output_queue=
            self.projection.display_buffer_input_queue)
        return None
    
    def load_data_buffers(self, N, timeout=0):
        """
        Feed the pipe!
        """
        for i in range(N):
            for tries in range(10):
                try:
                    self.camera.input_queue.put(self.idle_buffers.pop(0))
                    break
                except IndexError:
                    time.sleep(timeout * 0.1)
            else:
                raise UserWarning("Timeout exceeded")

    def collect_data_buffers(self):
        while True:
            try:
                self.idle_buffers.append(
                    self.file_saving.output_queue.get_nowait())
            except Queue.Empty:
                break
            else:
                info("Buffer %i idle"%(self.idle_buffers[-1]))
        return None

    def close(self):
        self.camera.input_queue.put(None)
        self.accumulation.input_queue.put(None)
        self.file_saving.input_queue.put(None)
        self.projection.display_buffer_input_queue.put(None)
        self.projection.accumulation_buffer_input_queue.put(None)
        self.display.display_buffer_input_queue.put(None)
        self.camera.child.join()
        self.accumulation.child.join()
        self.file_saving.child.join()
        self.projection.child.join()
        self.display.child.join()
        return None

class Data_Pipeline_Camera:
    def __init__(
        self,
        data_buffers,
        buffer_shape,
        input_queue=None,
        output_queue=None,
        ):
        if input_queue is None:
            self.input_queue = mp.Queue()
        else:
            self.input_queue = input_queue

        if output_queue is None:
            self.output_queue = mp.Queue()
        else:
            self.output_queue = output_queue

        self.commands, self.child_commands = mp.Pipe()

        self.child = mp.Process(
            target=camera_child_process,
            args=(data_buffers, buffer_shape,
                  self.input_queue, self.output_queue,
                  self.child_commands),
            name='Camera')
        self.child.start()
        return None

def camera_child_process(
    data_buffers,
    buffer_shape,
    input_queue,
    output_queue,
    commands,
    ):
    data = [np.zeros(buffer_shape, dtype=np.uint16)
            for i in range(100)]
    for i, d in enumerate(data):
        d.fill(int((2**16 - 1) * (i + 1.0) / len(data)))
    data_idx = -1
    while True:
        try:
            process_me = input_queue.get_nowait()
        except Queue.Empty:
            time.sleep(0.0005)
            continue
        if process_me is None:
            break #We're done
        else:
            """Fill the buffer with something"""
            info("start buffer %i"%(process_me))
            with data_buffers[process_me].get_lock():
                a = np.frombuffer(data_buffers[process_me].get_obj(),
                                  dtype=np.uint16).reshape(buffer_shape)
##                a.fill(1)
                data_idx += 1
                data_idx = data_idx %len(data)
                a[:] = data[data_idx]
##            time.sleep(0.013)
            info("end buffer %i"%(process_me))
            output_queue.put(process_me)
    return None

class Data_Pipeline_Accumulation:
    def __init__(
        self,
        data_buffers,
        buffer_shape,
        accumulation_buffers,
        input_queue=None,
        output_queue=None,
        ):
        if input_queue is None:
            self.input_queue = mp.Queue()
        else:
            self.input_queue = input_queue

        if output_queue is None:
            self.output_queue = mp.Queue()
        else:
            self.output_queue = output_queue

        self.commands, self.child_commands = mp.Pipe()
        self.accumulation_buffer_input_queue = mp.Queue()
        self.accumulation_buffer_output_queue = mp.Queue()

        self.child = mp.Process(
            target=accumulation_child_process,
            args=(data_buffers, buffer_shape, accumulation_buffers,
                  self.input_queue, self.output_queue, self.child_commands,
                  self.accumulation_buffer_input_queue,
                  self.accumulation_buffer_output_queue),
            name='Accumulation')
        self.child.start()
        return None

def accumulation_child_process(
    data_buffers,
    buffer_shape,
    accumulation_buffers,
    data_buffer_input_queue,
    data_buffer_output_queue,
    commands,
    accumulation_buffer_input_queue,
    accumulation_buffer_output_queue,
    ):
    current_accumulation_buffer = 0
    num_accumulated = 0
    accumulation_buffer_input_queue.put(1)
    accumulation_buffer_occupied = False
    while True:
        if accumulation_buffer_occupied:
            try: #Check for a pending accumulation buffer
                switch_to_me = accumulation_buffer_input_queue.get_nowait()
            except Queue.Empty: #Keep accumulating to the current buffer
                pass
            else: #We got one! Switch to using the fresh accumulation buffer
                accumulation_buffer_output_queue.put(
                    int(current_accumulation_buffer))
                current_accumulation_buffer = switch_to_me
                info("Sending accumulation buffer with %i timepoint(s)"%(
                    num_accumulated))
                accumulation_buffer_occupied = False
                num_accumulated = 0
        try: #Check for a pending data buffer
            process_me = data_buffer_input_queue.get_nowait()
        except Queue.Empty: #Nothing pending. Back to square one.
            time.sleep(0.0005)
            continue
        if process_me is None: #Poison pill. Quit!
            break
        else:
            """Accumulate the data buffer"""
            info("start buffer %i"%(process_me))
            with data_buffers[process_me].get_lock():
                data = np.frombuffer(
                    data_buffers[process_me].get_obj(),
                    dtype=np.uint16).reshape(buffer_shape)
                with accumulation_buffers[
                    current_accumulation_buffer].get_lock():
                    a_b = np.frombuffer(accumulation_buffers[
                        current_accumulation_buffer].get_obj(),
                        dtype=np.uint16).reshape(buffer_shape)
                    if accumulation_buffer_occupied: #Accumulate
                        np.maximum(data, a_b, out=a_b)
                    else: #First accumulation; copy.
                        a_b[:] = data
                        accumulation_buffer_occupied = True
            num_accumulated += 1
            data_buffer_output_queue.put(process_me)
            info("end buffer %i"%(process_me))
    return None

class Data_Pipeline_Projection:
    def __init__(
        self,
        buffer_shape,
        display_buffers,
        accumulation_buffers,
        accumulation_buffer_input_queue,
        accumulation_buffer_output_queue,
        ):

        self.accumulation_buffer_input_queue = accumulation_buffer_input_queue
        self.accumulation_buffer_output_queue = accumulation_buffer_output_queue

        self.commands, self.child_commands = mp.Pipe()
        self.display_buffer_input_queue = mp.Queue()
        self.display_buffer_output_queue = mp.Queue()

        self.child = mp.Process(
            target=projection_child_process,
            args=(buffer_shape, display_buffers, accumulation_buffers,
                  self.child_commands,
                  self.display_buffer_input_queue,
                  self.display_buffer_output_queue,
                  self.accumulation_buffer_input_queue,
                  self.accumulation_buffer_output_queue),
            name='Projection')
        self.child.start()
        return None

def projection_child_process(
    buffer_shape,
    display_buffers,
    accumulation_buffers,
    commands,
    display_buffer_input_queue,
    display_buffer_output_queue,
    accumulation_buffer_input_queue,
    accumulation_buffer_output_queue,
    ):
    while True:
        try: #Get a pending display buffer
            fill_me = display_buffer_input_queue.get_nowait()
        except Queue.Empty:
            time.sleep(0.0005)
            continue #Don't bother with other stuff!
        if fill_me is None: #Poison pill. Quit!
            break
        else: 
            info("Display buffer %i received"%(fill_me))
            while True:
                try: #Now get a pending accumulation buffer
                    project_me = accumulation_buffer_input_queue.get_nowait()
                except Queue.Empty: #Nothing pending. Keep trying.
                    time.sleep(0.0005)
                    continue
                if project_me is None: #Poison pill. Quit!
                    break
                else:
                    """Project the accumulation buffer"""
                    info("start accumulation buffer %i"%(project_me))
                    with accumulation_buffers[project_me].get_lock():
                        acc = np.frombuffer(
                            accumulation_buffers[project_me].get_obj(),
                            dtype=np.uint16).reshape(buffer_shape)
                        with display_buffers[fill_me].get_lock():
                            disp = np.frombuffer(
                                display_buffers[fill_me].get_obj(),
                                dtype=np.uint16).reshape(buffer_shape[1:])
                            np.amax(acc, axis=0, out=disp) #Project
                    info("end accumulation buffer %i"%(project_me))
                    accumulation_buffer_output_queue.put(project_me)
                    info("Returning display buffer %i"%(fill_me))
                    display_buffer_output_queue.put(fill_me)
                    break #Go back and look for the next display buffer
    return None

class Data_Pipeline_Display:
    def __init__(
        self,
        display_buffers,
        buffer_shape,
        display_buffer_input_queue,
        display_buffer_output_queue,
        ):
        self.display_buffer_input_queue = display_buffer_input_queue
        self.display_buffer_output_queue = display_buffer_output_queue

        self.commands, self.child_commands = mp.Pipe()

        self.child = mp.Process(
            target=display_child_process,
            args=(display_buffers, buffer_shape,
                  self.display_buffer_input_queue,
                  self.display_buffer_output_queue,
                  self.child_commands),
            name='Display')
        self.child.start()
        return None

def display_child_process(
    display_buffers,
    buffer_shape,
    input_queue,
    output_queue,
    commands,
    ):
    args = locals()
    display = Display(**args)
    display.run()
    return None

class Display:
    def __init__(
        self,
        display_buffers,
        buffer_shape,
        input_queue,
        output_queue,
        commands):
        
        self.display_buffers = display_buffers
        self.buffer_shape = buffer_shape
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.commands = commands

        self.make_linear_lookup_table(display_min=0, display_max=2**16-1)

        self.current_display_buffer = 1
        self.switch_buffers(0)
        self.convert_to_8_bit()

        self.window = pyglet.window.Window(
            self.image.width, self.image.height,
            caption='Display', resizable=False)
        self.image_scale = 1
        self.image_x, self.image_y = 0, 0
        @self.window.event
        def on_draw():
            self.window.clear()
            self.image.blit(
                x=self.image_x, y=self.image_y,
                height=int(self.image.height * self.image_scale),
                width=int(self.image.width * self.image_scale))

        update_interval_seconds = 0.025
        pyglet.clock.schedule_interval(self.update, update_interval_seconds)
        return None

    def run(self):
        """
        Eventually put code here to deal with closing and re-opening the window.
        """
        pyglet.app.run()
        return None

    def quit(self):
        pyglet.app.exit()
        return None

    def update(self, dt):
        try:
            switch_to_me = self.input_queue.get_nowait()
        except Queue.Empty:
            return None
        if switch_to_me is None: #Poison pill. Quit!
            self.quit()
        else:
            self.switch_buffers(switch_to_me)
            self.convert_to_8_bit()

        return None

    def switch_buffers(self, switch_to_me):
        """
        Lock the new buffer, give up the old one.
        """
        info("Display buffer %i received"%(switch_to_me))
        self.display_buffers[switch_to_me].get_lock().acquire()
        try:
            self.display_buffers[self.current_display_buffer
                                 ].get_lock().release()
        except AssertionError:
            info("First time releasing lock")
            pass #First time through, we don't have the lock yet.
        self.output_queue.put(int(self.current_display_buffer))
        info("Display buffer %i loaded to projection process"%(
            self.current_display_buffer))
        self.current_display_buffer = int(switch_to_me)
        self.display_data_16 = np.frombuffer(
            self.display_buffers[self.current_display_buffer].get_obj(),
            dtype=np.uint16).reshape(self.buffer_shape[1:])
        return None

    def convert_to_8_bit(self):
        """
        Convert 16-bit display data to 8-bit using a lookup table.
        """
        if not hasattr(self, 'display_data_8'):
            self.display_data_8 = np.empty(
                self.buffer_shape[1:], dtype=np.uint8)            
        np.take(self.lut, self.display_data_16, out=self.display_data_8)
        self.image = ArrayInterfaceImage(self.display_data_8, allow_copy=False)
        pyglet.gl.glTexParameteri( #Reset to no interpolation
                pyglet.gl.GL_TEXTURE_2D,
                pyglet.gl.GL_TEXTURE_MAG_FILTER,
                pyglet.gl.GL_NEAREST)
        return None

    def make_linear_lookup_table(self, display_min, display_max):
        """
        Waaaaay faster than how I was doing it before.
        http://stackoverflow.com/q/14464449/513688
        """
        if not hasattr(self, '_lut_start'):
            self._lut_start = np.arange(2**16, dtype=np.uint16)
        if not hasattr(self, '_lut_intermediate'):
            self._lut_intermediate = self._lut_start.copy()
        if not hasattr(self, 'lut'):
            self.lut = np.empty(2**16, dtype=np.uint8)
        np.clip(self._lut_start, display_min, display_max,
                out=self._lut_intermediate)
        self._lut_intermediate -= display_min
        self._lut_intermediate //= (display_max - display_min + 1.) / 256.
        self.lut[:] = self._lut_intermediate.view(np.uint8)[::2]
        return None

class Data_Pipeline_File_Saving:
    def __init__(
        self,
        data_buffers,
        buffer_shape,
        input_queue=None,
        output_queue=None,
        ):
        if input_queue is None:
            self.input_queue = mp.Queue()
        else:
            self.input_queue = input_queue

        if output_queue is None:
            self.output_queue = mp.Queue()
        else:
            self.output_queue = output_queue

        self.commands, self.child_commands = mp.Pipe()

        self.child = mp.Process(
            target=file_saving_child_process,
            args=(data_buffers, buffer_shape,
                  self.input_queue, self.output_queue, self.child_commands),
            name='File Saving')
        self.child.start()
        return None

def file_saving_child_process(
    data_buffers,
    buffer_shape,
    input_queue,
    output_queue,
    commands,
    ):
    while True:
        try:
            process_me = input_queue.get_nowait()
        except Queue.Empty:
            time.sleep(0.0005)
            continue
        if process_me is None:
            break
        else:
            """Copy the buffer to disk"""
            info("start buffer %i"%(process_me))
            with data_buffers[process_me].get_lock():
                a = np.frombuffer(data_buffers[process_me].get_obj(),
                                  dtype=np.uint16).reshape(buffer_shape)
##                simple_tif.array_to_tif(a, 'out.tif')
            info("end buffer %i"%(process_me))
            output_queue.put(process_me)
    return None
