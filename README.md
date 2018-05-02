#### SimpleCRS
This Python 3 script is an example consumer of the Rode0day API. It will automatically play in Rode0day competitions using AFL in qemu-mode. At the end of each competition, the script will load the next competition and switch to fuzzing those binaries.

# Installation
1. `git clone https://github.com/AndrewFasano/simple-crs.git`
2. `cd simple-crs`
3. Save your API key provied at https://rode0day.mit.edu/profile into `api_key.txt`


# Features
* Get competition status
* Get competition files
* Run challenges with sample input
* Try to find bugs with afl in qemu mode
* Submit bug-triggering inputs
* Caching to minimize rate-limited requests

# Planned features
* Additional fuzzing backends
