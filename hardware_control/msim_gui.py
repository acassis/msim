import os
##import time
import logging
import ConfigParser
import datetime
import multiprocessing as mp
import Tkinter as tk
import tkMessageBox
import tkFileDialog
##import numpy as np
from image_data_pipeline import Image_Data_Pipeline
from dmd import ALP

##if sys.platform == 'win32':
##    clock = time.clock
##else:
##    clock = time.time

class GUI:
    def __init__(self):
        logger = mp.log_to_stderr()
        logger.setLevel(logging.INFO)
        self.data_pipeline = Image_Data_Pipeline(
            num_buffers=5,
            buffer_shape=(224, 480, 480))
        self.dmd = ALP()
        self.root = tk.Tk()
        try:
            self.root.iconbitmap(default='microscope.ico')
        except tk.TclError:
            print "WARNING: Icon file 'microscope.ico' not found."
        self.root.report_callback_exception = self.report_callback_exception
        self.root.title("MSIM controls")

        self.menubar = tk.Menu(self.root)
        self.filemenu = tk.Menu(self.menubar, tearoff=0)
        self.filemenu.add_command(label="Exit", command=self.root.destroy)
        self.menubar.add_cascade(label="File", menu=self.filemenu)
        self.settingsmenu = tk.Menu(self.menubar, tearoff=0)
        self.settingsmenu.add_command(
            label="Display", command=self.open_display_settings_window)
        self.settingsmenu.add_command(
            label="Brightfield mode", command=self.open_brightfield_window)
        self.settingsmenu.add_command(
            label="Emission filters", command=self.open_filter_window)
        self.menubar.add_cascade(label="Settings", menu=self.settingsmenu)
        self.root.config(menu=self.menubar)

        self.lasers = ['561', '488']
        self.emission_filters = {}
        for c in self.lasers:
            self.emission_filters[c] = tk.StringVar()
            self.emission_filters[c].set('Filter 3')

        self.laser_power = {}
        self.laser_on = {}
        self.lake_info = {}
        frame = tk.Frame(self.root, bd=4, relief=tk.SUNKEN)
        frame.pack(side=tk.TOP, fill=tk.BOTH, expand=1)
        a = tk.Label(frame, text='Snap settings:')
        a.pack(side=tk.TOP)
        for c in self.lasers:
            subframe = tk.Frame(frame)
            subframe.pack(side=tk.TOP, fill=tk.BOTH, expand=1)
            a = tk.Label(subframe, text='Laser power:\n'+c+' nm (%)')
            a.pack(side=tk.LEFT)
            self.laser_power[c] = Scale_Spinbox(
                subframe, from_=0.1, to=100, increment=0.1, initial_value=100)
            self.laser_power[c].spinbox.config(width=5)
            self.laser_power[c].pack(side=tk.LEFT, fill=tk.BOTH, expand=1)
            self.laser_on[c] = tk.IntVar()
            a = tk.Checkbutton(subframe, text='',
                               variable=self.laser_on[c])
            if c == '488':
                self.laser_on[c].set(1)
            else:
                self.laser_on[c].set(0)
            a.pack(side=tk.LEFT)
            self.lake_info[c] = {}
            self.lake_info[c]['button'] = tk.Button(
                subframe, text='Calibrate',bg='red', fg='white',
                command=lambda: self.root.after_idle(
                    lambda: self.calibrate(c)))
            self.lake_info[c]['button'].pack(side=tk.LEFT)

