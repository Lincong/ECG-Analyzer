import matplotlib
import matplotlib.patches as patches
import sys
import os
import gc
import math
import Queue
import logging
import csv
matplotlib.use('TkAgg')
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2TkAgg
from matplotlib.figure import Figure
from matplotlib.widgets import RectangleSelector

DAT_FILE_NUM = 4
EXIT_SUCCESS = 0
EXIT_FAILURE = 1

STEP_ONE = 0  # select rectangle
STEP_TWO = 1  # draw vertical lines
STEP_THREE = 2  # draw vertical sync lines
STEP_FOUR = 3  # draw horizontal lines
STEP_FIVE = 4  # draw ROI

curr_step = STEP_ONE

disablers = {}
enablers = {}

WARNING_TITLE = "Warning"
WARNING_WINDOW_GEOMETRY = "200x100"
gc.enable()

if sys.version_info[0] < 3:
    import Tkinter as Tk
else:
    import tkinter as Tk

from tkFileDialog import askdirectory, asksaveasfile


whiteSpaceLength = 0.3
paddingLength = 0.1
VerticalLineNum = 5
OpEnabled = 1

userModes = ['Mark calibration box', 'Mark lead start/end', 'Mark Sync time in 4 columns',
             'Mark 3 zero reference voltages', 'Mark ROI']

root = Tk.Tk()
root.wm_title("ECG Analyzer 2.0")

# get screen width and height
ws = root.winfo_screenwidth()  # width of the screen
hs = root.winfo_screenheight()  # height of the screen

root.geometry('{}x{}+{}+{}'.format(int(ws*.8), int(hs*.8), int(ws*.1), int(hs*.1)))
f = Figure(figsize=(5, 4), dpi=100)
mainAx = f.add_subplot(111)

radioButtonState = Tk.IntVar()
radioButtonState.set(1)  # initialize

enableCheckBoxState = Tk.IntVar()
enableCheckBoxState.set(1)  # allow drawing
selectedOp = Tk.StringVar()
selectedOp.set(userModes[STEP_ONE])
drawVLineHandle = None
drawSyncLineHandle = None
drawHorizontalLineHandle = None

dataLoaded = False


# A class used to manage all input data and perform transformation on it
class AllRows(object):
    inputXY = None
    invertedInputXY = None
    plotHandles = None

    allXmax = 0
    allXmin = 0

    allYmax = 0
    allYmin = 0
    rowDistance = 20
    distanceFromBottom = 10
    isInverted = False

    def __init__(self):
        self.inputXY = []
        self.invertedInputXY = []
        self.plotHandles = []

    def mark_ROI_regions(self, x_start_offset, ROI_len, syncLineXs):
        XYs = None
        if self.isInverted:
            XYs = self.invertedInputXY
        else:
            XYs = self.inputXY

        for row in XYs:
            yMax = row.yMax
            yMin = row.yMin
            deltaY = yMax - yMin

            for syncLineX in syncLineXs:
                rectPatch = patches.Rectangle((syncLineX - x_start_offset, yMax), ROI_len, deltaY, alpha=0.3)
                mainAx.add_patch(rectPatch)

        canvas.draw()

    def addRow(self, xs, ys):

        row = OneRowXY(xs, ys)
        row.resetMaxMinAverage()
        self.inputXY.append(row)
        self.invertedInputXY.append(OneRowXY(xs, ys))

    # when this function is called. It means all data are stored in inputXY
    # This function 1. calculate the inverted version of the data and store it
    # 2. adjust the saved data
    def finishLoading(self):
        self.inputXY = self.adjustRows(self.inputXY)

        # find the global maximum Y
        for eachRow in self.inputXY:

            if self.allXmax < eachRow.xMax:
                self.allXmax = eachRow.xMax

            if self.allXmin > eachRow.xMin:
                self.allXmin = eachRow.xMin

            if self.allYmax < eachRow.yMax:
                self.allYmax = eachRow.yMax

        self.plotRows(self.inputXY)

        index = 0
        for eachRow in self.inputXY:
            self.invertedInputXY[index].ys = list(map(lambda y: (self.allYmax - y), eachRow.ys))
            self.invertedInputXY[index].xs = eachRow.xs
            self.invertedInputXY[index].resetMaxMinAverage()
            index += 1
        self.invertedInputXY = self.adjustRows(self.invertedInputXY)
        # at this point, both invertedInputXY and XY are sorted

    def plotRows(self, rows):
        for eachRow in rows:
            pltHandle, = mainAx.plot(eachRow.xs, eachRow.ys, color='black')
            self.plotHandles.append(pltHandle)

        mainAx.set_ylim([0, self.allYmax + 20])
        canvas.draw()
        self.isInverted = not self.isInverted

    def invert(self):
        # remove the current plot
        for eachHandle in self.plotHandles:
            eachHandle.remove()
        canvas.draw()
        self.plotHandles = []

        if self.isInverted:
            self.plotRows(self.invertedInputXY)
        else:
            self.plotRows(self.inputXY)

    def getCurrentPlotedXYs(self):
        if self.isInverted:
            return self.inputXY
        else:
            return self.invertedInputXY

    # adjust the position of these XY rows
    def adjustRows(self, rows):
        rows = sorted(rows)
        # shift the lowest line
        shiftUpOffset = self.distanceFromBottom - rows[0].yMin
        rows[0].ys = list(map(lambda y: (y + shiftUpOffset), rows[0].ys))
        rows[0].resetMaxMinAverage()
        prevYmax = 0
        index = 0

        for eachRow in rows:
            shiftUpOffset = (prevYmax + self.rowDistance) - eachRow.yMin
            eachRow.ys = list(map(lambda y: (y + shiftUpOffset), eachRow.ys))
            eachRow.resetMaxMinAverage()  # reset the max Y for each row
            prevYmax = eachRow.yMax
            rows[index] = eachRow
            index += 1

        return rows

    def reset(self):
        for eachHandle in self.plotHandles:
            eachHandle.remove()
        canvas.draw()

        self.inputXY = []
        self.invertedInputXY = []
        self.plotHandles = []
        self.allYmax = 0
        self.allYmin = 0
        self.allXmax = 0
        self.allXmin = 0
        self.rowDistance = 20
        self.distanceFromBottom = 10
        self.isInverted = False


