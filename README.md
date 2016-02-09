ev3dev Photo Booth
==================

A webcam app for LEGO MINDSTORMS EV3 running [ev3dev].

[ev3dev]: http://www.ev3dev.org


Installation
------------

* Install `fswebcam` on your EV3.

        sudo apt-get update && sudo apt-get install fswebcam

* Copy `ev3dev-photo-booth.py` to the `/home/robot` directory on your EV3.

        wget https://raw.githubusercontent.com/dlech/ev3dev-photo-booth/master/ev3dev-photo-booth.py

* Make sure the executable bit is set.

        chmod +x ev3-photo-booth.py


Usage
-----

* Run `ev3-photo-booth.py` from the file browser on your EV3.
* Press the ENTER button (center button on the EV3) or the button on the webcam
  itself if it has one to start the countdown.
* Strike a pose. The picture is captured when the screens says "Cheese!".
* The picture will appear on the screen of the EV3.
* Press the BACKSPACE (back button on the EV3) button to exit.