##        self.exposure_time_milliseconds = 4.5
##        subframe = Tk.Frame(frame)
##        subframe.pack(side=tk.TOP, fill=tk.BOTH, expand=1)
##        self.galvo_num_sweeps_label = Tk.Label(subframe, text='')
##        self.galvo_num_sweeps_label.pack(side=Tk.LEFT)
##        self.num_galvo_sweeps = Scale_Spinbox(
##            subframe, from_=1, to=50, increment=1, initial_value=2)
##        self.num_galvo_sweeps.spinbox.config(width=2)
##        self.num_galvo_sweeps.bind(
##            "<<update>>", lambda x: self.root.after_idle(
##                self.set_num_galvo_sweeps))
##        self.num_galvo_sweeps.pack(side=Tk.LEFT, fill=Tk.BOTH, expand=1)
##        self.galvo_num_sweeps_label.config(
##            text='Exposure:\n%i sweeps\n%0.2f ms each\n%0.2f ms total'%(
##                self.num_galvo_sweeps.get(), self.galvo_sweep_milliseconds,
##                self.num_galvo_sweeps.get()* self.galvo_sweep_milliseconds))
##        a.pack(side=Tk.LEFT)
        self.snap_button = tk.Button(
            master=frame, text='Snap', bg='gray1', fg='white', font=60,
            command=lambda: self.root.after_idle(self.snap))
        self.snap_button.bind(
            "<Button-1>", lambda x: self.snap_button.focus_set())
        self.snap_button.pack(side=tk.TOP)

        frame = tk.Frame(self.root)
        frame.pack(side=tk.TOP)
        
        a.pack(side=tk.LEFT)
        a = tk.Button(
            frame, text="Load buffers",
            command=self.load_buffers)
        a.pack(side=tk.LEFT)
        
        self.file_num = 0
        a = tk.Button(
            frame, text="Load buffers and save",
            command=self.load_and_save)
        a.pack(side=tk.LEFT)

        self.data_pipeline.set_display_intensity_scaling(
            'median_filter_autoscale', display_min=0, display_max=0)
        self.root.after(50, self.load_config)
        self.root.mainloop()
        self.data_pipeline.close()
        return None

    def load_buffers(self):
        self.data_pipeline.collect_data_buffers()
        self.data_pipeline.load_data_buffers(
            len(self.data_pipeline.idle_buffers))
        return None

    def load_and_save(self):
        self.data_pipeline.collect_data_buffers()
        num_buffers = len(self.data_pipeline.idle_buffers)
        file_info = []
        for b in self.data_pipeline.idle_buffers:
            file_info.append(
                {'buffer_number': b,
                 'outfile': 'image_%06i.tif'%(self.file_num)
                 })
            self.file_num += 1
        self.data_pipeline.load_data_buffers(
            num_buffers, file_saving_info=file_info)
        return None

    def open_display_settings_window(self):
        try:
            self.display_settings_window.root.config()
        except (AttributeError, tk.TclError):
            self.display_settings_window = Display_Settings_Window(self)
        self.display_settings_window.root.lift()
        self.display_settings_window.root.focus_force()
        return None

    def open_brightfield_window(self):
        """TODO"""
        return None

    def open_filter_window(self):
        try:
            self.filter_window.root.config()
        except (AttributeError, tk.TclError):
            self.filter_window = Filter_Window(self)
        self.filter_window.root.lift()
        self.filter_window.root.focus_force()
        return None

    def report_callback_exception(self, *args):
        import traceback
        err = traceback.format_exception(*args)
        with open(os.path.join(
            os.getcwd(),
            'error_log_gui.txt'), 'ab') as error_log:
            for e in err:
                error_log.write(e + os.linesep)
            error_log.write(os.linesep*2)
        tkMessageBox.showerror(
            'Exception',
            'An exception occured. ' +
            'Read "error_log.txt" in:\n' +
            repr(os.getcwd()) +
            '\nfor details."')
        return None

    def load_config(self):
        self.config = ConfigParser.RawConfigParser()
        self.config.read(os.path.join(os.getcwd(), 'config.ini'))
        while True:
            """Try to get the path to the ImageJ executable"""
            try:
                imagej_path = self.config.get('ImageJ', 'path')
                assert os.path.basename(imagej_path).lower() == 'imagej.exe'
                break
            except ConfigParser.NoSectionError:
                self.config.add_section('ImageJ')
            except ConfigParser.NoOptionError:
                imagej_path = str(os.path.normpath(tkFileDialog.askopenfilename(
                    title="Where is the ImageJ executable?",
                    filetypes=[('Executable', '.exe')],
                    defaultextension='.raw',
                    initialdir=os.getcwd(),
                    initialfile='ImageJ.exe'))) #Careful about Unicode here!
                self.config.set('ImageJ', 'path', imagej_path)
            except AssertionError:
                try_again = tkMessageBox.askretrycancel(
                    'ImageJ executable is weird',
                    'Try again?')
                if try_again:
                    self.config.remove_option('ImageJ', 'path')
                else:
                    break
        """Try to get path and age of the lake calibration data"""
        now = datetime.datetime.now()
        for c in self.lasers:
            try:
                self.lake_info[c]['path'] = self.config.get(
                    c + ' calibration', 'path')
                self.lake_info[c]['date'] = self.config.get(
                    c + ' calibration', 'date').split()
                assert os.path.exists(self.lake_info[c]['path'])
            except (ConfigParser.NoSectionError,
                    ConfigParser.NoOptionError,
                    AssertionError) as e:
                continue
            try:
                lake_date = datetime.datetime(
                    *[int(i) for i in self.lake_info[c]['date']])
                print lake_date
            except TypeError:
                continue
            if abs((lake_date - now).total_seconds()) > 85400:
                print "Yellow"
                """The lake data exists, but is more than one day old"""
                self.lake_info[c]['button'].config(bg='yellow', fg='black')
            else:
                print "Gray"
                self.lake_info[c]['button'].config(bg='gray', fg='black')
                
        with open('config.ini', 'w') as configfile:
            self.config.write(configfile)
        return None

    def calibrate(self, color):
        calibration_window = Calibration_Window(self, color)
        return None

    def snap(self):
        return None