class OneRowXY(object):
    xs = []
    ys = []
    yMin = 0
    yMax = 0
    yAve = 0

    xMin = 0
    xMax = 0

    def __init__(self, xs=None, ys=None):
        if ys is None:
            ys = []
        if xs is None:
            xs = []

        if len(xs) != len(ys):
            print 'This is weird. A row should have equal number of Xs and Ys'
            assert False

        self.xs = xs
        self.ys = ys
        self.yMin = min(ys)
        self.yMax = max(ys)
        self.xMin = min(xs)
        self.xMax = max(xs)
        self.yAve = reduce(lambda x, y: x + y, ys) / len(ys)

    def resetMaxMinAverage(self):
        self.yAve = reduce(lambda x, y: x + y, self.ys) / len(self.ys)
        self.yMin = min(self.ys)
        self.yMax = max(self.ys)
        self.xMin = min(self.xs)
        self.xMax = max(self.xs)

    # implement the comparing interface
    def __lt__(self, other):
        return self.yAve < other.yAve

    def __gt__(self, other):
        return self.yAve > other.yAve

    def __eq__(self, other):
        return self.yAve == other.yAve

    def __ne__(self, other):
        return not self.__eq__(other)


# for each vertical line
class VLine(object):
    lineX = 0
    handle = None

    def __init__(self, handle, x):
        self.handle = handle
        self.lineX = x


# for each horizontal line
class Hline(object):
    lineX = 0
    handle = None

    def __init__(self, handle, y):
        self.handle = handle
        self.lineY = y


# keep track of all vertical lines
class VLines(object):
    currVLineXs = None
    maxVerticalLineNUm = VerticalLineNum

    def __init__(self):
        self.currVLineXs = Queue.LifoQueue()
        # self.maxVerticalLineNUm = VerticalLineNum

    def addVerticalLine(self, vline):
        if self.maxVerticalLineNUm <= self.currVLineXs.qsize(): return  # full
        self.currVLineXs.put(vline)

    def deleteVerticalLine(self):
        if self.currVLineXs.empty():  # nothing to delete
            return False

        vline = self.currVLineXs.get()
        vline.handle.remove()
        canvas.draw()
        return True

    def deleteAll(self):
        while self.deleteVerticalLine() is True:
            continue

    def getXs(self):
        Xs = []
        vlines = []
        while not self.currVLineXs.empty():
            vline = self.currVLineXs.get()
            Xs.append(vline.lineX)
            vlines.append(vline)
        # put back into the queue
        for eachLine in vlines:
            self.currVLineXs.put(eachLine)

        Xs.sort()
        return Xs

    def vLinesReady(self):
        return self.maxVerticalLineNUm == self.currVLineXs.qsize()


