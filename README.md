# SimpleCRS
This Python 3 script is an example consumer of the Rode0day API. It will automatically play in Rode0day competitions using AFL in qemu-mode. At the end of each competition, the script will load the next competition and switch to fuzzing those binaries.

## Installation
1. `git clone https://github.com/AndrewFasano/simple-crs.git`
1. `cd simple-crs`
1. `mkvirtualenv --python=\`which python3\` crs`
1. `pip install -r requirements.txt`
1. Save your API key provied at https://rode0day.mit.edu/profile into `api_key.txt`

To enable afl-support you must also build AFL in qemu\_mode as described in [AFL's README](https://github.com/mirrorer/afl/blob/master/qemu_mode/README.qemu) and place the afl-fuzz binary is on your $PATH.


## Features
* Get competition status
* Get competition files
* Run challenges with sample input
* Try to find bugs with afl in qemu mode
* Submit bug-triggering inputs
* Caching to minimize rate-limited requests

## Planned features
* Additional fuzzing backends