class Display_Settings_Window:
    def __init__(self, parent):
        self.parent = parent
        self.root = tk.Toplevel(parent.root)
        self.root.wm_title("Display settings")
        self.root.bind("<Escape>", lambda x: self.root.destroy())

        scaling, display_min, display_max = (
            self.parent.data_pipeline.get_display_intensity_scaling())

        frame = tk.Frame(self.root, relief=tk.SUNKEN, bd=4)
        frame.pack(side=tk.TOP, fill=tk.BOTH, expand=1)
        a = tk.Label(frame, text="Contrast settings:")
        a.pack(side=tk.TOP)
        subframe = tk.Frame(frame)
        subframe.pack(side=tk.TOP, fill=tk.BOTH)
        a = tk.Label(master=subframe, text='Lower\nlimit:')
        a.pack(side=tk.LEFT)
        self.display_min = Scale_Spinbox(
            subframe, from_=0, to=(2**16 - 1), initial_value=display_min)
        self.display_min.bind(
            "<<update>>", lambda x: self.set_scaling())
        self.display_min.pack(side=tk.LEFT, fill=tk.BOTH, expand=1)
        subframe = tk.Frame(frame)
        subframe.pack(side=tk.TOP, fill=tk.BOTH)
        a = tk.Label(master=subframe, text='Upper\nlimit:')
        a.pack(side=tk.LEFT)
        self.display_max = Scale_Spinbox(
            subframe, from_=0, to=(2**16 - 1), initial_value=display_max)
        self.display_max.bind(
            "<<update>>", lambda x: self.set_scaling())
        self.display_max.pack(side=tk.LEFT, fill=tk.BOTH, expand=1)
        subframe = tk.Frame(frame)
        subframe.pack(side=tk.TOP, fill=tk.BOTH)
        a = tk.Label(master=subframe, text='Mode:')
        a.pack(side=tk.LEFT)
        self.scaling = tk.StringVar()
        self.scaling.set(scaling)
        button = tk.Radiobutton(
            master=subframe, text='Linear', variable=self.scaling,
            value='linear', indicatoron=0,
            command=lambda: self.root.after_idle(self.set_scaling))
        button.pack(side=tk.LEFT)
        button = tk.Radiobutton(
            master=subframe, text='Autoscale', variable=self.scaling,
            value='autoscale', indicatoron=0,
            command=lambda: self.root.after_idle(self.set_scaling))
        button.pack(side=tk.LEFT)
        button = tk.Radiobutton(
            master=subframe, text='Median autoscale', variable=self.scaling,
            value='median_filter_autoscale', indicatoron=0,
            command=lambda: self.root.after_idle(self.set_scaling))
        button.pack(side=tk.LEFT)

        self.update_scaling()
        return None
    
    def set_scaling(self):
        self.parent.data_pipeline.set_display_intensity_scaling(
            self.scaling.get(),
            display_min=self.display_min.get(),
            display_max=self.display_max.get())
        """
        Now we make sure the changes were accepted.
        """
        scaling, display_min, display_max = (
            self.parent.data_pipeline.get_display_intensity_scaling())
        self.scaling.set(scaling)
        self.display_min.set(int(display_min), update_trigger=False)
        self.display_max.set(int(display_max), update_trigger=False)
        return None

    def update_scaling(self):
        scaling, display_min, display_max = (
            self.parent.data_pipeline.get_display_intensity_scaling())
        if scaling == 'autoscale' or scaling == 'median_filter_autoscale':
            self.display_min.set(display_min)
            self.display_max.set(display_max)
        self.root.after(400, self.update_scaling)
        return None