# keep track of all sync lines
class VSyncLines(object):
    currSyncLineXs = None
    maxSyncLineNUm = VerticalLineNum - 1

    def __init__(self):
        self.currSyncLineXs = Queue.LifoQueue()
        # self.maxVerticalLineNUm = VerticalLineNum

    def addSyncLine(self, vline):
        if self.maxSyncLineNUm <= self.currSyncLineXs.qsize(): return  # full
        self.currSyncLineXs.put(vline)

    def deleteSyncLine(self):
        if self.currSyncLineXs.empty():  # nothing to delete
            return False

        vline = self.currSyncLineXs.get()
        vline.handle.remove()
        canvas.draw()
        return True

    def deleteAll(self):
        while self.deleteSyncLine() is True:
            continue

    def getXs(self):
        Xs = []
        vlines = []
        while not self.currSyncLineXs.empty():
            vline = self.currSyncLineXs.get()
            Xs.append(vline.lineX)
            vlines.append(vline)

        # put back into the queue
        for eachLine in vlines:
            self.currSyncLineXs.put(eachLine)

        Xs.sort()
        return Xs

    def vSyncLinesReady(self):
        return self.maxSyncLineNUm == self.currSyncLineXs.qsize()


# keep track of horizontal lines
class HLines(object):
    currYs = None
    maxHlineNum = 3


    def __init__(self):
        self.currYs = Queue.LifoQueue()
        # self.maxVerticalLineNUm = VerticalLineNum

    def addHLine(self, hline):
        if self.maxHlineNum <= self.currYs.qsize(): return  # full
        self.currYs.put(hline)

    def deleteHorizontalLine(self):
        if self.currYs.empty():  # nothing to delete
            return False

        hline = self.currYs.get()
        hline.handle.remove()
        canvas.draw()
        return True

    def deleteAll(self):
        while self.deleteHorizontalLine() is True:
            continue

    def getYs(self):
        Ys = []
        hlines = []
        while not self.currYs.empty():
            hline = self.currYs.get()
            Ys.append(hline.lineY)
            hlines.append(hline)

        # put back into the queue
        for eachLine in hlines:
            self.currYs.put(eachLine)

        Ys.sort()
        return Ys

    def HorizontalLinesReady(self):
        return self.maxHlineNum == self.currYs.qsize()


class CaliInfo(object):
    caliFactor1 = None
    caliFactor2 = None

    deltaX = None
    deltaY = None

    handle = None
    Yscale = None
    Xscale = None

    def __init__(self):
        self.resetAll()

    def setXY(self, info):
        self.deltaX = info[0]
        self.deltaY = info[1]

    def setCaliFactor(self, factors):
        self.voltageCalibrationFactor = factors[0]
        self.timeCalibrationFactor = factors[1]

        self.Yscale = float(self.voltageCalibrationFactor) / self.deltaY
        self.Xscale = float(self.timeCalibrationFactor) / self.deltaX

    def getCaliInfor(self):
        if self.handle is None:
            return None

        return [self.caliFactor1, self.caliFactor2, self.leftTopX, self.leftTopY, self.rightBottomX, self.rightBottomY]

    def setHandle(self, handle):
        self.handle = handle

    def caliInfoReady(self):
        return self.handle is not None
        # return (self.caliFactor1 is not None) and (self.caliFactor2 is not None) and \
        #        (self.leftTopX is not None) and (self.leftTopY is not None) and \
        #        (self.rightBottomX is not None) and (self.rightBottomY is not None) and \
        #        (self.handle is not None)

    def deleteRect(self):
        if self.handle is None:
            return
        self.handle.remove()
        canvas.draw()
        self.handle = None
        self.resetAll()

    def resetAll(self):
        self.leftTopX = None
        self.leftTopY = None
        self.rightBottomX = None
        self.rightBottomY = None
        self.caliFactor1 = None
        self.caliFactor2 = None


# global vars keeping track of current data and objects drew on the canvas
XYs = AllRows()
v_lines = VLines()
sync_lines = VSyncLines()
h_lines = HLines()
cali_info = CaliInfo()

# a tk.DrawingArea
canvas = FigureCanvasTkAgg(f, master=root)
canvas.show()
canvas.get_tk_widget().pack(side=Tk.BOTTOM, fill=Tk.BOTH, expand=10)

toolbar = NavigationToolbar2TkAgg(canvas, root)
toolbar.update()
canvas._tkcanvas.pack(side=Tk.TOP, fill=Tk.BOTH, expand=10)


def readXYfromFile(file_name):
    xs = []
    ys = []
    with open(file_name) as fp:
        for line in fp:
            xyStr = line.split()
            xs.append(float(xyStr[0]))
            ys.append(float(xyStr[1]))
    return xs, ys


def remindLoadingData():
    remindWindow(WARNING_TITLE, "Please use \'Browse\' button to load data first")


def remindWindow(title, content):
    top = Tk.Toplevel()
    top.geometry(WARNING_WINDOW_GEOMETRY)
    top.title(title)
    msg = Tk.Message(top, text=content)
    msg.pack()

    button = Tk.Button(top, text="OK", command=top.destroy)
    button.pack()
    return

