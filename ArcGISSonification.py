#!/usr/bin/env python
# coding: utf-8

# TITLE: From Visual Data to Auditory Landscapes in ArcGIS 
# AUTHOR: Grace Hegland 

from pynput import keyboard
from pynput.keyboard import Key, Listener
from pysinewave import SineWave
from threading import Thread
from gtts import gTTS

import sys
import time
import winsound # this is a Windows specific library
import rtmidi
import pandas as pd
import os

# Read in the data that has been exported from an ArcGIS attribute table as a csv file
fileName, XLongColumnName, YLatColumnName, dataToMapColumnName = sys.argv[1:]

data = pd.read_csv(fileName) # Load data as a pandas dataframe
numberOfRecords = len(data)
dataToMap = data[dataToMapColumnName]

# General mapping function
# Calculate the proportional value of 'value' between 'min_value' and 'max_value'
# Map this proportional value to the range between 'min_result' and 'max_result'
def map_value(value, min_value, max_value, min_result, max_result): 
    return min_result + (value - min_value)/(max_value - min_value)*(max_result - min_result)
   

# MIDI note numbers for the major pentatonic scale
note_midis = [36, 38, 40, 43, 45, 48, 50, 52, 55, 57, 60, 62, 64, 67, 69, 72, 74, 76, 79, 81]

if min(dataToMap) == max(dataToMap): 
    midi_data = [] 
    for i in range(numberOfRecords): 
        note = 57
        midi_data.append(note)
else: 
    # Normalize data
    y_data = map_value(dataToMap, min(dataToMap), max(dataToMap), 0, 1)

    # Map y data to MIDI note numbers
    midi_data = []
    for i in range(numberOfRecords): 
        note_index = round(map_value(y_data[i],0,1,0,19))
        midi_data.append(note_midis[note_index])

# Create a dictionary with longitude and latitude pairs as the keys and notes as the values
latLongNotes = dict(zip(zip(data[XLongColumnName], data[YLatColumnName]), midi_data))

# Sort the dictionary first by decreasing latitude and then by increasing longitude
sortedLatLongNotes = dict(sorted(latLongNotes.items(), key=lambda item: (-item[0][1], item[0][0])))

# Create a list of the sorted latitudes
lats = [lat for _, lat in sortedLatLongNotes.keys()]

# Sort the dictionary by increasing longitude 
sortedByLong = dict(sorted(latLongNotes.items(), key=lambda item: (item[0][0])))
longitudes = [long for long, _ in sortedByLong.keys()]

# Return true if the latitude is in the specified range of the current latitude (global)
# and if the longitude is in the range set by the zoom
# This range will define the width of our latitude bands when used to filter sortedLatLongNotes
def in_range(latlong_and_note, bandWidth):
    latlong, _ = latlong_and_note
    long , lat = latlong
    
    return lat <= currentLat and lat > currentLat - bandWidth and long >= longrange[0] and long <= longrange[1]

# This function should read to the user what the current line is 
def say_line(line_counter): 
    myText = f"line {line_counter}" 
    language = 'en'
    output = gTTS(text = myText, lang = language, slow = False)
    output.save("output.mp3")
    os.system("start output.mp3")
    
# This function should read to the user the function of each key
def say_help_info(): 
    Text = "Tab plays a line. The left arrow decreases the speed of lines. The right arrow increases the speed of lines.The down arrow moves to the next line. The up arrow moves to the previous line. One allows you to zoom in on the first half of a region. Two allows you to zoom in on the second half of a region. Zero returns the zoom to the default. Z tells you the zoom level of the current region. S takes you to the starting line. M takes you to the middle line. E takes you to the ending line. I tells you what line you are currently on."
    language = 'en'
    output = gTTS(text = Text, lang = language, slow = False)
    output.save("output.mp3")
    os.system("start output.mp3")

def calculate_zoom_percentage(zoom_counter): 
    return 100/(2**(zoom_counter))  

# This function should read to the user the current zoom level
def say_zoom_info(zoom_counter): 
    ZText = f"The zoom level is {calculate_zoom_percentage(zoom_counter)} percent" 
    language = 'en'
    output = gTTS(text = ZText, lang = language, slow = False)
    output.save("output.mp3")
    os.system("start output.mp3")

# Play a sine wave that decreases in pitch as you move along the x axis 
def play_sine_wave(lineDuration): 
    sinewave = SineWave(pitch=0, pitch_per_second= 5/lineDuration) # Starting pitch = 0 
    sinewave.play()
    sinewave.set_pitch(-5) # Ending pitch
    time.sleep(lineDuration) # Total time of the sine wave in seconds
    sinewave.stop()

# Calculate the length of the delay between piano notes
def delayCalc(long1, long2, delayTime, intervalWidth):
    return ((long2 - long1)/intervalWidth)*delayTime

def notesToDelays(sortedLatLongNotes, delayTime, intervalWidth):
    delays = []
    longs = [long for long, _ in sortedLatLongNotes.keys()]
    for i in range(len(sortedLatLongNotes)-1): 
        # Calculate the delays between consecutive notes using delayCalc
        # Append the calculated delays to the delays list
        delays.append(delayCalc(longs[i], longs[i+1], delayTime, intervalWidth))
    return delays

def midi_play(note, noteDuration):
    # 0x94 is the status byte for the "note on" message, note pitch, note velocity (volume) = 127
    note_on = [0x94, note, 127]
    # 0x84 is the status byte for the "note off" message, note pitch, note velocity (volume) = 0
    note_off = [0x84, note, 0] 
    midi_out.send_message(note_on)
    time.sleep(noteDuration) # Play note for note duration before turning off
    midi_out.send_message(note_off)