class Filter_Window:
    def __init__(self, parent):
        self.parent = parent
        self.root = tk.Toplevel(parent.root)
        self.root.wm_title("Emission filter settings")
        self.root.bind("<Escape>", lambda x: self.root.destroy())

        a = tk.Label(self.root, text="Emission filter settings:")
        a.pack(side=tk.TOP)
        for c in self.parent.lasers:
            frame = tk.Frame(self.root)
            frame.pack(side=tk.TOP, fill=tk.BOTH)
            a = tk.Label(master=frame, text=c + ' nm laser\nemission filter:')
            a.pack(side=tk.LEFT)
            a = tk.OptionMenu(frame, self.parent.emission_filters[c],
                              *['Filter %i'%i for i in range(1, 7)])
            a.pack(side=tk.LEFT)
        return None

class Calibration_Window:
    def __init__(self, parent, color):
        self.parent = parent
        self.color = color
        self.root = tk.Toplevel(parent.root)
        self.root.wm_title("Calibration")
        self.root.bind("<Escape>", lambda x: self.cancel())
        self.root.protocol("WM_DELETE_WINDOW", self.cancel)
        self.root.lift()
        self.root.focus_force()
        self.parent.root.withdraw()

        self.frame = tk.Frame(self.root)
        self.frame.pack(side=tk.TOP, fill=tk.BOTH)
        a = tk.Label(self.frame, text="Calibration mode.\n\n" +
                     "Put a fluorescent lake slide on the microscope.\n" +
                     "Click 'Ok' when the slide is in place.\n" +
                     "\nWARNING!\n\n" +
                     "Lasers will turn on when you press 'Ok'.")
        a.pack(side=tk.TOP)
        frame = tk.Frame(self.frame)
        frame.pack(side=tk.TOP)
        a = tk.Button(frame, text='Ok', command=self.alignment_mode)
        a.focus_set()
        a.bind('<Return>', lambda x: self.alignment_mode())
        a.pack(side=tk.LEFT)
        a = tk.Button(frame, text='Cancel', command=self.cancel)
        a.bind('<Return>', lambda x: self.cancel())
        a.pack(side=tk.LEFT)
        
        return None

    def alignment_mode(self):
        self.frame.pack_forget()
        self.frame = tk.Frame(self.root)
        self.frame.pack(side=tk.TOP, fill=tk.BOTH)
        a = tk.Label(self.frame, text="Calibration mode.\n\n" +
                     "Adjust the focus using the objective knob.\n" +
                     "You should see an array of spots.\n" +
                     "Click 'Ok' when the spots are visible.\n")
        a.pack(side=tk.TOP)
        frame = tk.Frame(self.frame)
        frame.pack(side=tk.TOP)
        a = tk.Button(frame, text='Ok', command=self.acquire_calibration)
        a.focus_set()
        a.bind('<Return>', lambda x: self.alignment_mode())
        a.pack(side=tk.LEFT)
        a = tk.Button(frame, text='Cancel', command=self.cancel)
        a.bind('<Return>', lambda x: self.cancel())
        a.pack(side=tk.LEFT)
        self.parent.data_pipeline.camera.commands.send((
            'frames_per_acquisition', {'frames_per_acquisition': 1}))
        assert self.parent.data_pipeline.camera.commands.recv() == 1
        self.parent.dmd.apply_settings(
            illuminate_time=2200,
            illumination_filename='alignment_pattern.raw')
        self.aligning = True
        self.play_alignment_pattern()
        return None

    def play_alignment_pattern(self):
        while len(self.parent.data_pipeline.idle_buffers) < 1:
            self.parent.data_pipeline.collect_data_buffers()
        self.parent.data_pipeline.load_data_buffers(1)
        self.parent.dmd.display_pattern()
        if self.aligning:
            self.root.after(50, self.play_alignment_pattern)
        return None

    def acquire_calibration(self):
        self.aligning = False
        self.parent.data_pipeline.camera.commands.send((
            'frames_per_acquisition',
            {'frames_per_acquisition': 'buffer_size'}))
        assert self.parent.data_pipeline.camera.commands.recv() == 'buffer_size'
        self.frame.pack_forget()
        self.frame = tk.Frame(self.root)
        self.frame.pack(side=tk.TOP, fill=tk.BOTH)
        a = tk.Label(self.frame, text="Calibration mode.\n\n" +
                     "Acquiring calibration...")
        a.pack(side=tk.TOP)
        a = tk.Button(self.frame, text='Cancel', command=self.cancel)
        a.bind('<Return>', lambda x: self.cancel())
        a.pack(side=tk.TOP)
        return None
    
    def cancel(self):
        self.root.withdraw()
        self.parent.root.deiconify()
        self.root.destroy()
        return None
    