# rowDistance: distance between the Y max and Y min of two adjacent rows
def plotRawDataFromDir(dir_name, rowDistance=20):
    allInputFiles = []
    try:
        allInputFiles = os.listdir(dir_name)
    except OSError:
        remindWindow('Error!', 'No such a directory')
        return EXIT_FAILURE

    global XYs, yMax, yMin

    allInputFiles = list(filter(lambda fn: ('.dat' in fn), allInputFiles))

    if len(allInputFiles) != DAT_FILE_NUM:
        remindWindow('Error!', 'Need exactly ' + str(DAT_FILE_NUM) + ' dat files')
        return EXIT_FAILURE

    allInputFiles = list(map(lambda fn: (dir_name + '/' + fn), allInputFiles))
    logging.debug(allInputFiles)

    for idx, inputFile in enumerate(allInputFiles):
        # print inputFile
        xs, ys = readXYfromFile(inputFile)
        XYs.addRow(xs, ys)

    XYs.finishLoading()
    return EXIT_SUCCESS

# button callbacks
def browseCallBack():
    dir = askdirectory()
    print dir
    ret = plotRawDataFromDir(dir)
    if ret == EXIT_SUCCESS:
        global dataLoaded
        dataLoaded = True

def invertCallBack():
    if not dataLoaded:
        remindLoadingData()
        return
    print 'invert button clicked'
    global XYs
    XYs.invert()

def promptCaliFactor():
    top = Tk.Toplevel()
    top.title("Please enter calibration factors")
    top.geometry("300x100")
    Tk.Label(top, text="Voltage (mV)").grid(row=0)
    Tk.Label(top, text="Time (sec)").grid(row=1)
    e1 = Tk.Entry(top, width=10)
    e1.insert(0, "1")
    e2 = Tk.Entry(top, width=10)
    e2.insert(0, ".2")

    e1.grid(row=0, column=1)
    e2.grid(row=1, column=1)

    def save_and_quit():
        voltageCalibrationFactor = e1.get()
        timeCalibrationFactor = e2.get()
        cali_info.setCaliFactor([voltageCalibrationFactor, timeCalibrationFactor])
        top.destroy()

        currOp = selectedOp.get()
        index = 0
        for op in userModes:
            if currOp == op:
                index += 1
                index %= len(userModes)
                selectedOp.set(userModes[index])
                selectOpCallBack(None)

    Tk.Button(top, text='Save', command=save_and_quit).grid(row=3, column=1, pady=4)
    return


#      _                                    _                    _
#     | |                                  | |                  | |
#   __| |_ __ __ ___      __  _ __ ___  ___| |_ __ _ _ __   __ _| | ___
#  / _` | '__/ _` \ \ /\ / / | '__/ _ \/ __| __/ _` | '_ \ / _` | |/ _ \
# | (_| | | | (_| |\ V  V /  | | |  __/ (__| || (_| | | | | (_| | |  __/
#  \__,_|_|  \__,_| \_/\_/   |_|  \___|\___|\__\__,_|_| |_|\__, |_|\___|
#                                                           __/ |
#                                                          |___/

def drawCaliRectCallBack(eclick, erelease):
    if enableCheckBoxState.get() is not OpEnabled:
        remindWindow('Wait...', 'Check \'Enable Marker Placement\' to enable this feature')
        return

    if cali_info.caliInfoReady():
        return

    # draw rectangle
    deltaX = abs(erelease.xdata - eclick.xdata)
    deltaY = abs(erelease.ydata - eclick.ydata)

    # if invalid marking, don't save any data
    if deltaX is 0:
        remindWindow('Error!', 'Invalid rectange. x distance too small')
        return

    if deltaY is 0:
        remindWindow('Error!', 'Invalid rectange. y distance too small')
        return

    rectPatch = patches.Rectangle((eclick.xdata, eclick.ydata), deltaX, deltaY, edgecolor='red', fill=False)
    mainAx.add_patch(rectPatch)

    cali_info.setXY([deltaX, deltaY])
    cali_info.setHandle(rectPatch)
    canvas.draw()
    promptCaliFactor()

# draw Rectangle switches
def drawRectCallBack(eclick, erelease):
    if not dataLoaded:
        remindLoadingData()
        return

    #
    currOp = selectedOp.get()
    if 'ROI' in currOp:
        ROICallBack(eclick, erelease)

    elif 'calibration' in currOp:
        drawCaliRectCallBack(eclick, erelease)

    else:
        print 'Draw rectangle is only valid for drawing calibration rectange or makr ROI. There must be some code logic issues'
        assert False

rectSelectorHandle = RectangleSelector(mainAx, drawRectCallBack, drawtype='box')

def enableRectSelector():
    global rectSelectorHandle
    if not rectSelectorHandle.active:
        rectSelectorHandle.set_active(True)

