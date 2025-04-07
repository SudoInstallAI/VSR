#!/usr/bin/env python3
import os
import re
import subprocess
import tempfile

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QGridLayout, QLabel, QLineEdit, QMainWindow,
                             QPushButton, QTextEdit, QWidget, QFileDialog, QMessageBox)

### Core Video Processing Functions ###

def get_video_duration(input_file):
    """Retrieve the total duration (in seconds) of the video using ffprobe."""
    cmd = [
        'ffprobe', '-i', input_file,
        '-show_entries', 'format=duration',
        '-v', 'quiet', '-of', 'csv=p=0'
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise RuntimeError("Failed to get video duration.")

def detect_silence(input_file, threshold, min_silence_duration, status_callback):
    """
    Use FFmpeg’s silencedetect filter to find silent intervals.
    Returns two lists: silence_starts and silence_ends (both in seconds).
    """
    status_callback("Detecting silence...")
    cmd = [
        'ffmpeg', '-i', input_file,
        '-af', f'silencedetect=noise={threshold}dB:d={min_silence_duration}',
        '-f', 'null', '-'
    ]
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
    stdout, stderr = proc.communicate()

    silence_starts = []
    silence_ends = []
    for line in stderr.splitlines():
        if "silence_start" in line:
            m = re.search(r'silence_start: (\d+(\.\d+)?)', line)
            if m:
                silence_starts.append(float(m.group(1)))
        if "silence_end" in line:
            m = re.search(r'silence_end: (\d+(\.\d+)?).*', line)
            if m:
                silence_ends.append(float(m.group(1)))
    return silence_starts, silence_ends

def compute_keep_segments(silence_starts, silence_ends, duration, min_segment_length=0.1, margin=0.0):
    """
    Compute segments (start, end) to keep (non-silent parts) based on silence intervals.
    Adds margin between the segments.
    """
    segments = []
    current_start = 0.0
    for s_start, s_end in zip(silence_starts, silence_ends):
        if s_start - current_start > min_segment_length:
            segments.append((current_start, s_start))
        current_start = s_end
    if duration - current_start > min_segment_length:
        segments.append((current_start, duration))

    # Add margin between segments
    if margin > 0:
        segments_with_margin = []
        for i in range(len(segments)):
            start, end = segments[i]
            # Apply left margin (except first segment)
            if i > 0:
                start = max(start - margin, 0)
            # Apply right margin (except last segment)
            if i < len(segments) - 1:
                end = min(end + margin, duration)
            segments_with_margin.append((start, end))
        segments = segments_with_margin

    return segments

def cut_segment(input_file, start, end, output_file, status_callback, fade_duration=0.1):
    """
    Cut a segment from the input file between start and end times using filter_complex.
    This applies a fade-in at the beginning and fade-out at the end of the audio track.
    """
    status_callback(f"Cutting segment: {start:.2f} to {end:.2f} seconds")
    segment_length = end - start

    # If the segment is too short, adjust the fade duration.
    if segment_length < 2 * fade_duration:
        fade_duration = segment_length / 2

    filter_complex = (
        f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v];"
        f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d={fade_duration},"
        f"afade=t=out:st={segment_length - fade_duration}:d={fade_duration}[a]"
    )

    cmd = [
        'ffmpeg', '-y', '-i', input_file,
        '-filter_complex', filter_complex,
        '-map', '[v]', '-map', '[a]',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
        '-c:a', 'aac', '-b:a', '192k',
        output_file
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def concat_segments_without_crossfade(segment_files, output_file, status_callback):
    """
    Concatenate segment files without shifting audio, using a simple concat method.
    """
    status_callback("Concatenating segments...")

    with tempfile.NamedTemporaryFile(mode='w', delete=False) as concat_file:
        for seg in segment_files:
            concat_file.write(f"file '{seg}'\n")
        concat_filepath = concat_file.name

    cmd = [
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_filepath,
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
        '-c:a', 'aac', '-b:a', '192k',
        '-strict', 'experimental',
        output_file
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    os.remove(concat_filepath)

def process_video(input_file, output_file, threshold, min_silence_duration, margin, status_callback):
    try:
        duration = get_video_duration(input_file)
        status_callback(f"Video duration: {duration:.2f} seconds")

        silence_starts, silence_ends = detect_silence(input_file, threshold, min_silence_duration, status_callback)
        segments = compute_keep_segments(silence_starts, silence_ends, duration, margin=margin)
        if not segments:
            raise RuntimeError("No non-silent segments detected. Adjust your threshold or silence duration settings.")
        status_callback(f"Found {len(segments)} non-silent segments.")

        segment_files = []
        with tempfile.TemporaryDirectory() as tmpdirname:
            for idx, (start, end) in enumerate(segments):
                seg_file = os.path.join(tmpdirname, f"segment_{idx}.mp4")
                cut_segment(input_file, start, end, seg_file, status_callback)
                segment_files.append(seg_file)

            # Updated function call: using concat_segments_without_crossfade instead of concat_segments_with_audio_crossfade
            concat_segments_without_crossfade(segment_files, output_file, status_callback)
        status_callback(f"Processing complete. Output saved as:\n{output_file}")
    except Exception as e:
        status_callback(f"Error: {e}")

### Worker Thread for Processing ###
class Worker(QThread):
    updateStatus = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, input_file, output_file, threshold, min_silence, margin, parent=None):
        super().__init__(parent)
        self.input_file = input_file
        self.output_file = output_file
        self.threshold = threshold
        self.min_silence = min_silence
        self.margin = margin  # Store margin value

    def run(self):
        def status_callback(msg):
            self.updateStatus.emit(msg)
        process_video(self.input_file, self.output_file, self.threshold, self.min_silence, self.margin, status_callback)
        self.finished.emit()

### Main Qt GUI ###
class VideoCutterGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video Silence Cutter")
        self.setGeometry(100, 100, 700, 400)
        self.worker = None
        self.initUI()

    def initUI(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        grid = QGridLayout(central_widget)

        # Input file selection
        grid.addWidget(QLabel("Input Video:"), 0, 0)
        self.input_entry = QLineEdit()
        grid.addWidget(self.input_entry, 0, 1)
        self.input_button = QPushButton("Browse...")
        self.input_button.clicked.connect(self.browse_input)
        grid.addWidget(self.input_button, 0, 2)

        # Output file selection
        grid.addWidget(QLabel("Output Video:"), 1, 0)
        self.output_entry = QLineEdit()
        grid.addWidget(self.output_entry, 1, 1)
        self.output_button = QPushButton("Browse...")
        self.output_button.clicked.connect(self.browse_output)
        grid.addWidget(self.output_button, 1, 2)

        # Threshold input
        grid.addWidget(QLabel("Silence Threshold (dB):"), 2, 0)
        self.threshold_entry = QLineEdit("-30")
        grid.addWidget(self.threshold_entry, 2, 1)

        # Minimum silence duration input
        grid.addWidget(QLabel("Min Silence Duration (sec):"), 3, 0)
        self.min_silence_entry = QLineEdit("1")
        grid.addWidget(self.min_silence_entry, 3, 1)

        # Margin Between Segments input
        grid.addWidget(QLabel("Margin Between Segments (sec):"), 4, 0)
        self.margin_entry = QLineEdit("0.5")  # Default margin is 0.2 seconds
        grid.addWidget(self.margin_entry, 4, 1)

        # Run button
        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self.start_processing)
        grid.addWidget(self.run_button, 5, 0, 1, 3)

        # Status output text area
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        grid.addWidget(self.status_text, 6, 0, 1, 3)

    def browse_input(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Select Input Video", "",
                                                  "Video Files (*.mp4 *.mov *.avi *.mkv);;All Files (*)")
        if filename:
            self.input_entry.setText(filename)

    def browse_output(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Select Output Video", "",
                                                  "MP4 Files (*.mp4);;All Files (*)")
        if filename:
            self.output_entry.setText(filename)

    def start_processing(self):
        input_file = self.input_entry.text().strip()
        output_file = self.output_entry.text().strip()
        threshold_str = self.threshold_entry.text().strip()
        min_silence_str = self.min_silence_entry.text().strip()
        margin_str = self.margin_entry.text().strip()  # Get margin value

        if not input_file or not output_file:
            QMessageBox.critical(self, "Error", "Please select both input and output files.")
            return

        try:
            threshold = float(threshold_str)
            min_silence = float(min_silence_str)
            margin = float(margin_str)  # Convert margin to float
        except ValueError:
            QMessageBox.critical(self, "Error", "Threshold, min silence duration, and margin must be numbers.")
            return

        self.run_button.setEnabled(False)
        self.status_text.clear()
        self.append_status("Starting processing...\n")

        # Create and start the worker thread
        self.worker = Worker(input_file, output_file, threshold, min_silence, margin)  # Pass margin to Worker
        self.worker.updateStatus.connect(self.append_status)
        self.worker.finished.connect(self.processing_finished)
        self.worker.start()

    def append_status(self, msg):
        self.status_text.append(msg)

    def processing_finished(self):
        self.run_button.setEnabled(True)

if __name__ == '__main__':
    import sys
    app = QApplication(sys.argv)
    window = VideoCutterGUI()
    window.show()
    sys.exit(app.exec_())