class Scale_Spinbox:
    def __init__(self, master, from_, to, increment=1, initial_value=None):
        self.frame = tk.Frame(master)
        self.scale = tk.Scale(
            self.frame,
            from_=from_, to=to, resolution=increment,
            orient=tk.HORIZONTAL)
        for e in ("<FocusOut>", "<ButtonRelease-1>", "<Return>"):
            self.scale.bind(e, lambda x: self.set(self.scale.get()))

        self.spinbox_v = tk.StringVar()
        self.spinbox = tk.Spinbox(
            self.frame,
            from_=from_, to=to, increment=increment,
            textvariable=self.spinbox_v, width=6)
        for e in ("<FocusOut>", "<ButtonRelease-1>", "<Return>"):
            self.spinbox.bind(e, lambda x: self.frame.after_idle(
                lambda: self.set(self.spinbox_v.get())))
        
        self.set(initial_value)

        self.scale.pack(side=tk.LEFT, fill=tk.BOTH, expand=1)
        self.spinbox.pack(side=tk.LEFT)
        
    def pack(self, *args, **kwargs):
        return self.frame.pack(*args, **kwargs)

    def bind(self, *args, **kwargs):
        return self.frame.bind(*args, **kwargs)

    def get(self):
        return self.scale.get()

    def set(self, value=None, update_trigger=True):
        try:
            self.scale.set(value)
        except tk.TclError:
            pass
        self.spinbox_v.set(self.scale.get())
        if update_trigger: #Bind to this event for on-set
            self.frame.event_generate("<<update>>")
        return None


if __name__ == '__main__':
    GUI()