def disableRectSelector():
    global rectSelectorHandle
    if rectSelectorHandle.active:
        rectSelectorHandle.set_active(False)

# draw V line switches

def enableDrawVertLine():
    global drawVLineHandle
    if drawVLineHandle is None:
        drawVLineHandle = canvas.mpl_connect('button_press_event', drawVerticalLineCallback)


def disableDrawVertLine():
    global drawVLineHandle
    if drawVLineHandle is not None:
        canvas.mpl_disconnect(drawVLineHandle)
        drawVLineHandle = None

# draw Sync line switches

def enableDrawSyncLine():
    global drawSyncLineHandle
    if drawSyncLineHandle is None:
        drawSyncLineHandle = canvas.mpl_connect('button_press_event', drawSyncLineCallback)


def disableDrawSyncLine():
    global drawSyncLineHandle
    if drawSyncLineHandle is not None:
        canvas.mpl_disconnect(drawSyncLineHandle)
        drawSyncLineHandle = None

# draw horizontal line switches

def enableDrawHorizontalLine():
    global drawHorizontalLineHandle
    if drawHorizontalLineHandle is None:
        drawHorizontalLineHandle = canvas.mpl_connect('button_press_event', drawHorizontalLineCallback)


def disableDrawHorizontalLine():
    global drawHorizontalLineHandle
    if drawHorizontalLineHandle is not None:
        canvas.mpl_disconnect(drawHorizontalLineHandle)
        drawHorizontalLineHandle = None

# draw ROI switches
def ROICallBack(eclick, erelease):
    print 'In ROI callback'
    if not dataLoaded:
        remindLoadingData()
        return

    if enableCheckBoxState.get() is not OpEnabled:
        remindWindow('Wait...', 'Check \'Enable Marker Placement\' to enable this feature')
        return

    x_min = min(erelease.xdata, eclick.xdata)
    x_max = max(erelease.xdata, eclick.xdata)

    # check if x_min and x_max are valid
    validate_and_mark_ROI_regions(x_min, x_max)

def validate_and_mark_ROI_regions(x_min, x_max):
    if x_min >= x_max:
        remindWindow('Error!', 'Invalid rectange. x distance too small')
        return

    # validate existing data
    ret = is_data_complete_and_valid()
    if len(ret) == 0:
        return
    if len(ret) != 3:
        print 'is_data_complete_and_valid() does not return properly!'
        assert False

    vLineXs = ret[0]
    syncLineXs = ret[1]
    hLineYs = ret[2]

    # validate marked region
    # find regions that ROI is allowed to be in
    regions = list()
    for i in range(len(syncLineXs)):
        region = list()
        region.append(vLineXs[i])
        region.append(syncLineXs[i])
        regions.append(region)

    print 'x_min: ',
    print x_min
    print 'x_max: ',
    print x_max
    # check which region is the marked ROI in
    region_start = None
    region_end = None
    for region in regions:
        print 'region: ',
        print region
        if (region[0] <= x_min) and (x_max <= region[1]): # found it
            region_start = region[0]
            region_end = region[1]
            break

    if (region_start == None) or (region_end == None):
        remindWindow('Wait...', 'Invalid ROI')
        return

    # transform [x_min, x_max] to [x_start_offset, ROI_len]
    ROI_len = x_max - x_min
    x_start_offset = region_end - x_min  # how much to the left of the sync line it is

    # mark ROI on the plot
    XYs.mark_ROI_regions(x_start_offset, ROI_len, syncLineXs)

def enableDrawROI():
    enableRectSelector()

def disableDrawROI():
    disableRectSelector()

def enableStep(stepOn):
    print 'stepOn: ' + str(stepOn)
    if stepOn < STEP_ONE or stepOn > STEP_FIVE:
        assert False, "Illegal step number"

    global enablers
    global disablers
    # disable everything other steps
    for step in disablers:
        if step != stepOn:
            disablers[step]()

    # enable the step
    enablers[stepOn]()


#      _                      _ _
#     | |                    | (_)
#   __| |_ __ __ ___      __ | |_ _ __   ___
#  / _` | '__/ _` \ \ /\ / / | | | '_ \ / _ \
# | (_| | | | (_| |\ V  V /  | | | | | |  __/
#  \__,_|_|  \__,_| \_/\_/   |_|_|_| |_|\___|
#
#
def drawVerticalLineCallback(event):
    if event.x is None or event.y is None or event.xdata is None or event.ydata is None:
        return

    if not dataLoaded:
        remindLoadingData()
        return

    if enableCheckBoxState.get() is not OpEnabled:
        return

    if v_lines.vLinesReady():
        selectedOp.set(userModes[STEP_THREE])
        selectOpCallBack(None)
        return

    # print('button=%d, x=%d, y=%d, xdata=%f, ydata=%f' % (
    #   event.button, event.x, event.y, event.xdata, event.ydata))

    # set the current axis to the main axis
    yDataMax = XYs.allYmax - whiteSpaceLength + paddingLength
    yDataMin = XYs.allYmin + whiteSpaceLength - paddingLength
    lineHandle, = mainAx.plot([event.xdata, event.xdata], [yDataMax, yDataMin], linestyle='dashed', color='blue')
    v_lines.addVerticalLine(VLine(lineHandle, event.xdata))
    canvas.draw()


