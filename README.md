# VSR
## Video Silence Remover


### App that I created with ChatGPT to remove the silent parts of a video. Perfect for long presentations or speech with too many pauses and awkward silences. Saves a ton of editing work!

![Screenshot_20250407_034735-1](https://github.com/user-attachments/assets/54979923-8c47-4859-87c8-6871a24e4d5d)

To run it, you'll need to have python, ffmpeg and PyQt5 installed.
This should run on almost any system, no problem:

`python VSR.py`

<br/>
<br/>

If you use linux, just download the AppImage from the releases page, so you don't need to open the terminal to run.

<br/>
<br/>

You can also create a conda environment:

``conda create -n VSR python=3.10``

Then clone this repo assuming you have git installed:

`git clone https://github.com/SudoInstallAI/VSR.git`

Open the terminal in the cloned folder and activate your environment:

`conda activate VSR`

Then install the requirements:

`pip install -r requirements.txt`

And finally run it:

`python VSR.py`
