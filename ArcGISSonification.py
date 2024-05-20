#!/usr/bin/env python

"""
From Visual Data to Auditory Landscapes in ArcGIS
AUTHOR: Grace Hegland
"""

import wx
import sys
import time
import winsound  # this is a Windows specific library
import rtmidi
import pandas as pd

from pysinewave import SineWave
from threading import Thread
from cytolk import tolk


class ArcGISSonification(wx.Frame):
    NOTE_MIDIS = [
        36,
        38,
        40,
        43,
        45,
        48,
        50,
        52,
        55,
        57,
        60,
        62,
        64,
        67,
        69,
        72,
        74,
        76,
        79,
        81,
    ]
    HELP_TEXT = (
        "Tab plays a line. The left arrow decreases the speed of lines. "
        "The right arrow increases the speed of lines. The down arrow "
        "moves to the next line. The up arrow moves to the previous line. "
        "One allows you to zoom in on the first half of a region. Two "
        "allows you to zoom in on the second half of a region. Zero "
        "returns the zoom to the default. Z tells you the zoom level of "
        "the current region. S takes you to the starting line. M takes "
        "you to the middle line. E takes you to the ending line. I tells "
        "you what line you are currently on. Escape exits the application."
    )
    MINIMUM_LINE = 1
    MAXIMUM_LINE = 60

    def __init__(self, file_name, x_long_col, y_lat_col, data_to_map_col):
        super().__init__(parent=None, title="ArcGIS data sonification")
        self.Bind(wx.EVT_KEY_DOWN, self.on_key_press)

        data = pd.read_csv(file_name)
        self.number_of_records = len(data)
        data_to_map = data[data_to_map_col]

        self.sorted_lat_long_notes = self._prepare_data(
            data, x_long_col, y_lat_col, data_to_map
        )

        self.lats = [lat for _, lat in self.sorted_lat_long_notes.keys()]
        self.longitudes = sorted(
            {long for long, _ in self.sorted_lat_long_notes.keys()}
        )

        self.current_lat = self.lats[0]
        self.beep_frequency = 1000
        self.line_counter = 1
        self.longrange = [self.longitudes[0], self.longitudes[-1]]
        self.zoom_counter = 0
        self.interval_width = self.longitudes[-1] - self.longitudes[0]
        self.band_width = (self.lats[0] - self.lats[-1]) / 60
        self.duration = 10
        self.note_time = 5

        self.midi_out = rtmidi.MidiOut()
        self.midi_out.open_port(0)

    def on_key_press(self, event):
        key_code = event.GetKeyCode()
        key_actions = {
            wx.WXK_TAB: self.play,
            wx.WXK_LEFT: self.slow_down,
            wx.WXK_RIGHT: self.speed_up,
            wx.WXK_UP: self.move_up,
            wx.WXK_DOWN: self.move_down,
            wx.WXK_ESCAPE: self.Close,
            ord("1"): self.zoom_in_first_half,
            ord("2"): self.zoom_in_second_half,
            ord("0"): self.reset_zoom,
            ord("I"): self.say_line,
            ord("S"): self.move_start,
            ord("M"): self.move_middle,
            ord("E"): self.move_end,
            ord("Z"): self.say_zoom_info,
            ord("H"): self.say_help_info,
        }
        act = key_actions.get(key_code)
        if act:
            act()

    @staticmethod
    def map_value(value, min_value, max_value, min_result, max_result):
        """
        Calculates the proportional value of 'value' between 'min_value'
        and 'max_value', and maps this value to the range between
        'min_result' and 'max_result'
        """
        return min_result + (value - min_value) / (max_value - min_value) * (
            max_result - min_result
        )

    def _prepare_data(self, data, x_long_col, y_lat_col, data_to_map):
        if min(data_to_map) == max(data_to_map):
            midi_data = [57] * self.number_of_records
        else:
            y_data = self.map_value(
                data_to_map, min(data_to_map), max(data_to_map), 0, 1
            )
            midi_data = [
                self.__class__.NOTE_MIDIS[
                    round(self.map_value(y, 0, 1, 0, 19))
                ]
                for y in y_data
            ]

        lat_long_notes = dict(
            zip(zip(data[x_long_col], data[y_lat_col]), midi_data)
        )
        return dict(
            sorted(
                lat_long_notes.items(),
                key=lambda item: (-item[0][1], item[0][0]),
            )
        )

    def in_range(self, latlong_and_note):
        """
        Checks if the latitude and longitude are within the current range.
        """
        (long, lat), _ = latlong_and_note
        return (
            self.longrange[0] <= long <= self.longrange[1]
            and self.current_lat - self.band_width < lat <= self.current_lat
        )

    def say_line(self):
        "Reports the current line number"
        tolk.output(f"line {self.line_counter}", interrupt=True)

    def say_help_info(self):
        "Reports help text to the user"
        tolk.output(self.__class__.HELP_TEXT, interrupt=True)

    @property
    def zoom_percentage(self) -> float:
        return 100 / (2**self.zoom_counter)

    def say_zoom_info(self):
        "Reports the current zoom level to the user"
        tolk.output(f"{self.zoom_percentage} percent zoom", interrupt=True)

    def _play_sine_wave(self, duration):
        """
        Plays a sine wave that decreases in pitch as you move along the x axis
        """
        sinewave = SineWave(pitch=0, pitch_per_second=5 / duration)
        sinewave.play()
        sinewave.set_pitch(-5)
        time.sleep(duration)
        sinewave.stop()

    @staticmethod
    def _delay_calc(long1, long2, delay_time, interval_width):
        "Calculates the length of the delay between piano notes"
        return ((long2 - long1) / interval_width) * delay_time

    @classmethod
    def _notes_to_delays(
        cls, sorted_lat_long_notes, delay_time, interval_width
    ):
        delays = []
        longs = [long for long, _ in sorted_lat_long_notes.keys()]
        for i in range(len(sorted_lat_long_notes) - 1):
            delays.append(
                cls._delay_calc(
                    longs[i], longs[i + 1], delay_time, interval_width
                )
            )
        return delays

    def midi_play(self, note, note_duration):
        STATUS_NOTE_ON = 0x94
        STATUS_NOTE_OFF = 0x84

        note_on_msg = (STATUS_NOTE_ON, note, 127)
        note_off_msg = (STATUS_NOTE_OFF, note, 0)

        self.midi_out.send_message(note_on_msg)
        time.sleep(note_duration)
        self.midi_out.send_message(note_off_msg)

    def play_midi_notes(
        self, sorted_lat_long_notes, note_duration, delay_time
    ):
        """
        Plays MIDI notes for their note durations with appropriate time delays
        """
        time_delays = self._notes_to_delays(
            sorted_lat_long_notes, delay_time, self.interval_width
        )
        for i, note in enumerate(sorted_lat_long_notes.values()):
            self.midi_play(note, note_duration)
            if i < len(time_delays):
                time.sleep(time_delays[i])

    def edge_delays(
        self, long_initial, long_final, delay_time, interval_width
    ):
        initial_delay = (
            (long_initial - self.longitudes[0]) / interval_width
        ) * delay_time
        final_delay = (
            (self.longitudes[-1] - long_final) / interval_width
        ) * delay_time
        return initial_delay, final_delay

    def play(self):
        latitude_bands = dict(
            filter(self.in_range, self.sorted_lat_long_notes.items())
        )
        sorted_latitude_bands = dict(
            sorted(latitude_bands.items(), key=lambda item: item[0])
        )

        if sorted_latitude_bands:
            longs = [long for long, _ in sorted_latitude_bands.keys()]
            delay_time = self.duration - self.note_time
            note_duration = self.note_time / len(sorted_latitude_bands)

            sine_thread = Thread(
                target=self._play_sine_wave, args=(self.duration,)
            )
            sine_thread.start()

            initial_delay, final_delay = self.edge_delays(
                longs[0], longs[-1], delay_time, self.interval_width
            )
            time.sleep(initial_delay)
            self.play_midi_notes(
                sorted_latitude_bands, note_duration, delay_time
            )
            time.sleep(final_delay)
        else:
            # if there are no notes in the line, just play the sine wave
            self._play_sine_wave(self.duration)

        winsound.Beep(self.beep_frequency, 500)

    def speed_up(self):
        self.duration /= 2
        self.note_time /= 2

    def slow_down(self):
        self.duration *= 2
        self.note_time *= 2

    def _move(self, direction: int):
        if (self.line_counter + direction) % (
            self.__class__.MAXIMUM_LINE + 1
        ) == 0:
            return
        self.longrange = [self.longitudes[0], self.longitudes[-1]]
        self.current_lat -= self.band_width * direction
        self.beep_frequency -= 5 * direction
        self.line_counter += direction
        self.zoom_counter = 0
        tolk.output(str(self.line_counter), True)

    def move_down(self):
        self._move(1)

    def move_up(self):
        self._move(-1)

    def zoom_in_first_half(self):
        self.longrange[1] = (
            self.longrange[0] + (self.longrange[1] - self.longrange[0]) / 2
        )
        self.zoom_counter += 1

    def zoom_in_second_half(self):
        self.longrange[0] = (
            self.longrange[0] + (self.longrange[1] - self.longrange[0]) / 2
        )
        self.zoom_counter += 1

    def reset_zoom(self):
        self.longrange = [self.longitudes[0], self.longitudes[-1]]
        self.zoom_counter = 0

    def move_start(self):
        self._move(self.__class__.MINIMUM_LINE - self.line_counter)

    def move_middle(self):
        self._move((self.__class__.MAXIMUM_LINE // 2) - self.line_counter)

    def move_end(self):
        self._move(self.__class__.MAXIMUM_LINE - self.line_counter)


if __name__ == "__main__":
    fileName, XLongColumnName, YLatColumnName, dataToMapColumnName = sys.argv[
        1:
    ]

    tolk.try_sapi(
        True  # Use Microsoft speech API if no screen reader is active
    )
    tolk.load()

    app = wx.App()
    frame = ArcGISSonification(
        fileName, XLongColumnName, YLatColumnName, dataToMapColumnName
    )
    frame.Show()
    app.MainLoop()