def drawSyncLineCallback(event):
    if event.x is None or event.y is None or event.xdata is None or event.ydata is None:
        return

    if not dataLoaded:
        remindLoadingData()
        return

    if enableCheckBoxState.get() is not OpEnabled:
        return

    if not v_lines.vLinesReady():
        remindWindow('Wait...', 'Please finish drawing vertical line first')
        return

    if sync_lines.vSyncLinesReady():
        selectedOp.set(userModes[STEP_FOUR])
        selectOpCallBack(None)
        return

    # print('button=%d, x=%d, y=%d, xdata=%f, ydata=%f' % (
    #   event.button, event.x, event.y, event.xdata, event.ydata))

    # set the current axis to the main axis
    yDataMax = XYs.allYmax - whiteSpaceLength + paddingLength
    yDataMin = XYs.allYmin + whiteSpaceLength - paddingLength
    lineHandle, = mainAx.plot([event.xdata, event.xdata], [yDataMax, yDataMin], linestyle='dashed', color='green')
    sync_lines.addSyncLine(VLine(lineHandle, event.xdata))
    canvas.draw()


def drawHorizontalLineCallback(event):
    if event.x is None or event.y is None or event.xdata is None or event.ydata is None:
        return

    if not dataLoaded:
        remindLoadingData()
        return

    if enableCheckBoxState.get() is not OpEnabled:
        return

    if h_lines.HorizontalLinesReady():
        # automatically move to the next state
        selectedOp.set(userModes[STEP_FIVE])
        selectOpCallBack(None)
        return

    # set the current axis to the main axis
    xDataMax = XYs.allXmax - whiteSpaceLength
    xDataMin = XYs.allXmin + whiteSpaceLength
    lineHandle, = mainAx.plot([xDataMin, xDataMax], [event.ydata, event.ydata], linestyle='dashed', color='orange')
    h_lines.addHLine(Hline(lineHandle, event.ydata))

    canvas.draw()


def enableCallBack():
    currState = enableCheckBoxState.get()
    print "variable is: ", currState

# This callback controls the current state of the program
def selectOpCallBack(event):
    currOp = selectedOp.get()
    if currOp == userModes[STEP_ONE]:  # calibration
        enableStep(STEP_ONE)

    elif currOp == userModes[STEP_TWO]:  # v line
        enableStep(STEP_TWO)

    elif currOp == userModes[STEP_THREE]:  # sync line
        enableStep(STEP_THREE)

    elif currOp == userModes[STEP_FOUR]: # horizontal line
        enableStep(STEP_FOUR)

    else: # ROI
        # check if all previous steps are ready
        unreadySteps = getUnreadySteps()
        if len(unreadySteps) != 0:
            remindWindow('Wait...', 'You have to finish all previous steps before marking ROI')
            return

        enableStep(STEP_FIVE)


def deleteCallBack():

    if not dataLoaded:
        remindLoadingData()
        return

    currOp = selectedOp.get()
    if currOp == userModes[STEP_ONE]:  # calibration
        cali_info.deleteRect()

    elif currOp == userModes[STEP_TWO]:  # v line
        v_lines.deleteVerticalLine()

    elif currOp == userModes[STEP_THREE]:  # sync line
        sync_lines.deleteSyncLine()

    else:  # horizontal line
        h_lines.deleteHorizontalLine()

def getUnreadySteps():

    unreadySteps = []
    if not cali_info.caliInfoReady():
        unreadySteps.append(STEP_ONE)

    if not v_lines.vLinesReady():
        unreadySteps.append(STEP_TWO)

    if not sync_lines.vSyncLinesReady():
        unreadySteps.append(STEP_THREE)

    if not h_lines.HorizontalLinesReady():
        unreadySteps.append(STEP_FOUR)

    return unreadySteps