# Play MIDI notes for their note durations with time delays between the notes
def play_midi_notes(sortedLatLongNotes, noteDuration, delayTime): 
    timeDelays = notesToDelays(sortedLatLongNotes, delayTime, intervalWidth)
    for i in range(len(sortedLatLongNotes)):
        midi_play(list(sortedLatLongNotes.values())[i], noteDuration)
        if i < len(timeDelays):
            # If there are corresponding time delays, wait before playing the next note
            time.sleep(timeDelays[i]) 
            
def edgeDelays(longInitial, longFinal, delayTime, intervalWidth):
    # Calculate the length of the delay between the start of the line and the first note
    initialDelay = ((longInitial - longitudes[0]) / intervalWidth) * delayTime
    # Calculate the length of the delay between the last note and the end of the line
    finalDelay = ((longitudes[-1] - longFinal) / intervalWidth) * delayTime 
    return (initialDelay, finalDelay)                        

def linePlay(currentLat, beep_frequency, lineDuration, noteTime): 
    # Use the in_range function to filter the sorted note dictionary 
    latitudeBands = dict(filter(lambda item: in_range(item, bandWidth), sortedLatLongNotes.items()))
    # Sort the latitude bands by increasing longitude 
    sortedLatitudeBands = dict(sorted(latitudeBands.items(), key = lambda item : item[0]))
    noteCount = len(sortedLatitudeBands)
    longs = [long for long, _ in sortedLatitudeBands.keys()]
    delayTime = lineDuration - noteTime
    
    if noteCount > 0:
        # Use threading to simultaneously play the sine wave and the piano notes
        sine_thread = Thread(target = play_sine_wave, args = (lineDuration,))  
        sine_thread.start()
        
        noteDuration = noteTime / noteCount
        initialDelay, finalDelay = edgeDelays(longs[0], longs[noteCount-1], delayTime, intervalWidth)
        time.sleep(initialDelay) 
        play_midi_notes(sortedLatitudeBands, noteDuration, delayTime) 
        time.sleep(finalDelay)
    else:
        # if there are no notes in the line, just play the sine wave
        play_sine_wave(lineDuration)
            
    winsound.Beep(beep_frequency, 500)

def speed_up(): 
    global lineDuration, noteTime
    lineDuration = lineDuration / 2
    noteTime = noteTime / 2
    
def slow_down(): 
    global lineDuration, noteTime
    lineDuration = lineDuration*2
    noteTime = noteTime*2

def on_key_release(key):
    global currentLat, beep_frequency, line_counter, longrange, zoom_counter, bandWidth,lineDuration, noteTime
    
    if currentLat < lats[-1]: #if current latitude is less than the minimum latitude
        return False # Stop the listener
    
    try:
        # Zoom into the first half of the region
        if key.char == "1":
            longrange[1] = longrange[0] + ((longrange[1] - longrange[0]) / 2) # Set a new upperbound
            zoom_counter += 1
            
        # Zoom into the second half of the region 
        elif key.char == "2":
            longrange[0] = longrange[0] + ((longrange[1] - longrange[0]) / 2) # Set a new lowerbound
            zoom_counter += 1
            
        # Reset to the default zoom level
        elif key.char == "0":
            longrange=[longitudes[0], longitudes[-1]] # Original longitude range
            zoom_counter = 0
           
        # Read the line counter
        elif key.char == "i":
            say_line(line_counter)
            
        # Go to the starting line
        elif key.char == "s": 
            longrange=[longitudes[0], longitudes[-1]]
            currentLat = lats[0] 
            beep_frequency = 1000 # Initial beep frequency
            line_counter = 1
            zoom_counter = 0
            
        # Go to the middle line
        elif key.char == "m": 
            longrange=[longitudes[0], longitudes[-1]]
            currentLat = lats[0] - bandWidth*29
            beep_frequency = 1000 - 5*29
            line_counter = 30 
            zoom_counter = 0
            
        # Go to the ending line 
        elif key. char == "e": 
            longrange=[longitudes[0], longitudes[-1]]
            currentLat = lats[-1] 
            beep_frequency = 1000 - 5*59
            line_counter = 60 
            zoom_counter = 0
            
        # Read the zoom_counter
        elif key.char == "z": 
            say_zoom_info(zoom_counter) 
            
        # Read the help info
        elif key.char == "h": 
            say_help_info()
    except:   
        # Repeat the current line
        if key == Key.left: 
            slow_down()
        
        elif key == Key.right:
            speed_up()
            
        # Move up a line
        elif key == Key.up:
            longrange=[longitudes[0], longitudes[-1]]
            currentLat += bandWidth
            beep_frequency += 5
            line_counter -= 1 
            zoom_counter = 0
            
        # Move down a line
        elif key == Key.down:
            longrange=[longitudes[0], longitudes[-1]]
            currentLat -= bandWidth
            beep_frequency -= 5
            line_counter += 1
            zoom_counter = 0
            
        # Play the line
        elif key == Key.tab: 
            linePlay(currentLat, beep_frequency, lineDuration, noteTime)
        
        elif key == Key.esc:
            return False #Stop the listener 

# Run these lines every time you want to run the code
midi_out = rtmidi.MidiOut() # Create a MIDI object to send MIDI messages to 
midi_out.open_port(0) # Send MIDI message to output port 

# Initialize all variables
currentLat = lats[0]
beep_frequency = 1000
line_counter = 1
longrange=[longitudes[0], longitudes[-1]] 
zoom_counter = 0 
intervalWidth = longitudes[-1] - longitudes [0] 
bandWidth = (lats[0]-lats[-1])/60 # Fix the line number at 60 and calculate the bandwidth
lineDuration = 10
noteTime = 5

# Have the listener always listening with on_key_release as the handler
with midi_out:  
    with Listener(on_release=on_key_release) as listener:
        listener.join()      