def generateWarningMsg(warning_step):
    retMsg = "Please finish "
    # if not cali_info.caliInfoReady():
    if warning_step == STEP_ONE:
        retMsg += " getting calibration data "

    # if not v_lines.vLinesReady():
    if warning_step == STEP_TWO:
        retMsg += (" and draw " + str(VerticalLineNum) + " vertical lines")

    # if not sync_lines.vSyncLinesReady():
    if warning_step == STEP_THREE:
        retMsg += (" and draw " + str(VerticalLineNum) + " synchronization vetical lines")

    # if not h_lines.HorizontalLinesReady():
    if warning_step == STEP_FOUR:
        retMsg += " and draw 3 horizontal lines"

    return retMsg


#                             _       _
#                            | |     | |
#   ___  __ ___   _____    __| | __ _| |_ __ _
#  / __|/ _` \ \ / / _ \  / _` |/ _` | __/ _` |
#  \__ \ (_| |\ V /  __/ | (_| | (_| | || (_| |
#  |___/\__,_| \_/ \___|  \__,_|\__,_|\__\__,_|
#
#
def preSaveDataProcess(fd, vLineXs, syncLineXs, hLineYs):
    csv.register_dialect('excel_custom', 'excel', lineterminator='\n')
    writer = csv.writer(fd, 'excel_custom')

    allXyRows = XYs.getCurrentPlotedXYs()
    # only needs the first 3 rows (the last row is reference)
    # assume rows are sorted already

    leadNames = ["I", "aVR", "V1", "V4",
                 "II", "aVL", "V2", "V5",
                 "III", "aVF", "V3", "V6"]

    allXyRows = allXyRows[1:]
    allXyRows = reversed(allXyRows)

    titleRow = []
    for leadName in leadNames:
        titleRow.append(leadName + ' (X)')
        titleRow.append(leadName + ' (Y)')
    writer.writerow(titleRow)

    allLeads = []
    hLineYs.reverse()
    allXyRowsIndex = 0
    for eachRow in allXyRows:
        yOffset = hLineYs[allXyRowsIndex]
        allXyRowsIndex += 1
        leads = splitOneRow(eachRow, vLineXs, syncLineXs, yOffset)
        # all leads should have the same number of Xs and Ys
        for lead in leads:
            # format to same type
            allLeads.append([float(x) if x is not None else "" for x in lead.xs])
            allLeads.append([float(y) if y is not None else "" for y in lead.ys])

    allLeads = zip(*allLeads)

    for eachRow in allLeads:
        writer.writerow(eachRow)

    fd.close()


def generateTitle(row_num, col_num, lead_names):
    leadName = lead_names[row_num][col_num]
    return leadName + ' (X)', leadName + ' (Y)'


'''
Split a row of Xs and Ys according to the Xs of the vertical lines
'''


def splitOneRow(row, vLineXs, syncLineXs, yOffset):

    # Truncate data before first vLine
    truncateIndex = 0
    while row.xs[truncateIndex] < vLineXs[0]:
        truncateIndex += 1
    row.xs = row.xs[truncateIndex:]
    row.ys = row.ys[truncateIndex:]
    row.resetMaxMinAverage()
    vLineXs = vLineXs[1:]  # get rid of first vLine to not disturb rest of function

    # back to regularly scheduled programming
    xMin = min(row.xs)
    leads = []  # A list of OneRowXY objects
    xs = []
    ys = []
    maxLeadLen = 0

    xScale = cali_info.Xscale
    yScale = cali_info.Yscale

    vLineXsIndex = 0
    for vLineX in vLineXs:
        index = 0
        xOffset = syncLineXs[vLineXsIndex]
        vLineXsIndex += 1

        rounder = lambda x: float("{0:.4g}".format(x))  # round up to 4 significant figures
        verticalLineWidthPercent = 0.02
        deltaX = max(row.xs) - min(row.xs)
        verticalLineWidth = verticalLineWidthPercent * deltaX

        vLineX -= verticalLineWidth
        for x in row.xs:
            if xMin <= x < vLineX:
                x -= xOffset
                xs.append(rounder(x * xScale))
                ys.append(rounder((row.ys[index] - yOffset) * yScale))
            index += 1

        lastX = xs[0]
        xs = xs[1:]
        uniqueXs = [lastX]
        uniqueYs = [ys[0]]
        ys = ys[1:]
        uniqIndex = 0
        originalIndex = 0
        for x in xs:
            if x == lastX:
                averagedY = (ys[originalIndex] + uniqueYs[uniqIndex]) / 2
                averagedY = rounder(averagedY)
                # averagedY = int(round(averagedY))
                uniqueYs[uniqIndex] = averagedY
            else:
                uniqueXs.append(x)
                uniqueYs.append(ys[originalIndex])
                uniqIndex += 1
                lastX = x

            originalIndex += 1

        xs = uniqueXs
        ys = uniqueYs

        currLeadLen = len(xs)
        if currLeadLen > maxLeadLen:
            maxLeadLen = currLeadLen

        leads.append(OneRowXY(xs, ys))
        xs = []
        ys = []
        xMin = vLineX + verticalLineWidth * 2

    # padding
    for index in range(0, len(leads)):
        currLen = len(leads[index].xs)
        while currLen < maxLeadLen:
            leads[index].xs.append(None)
            leads[index].ys.append(None)
            currLen += 1

    return leads


# returns a list [vLineXs, syncLineXs, hLineYs]
def is_data_complete_and_valid():
    unreadySteps = getUnreadySteps()

    ret = list()
    if len(unreadySteps) != 0:  # there are some steps not yet finish
        top = Tk.Toplevel()
        top.geometry(WARNING_WINDOW_GEOMETRY)
        top.title(WARNING_TITLE)
        msg = ''
        for unreadyStep in unreadySteps:
            msg += generateWarningMsg(unreadyStep)
            msg += '\n'

        msg = Tk.Message(top, text=msg)
        msg.pack()

        button = Tk.Button(top, text="OK", command=top.destroy)
        button.pack()
        return ret

    vLineXs = v_lines.getXs()
    syncLineXs = sync_lines.getXs()

    # validate syncLineXs
    if len(vLineXs) is not len(syncLineXs) + 1:
        remindWindow('Wait...', 'Invalid synchronization lines. Should have one less than vertical lines')
        return ret

    for i in range(len(syncLineXs)):
        if syncLineXs[i] < vLineXs[i] or syncLineXs[i] > vLineXs[i + 1]:
            remindWindow('Wait...',
                         'Invalid synchronization lines. Each sync line should be between two vertical lines')
            return ret

    hLineYs = h_lines.getYs()
    ret.append(vLineXs)
    ret.append(syncLineXs)
    ret.append(hLineYs)
    return ret

def saveCallBack():

    # check if it is ready to save
    if not dataLoaded:
        remindLoadingData()
        return

    ret = is_data_complete_and_valid()
    if len(ret) == 0:
        return
    if len(ret) != 3:
        print 'is_data_complete_and_valid() does not return properly!'
        assert False

    vLineXs = ret[0]
    syncLineXs = ret[1]
    hLineYs = ret[2]
    fd = asksaveasfile(mode='w', defaultextension=".csv")
    if fd is None:
        return

    preSaveDataProcess(fd, vLineXs, syncLineXs, hLineYs)


def restartCallBack():
    # delete all existing objects
    if not dataLoaded:
        remindLoadingData()
        return

    cali_info.deleteRect()
    v_lines.deleteAll()
    sync_lines.deleteAll()
    h_lines.deleteAll()
    XYs.reset()
    # reset global state
    global OpEnabled
    global dataLoaded
    dataLoaded = False
    OpEnabled = 1
    selectedOp.set(userModes[STEP_ONE])
    selectOpCallBack(None)

if __name__ == "__main__":
    browseButton = Tk.Button(master=root, text="Set Data Folder", command=browseCallBack)
    browseButton.pack(side=Tk.LEFT)

    invertButton = Tk.Button(master=root, text="Invert Entire Plot", command=invertCallBack)
    invertButton.pack(side=Tk.LEFT)

    enableDrawingButton = Tk.Checkbutton(master=root, text="Enable Marker Placement", variable=enableCheckBoxState, command=enableCallBack)
    enableDrawingButton.pack(side=Tk.LEFT)

    #######################
    # drop-down menue
    #######################
    dropDownMenu = Tk.OptionMenu(root, selectedOp, userModes[STEP_ONE], userModes[STEP_TWO], userModes[STEP_THREE], userModes[STEP_FOUR], userModes[STEP_FIVE], command=selectOpCallBack)
    dropDownMenu.pack(side=Tk.LEFT)

    deleteButton = Tk.Button(master=root, text="Delete", command=deleteCallBack)
    deleteButton.pack(side=Tk.LEFT)

    saveButton = Tk.Button(master=root, text="Save", command=saveCallBack)
    saveButton.pack(side=Tk.LEFT)

    restartButton = Tk.Button(master=root, text="Restart", command=restartCallBack)
    restartButton.pack(side=Tk.LEFT)

    # initialize global variables
    enablers[STEP_ONE] = enableRectSelector
    enablers[STEP_TWO] = enableDrawVertLine
    enablers[STEP_THREE] = enableDrawSyncLine
    enablers[STEP_FOUR] = enableDrawHorizontalLine
    enablers[STEP_FIVE] = enableDrawROI

    disablers[STEP_ONE] = disableRectSelector
    disablers[STEP_TWO] = disableDrawVertLine
    disablers[STEP_THREE] = disableDrawSyncLine
    disablers[STEP_FOUR] = disableDrawHorizontalLine
    disablers[STEP_FIVE] = disableDrawROI
    Tk.mainloop()
