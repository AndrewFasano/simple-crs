#!/usr/bin/env python3

import shutil
import yaml
import pickle
import os
import tarfile
import logging
import glob
import time
import shlex
import threading
import subprocess
from datetime import datetime
import requests

API_TOKEN = open("api_token.txt").read().strip()
CACHE_DIR = "cache"
COMP_DIR  = "competitions"
API_BASE  = "https://rode0day.mit.edu/api/1.0/"
AFL_PATH = "/home/andrew/git/afl/afl-fuzz" # Change to the location of afl-fuzz on your system

if not os.path.isfile(AFL_PATH):
    raise RuntimeError("You must update your AFL_PATH to the the location of afl-fuzz")

logging.basicConfig(format='%(levelname)s:\t%(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.WARNING)

for x in [COMP_DIR, CACHE_DIR]:
    if not os.path.exists(x):
        os.makedirs(x)

assert(len(API_TOKEN))

def get_status(force_reload=False):
    """
    Get status from /latest.yaml, save to CACHE_DIR/latest.yaml locally
    Only reload when we're past the end date of the local file
    """

    latest_path = os.path.join(CACHE_DIR, "latest.yaml")
    if os.path.isfile(latest_path) and not force_reload:
        try:
            data = pickle.load(open(latest_path, "rb"))
            if not data["rode0day_id"]:
                logger.warning("No rode0day_id cached- refresh")
                return get_status(True)
            if 'end' in data.keys() and datetime.utcnow() < data['end']:
                logger.debug("Using cached status becaue %s < %s", datetime.utcnow(), data['end'])
                return data
        except pickle.PickleError:
            logger.warning("Cached latest.yaml was corrupted")
            raise

    r = requests.get(API_BASE+"latest.yaml")
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logger.error("HTTP Error loading status: %s", e.response.text)
        return None

    try:
        data = yaml.load(r.text)
    except pickle.PickleError:
        logger.error("Could not load status, got message: %s", r.text)
        return None

    if 'rode0day_id' not in data.keys():
        logger.error("Invalid response from api (missing rode0day_id): %s", data)
        return None
    if not data["rode0day_id"]:
        if data["next_start"]:
            return data

        logger.warning("No Rode0day id or next_start provied, returning None")
        return None

    with open(latest_path, "wb") as f:
        pickle.dump(data, f)
    return data

def get_competition(status=None):
    """
    Get the .tar.gz for this competition, extract it into competition_X where X is the rode0day id
    """
    if not status:
        status = get_status()
    dl_gz = status["download_link"]
    dl_path = os.path.join(CACHE_DIR, (os.path.basename(dl_gz)))
    extract_dir = os.path.join(COMP_DIR, str(status["rode0day_id"]))
    info_yaml = os.path.join(extract_dir, "info.yaml")

    if os.path.isfile(info_yaml): # already downloaded and extracted
        logger.debug("Already have info.yaml")
        return

    if not os.path.isfile(dl_path):
        logger.debug("Download %s into %s", dl_gz, dl_path)
        dl_tar = requests.get(dl_gz, stream=True)
        try:
            dl_tar.raise_for_status()
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP Error getting competition binaries: %s", e.response.text)
            return None

        with open(dl_path, "wb") as f:
            shutil.copyfileobj(dl_tar.raw, f)

    logger.debug("Extracting %s into %s", dl_path, extract_dir)
    tar = tarfile.open(dl_path, "r:gz")
    tar.extractall(path=extract_dir)
    tar.close()


def parse_info(status=None):
    """
    Parse info.yaml for the current competition, return parsed yaml object
    """
    if not status:
        status = get_status()
    yaml_file = os.path.join(os.path.join(COMP_DIR, str(status["rode0day_id"])), "info.yaml")
    if not os.path.isfile(yaml_file):
        raise RuntimeError("Missing info.yaml file: {}".format(yaml_file))

    info = yaml.load(open(yaml_file))
    if info["rode0day_id"] != status["rode0day_id"]:
        raise RuntimeError("Comeptition and latest disagree about the rode0day_id: {} {}".format(info["rode0day_id"], status["rode0day_id"]))

    return info

def test_run(challenge, status=None):
    """
    Run the program on the sample input - Just useful to make sure everything is working (note programs may have no output with sample inputs)
    """
    if not status:
        status = get_status()

    local_dir   = os.path.join('', *[COMP_DIR, str(status["rode0day_id"]), challenge["install_dir"]])
    library_dir = None
    if "library_dir" in challenge.keys():
        library_dir = os.path.join(local_dir, challenge["library_dir"])
    binary      = os.path.join(local_dir, challenge["binary_path"])
    input_file  = os.path.join(local_dir, challenge["sample_inputs"][0])
    args        = challenge["binary_arguments"].format(input_file=input_file, install_dir=local_dir)
    if library_dir:
        command     = "LD_LIBRARY_PATH={library_dir} {binary} {args}".format(library_dir=library_dir, binary=binary, args=args)
    else:
        command     = "{binary} {args}".format(binary=binary, args=args)
    logger.info("Locally running with sample input: %s", command)
    os.system(command)


def submit_solution(file_path, challenge_id, status=None):
    """
    Submit a solution
        Abort if competition has ended
        Skip if file already submitted
        Save bug_ids in cache and only print when we find new bugs
    """

    if not status:
        status = get_status()

    if challenge_id not in status["challenge_ids"]:
        raise ValueError("Can't submit for challenge with id {} since it's not a part of the current competition ({})".format(challenge_id, status["challenge_ids"]))

    cache_pickle = os.path.join(CACHE_DIR, str(challenge_id)+".pickle")
    if os.path.isfile(cache_pickle):
        try:
            cache = pickle.load(open(cache_pickle, "rb"))
        except (EOFError, pickle.PickleError):
            logger.error("Couldn't write to %s. Skipping submission of %s for now", cache_pickle, file_path)

    else:
        cache = {}

    if "submitted_files" not in cache.keys():
        cache["submitted_files"] = []

    if file_path in cache["submitted_files"]:
        logger.debug("Skipping %s since we already submitted it", file_path)
        return

    with open(file_path, "rb") as f:
        input_file = f.read()
    r = requests.post(API_BASE+"submit", data={"challenge_id": challenge_id, "auth_token": API_TOKEN}, files={"input": input_file})
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        error = yaml.load(r.text)
        logger.warning("API Error %d: %s", error["status"], error["status_str"])
        if error["status"] == 7:
            logger.warning("Sleeping for a minute...")
            time.sleep(60)
            return submit_solution(file_path, challenge_id, status)
        else:
            logger.warning("API Error %d: %s", error["status"], error["status_str"])
            time.sleep(10)
            return None

    result = yaml.load(r.text)

    cache["submitted_files"].append(file_path)



    new_bugs = []
    firsts = []
    if result["status"] == 0:
        for bug in result["bug_ids"]:
            first = False
            if bug in result["first_ids"]:
                first = True
                firsts.append(bug)
            if bug not in cache.keys():
                cache[bug] = {"first": first, "found_at": datetime.utcnow()} # Storing local timestamps in UTC as well
                new_bugs.append(bug)

        if len(new_bugs):
            firsts_str = ""
            if len(firsts):
                firsts_str = "(firsts: {})".format(', '.join([str(first_id) for first_id in firsts]))

            logger.info("Found new bug(s) for challenge %d: %s %s",challenge_id, ', '.join([str(bug_id) for bug_id in new_bugs]), firsts_str)
            logger.info("Score is now %d", result["score"])

    elif result["status"] == 1:
        logger.warning("No crash with input %s", file_path)
    if result["status"] > 1:
        logger.warning("Error: %s", result['status_s'])

    # Update cache
    with open(cache_pickle, "wb") as f:
        pickle.dump(cache, f)


    logger.debug("%d API requests remaining", result["requests_remaining"])
    return result["bug_ids"]


def _start_afl(challenge):
    """
    Launch subprocess running afl-fuzz in qemu mode
    Translate file input and stdin into the right syntax for AFL
    """

    status = get_status()
    now_ms = int(round(time.time()*1000))

    local_dir   = os.path.join('', *[COMP_DIR, str(status["rode0day_id"]), challenge["install_dir"]])
    library_dir = None
    if "library_dir" in challenge.keys():
        library_dir = os.path.join(local_dir, challenge["library_dir"])
    binary      = os.path.join(local_dir, challenge["binary_path"])
    input_dir   = os.path.dirname(os.path.join(local_dir, challenge["sample_inputs"][0])) # Assuming all input files are in the same directory
    output_dir  = os.path.join('', *[COMP_DIR, str(status["rode0day_id"]), challenge["install_dir"], "outputs_"+str(now_ms)])

    use_stdin   = challenge["binary_arguments"].endswith("< {input_file}") # "< {input_file}" must be at end

    if use_stdin:
        args    = challenge["binary_arguments"].replace("< {input_file}", "").format(install_dir=local_dir) # Remove input_file redirect entirely
    else:
        args    = challenge["binary_arguments"].format(install_dir=local_dir, input_file="@@") # Input file name @@ is replaced by AFL with the fuzzed filename

    bin_command  = "{binary} {args}".format(binary=binary, args=args)
    fuzz_command = "{afl_path} -Q -m 4098 -i {input_dir} -o {output_dir} -- {bin_command}".format(afl_path=AFL_PATH, library_dir=library_dir, input_dir=input_dir, output_dir=output_dir, bin_command=bin_command)

    logger.info("AFL started with command: %s", fuzz_command)

    # We'll copy these all into the subprocess env, but this way we can print the things we've changed if there's an error
    custom_env={}
    if library_dir:
        custom_env["QEMU_SET_ENV"] = "LD_LIBRARY_PATH={}".format(library_dir)
        custom_env["AFL_INST_LIBS"] = "1"


# AFL_INST_LIBS=1 QEMU_SET_ENV=LD_LIBRARY_PATH=$(pwd)/lib ~/git/afl/afl-fuzz -m 4192 -Q -i inputs/ -o output_test -- bin/file -m share/misc/magic.mgc @@

    my_env = os.environ.copy()
    for k,v in custom_env.items():
        my_env[k] = v

    try:
        subprocess.check_output(shlex.split(fuzz_command), stderr=subprocess.STDOUT, env=my_env)
    except subprocess.CalledProcessError as e:
        logger.error(e.output)
        print("Error while running:\n\t {} {}\n\n".format(" ".join(["{}={}".format(k, v) for k,v in custom_env.items()]), fuzz_command))
        raise

def _submit_loop(path, challenge_id):
    while True:
        for filepath in glob.glob(path):
            submit_solution(filepath, challenge_id) # Will only submit new filepaths so we can call repeatedly
        time.sleep(30)

def compete():
    """
    Start a fuzzing and submission thread for each binary. Run until the competition ends
    """
    status = get_status()
    get_competition(status)
    info = parse_info(status)
    fuzz_threads = []
    for challenge_name, challenge in info['challenges'].items():
        logger.debug("Processing %s", challenge_name)
        #test_run(challenge, status)

        # Start fuzzer thread
        t = threading.Thread(target=_start_afl, args=(challenge,))
        t.daemon = True
        t.start()
        fuzz_threads.append(t)

        # Start submission thread watching AFL output
        output_path = "./competitions/{}/{}/outputs_*/crashes/*".format(info["rode0day_id"], challenge["install_dir"])
        t2 = threading.Thread(target=_submit_loop, args=(output_path, challenge["challenge_id"],))
        t2.daemon = True
        t2.start()

    for thread in fuzz_threads:
        # Join threads with timeout corresponding to end of competition
        # The join is blocking so we calculate the delta_t right before the call to join
        delta_t = status['end']-datetime.utcnow()
        thread.join(delta_t.total_seconds())

def main():
    # While there's a competition happening, try to find solutions until we finish or time runs out
    # Then move on to the next competition
    finished = []

    while True:
        status=get_status()
        if not status:
            logger.error("Could not get status, will retry in 1 minute")
            time.sleep(60)
            continue

        if not status['rode0day_id']:
            if "next_start" in status.keys():
                logger.info("No active competition, sleeping until next starts at %s UTC", str(status["next_start"]))
                delta_t = status['next_start']-datetime.utcnow()
                time.sleep(delta_t.total_seconds())
                continue
            else:
                logger.error("No active competition and unknown next start. Sleeping for 1 hour")
                time.sleep(60*60)
                continue

        if datetime.utcnow() > status['end']:
            logger.debug("Provied status is for an ended competition, retrying in 1 minute ")
            time.sleep(60)
            continue

        if status['rode0day_id'] in finished:
            delta_t = status['end']-datetime.utcnow()
            logger.info("Finished with competition %d, sleeping until next starts at %s (in %d seconds)", status['rode0day_id'], str(status['end']), delta_t.total_seconds())
            time.sleep(delta_t.total_seconds())
            continue

        compete()
        finished.append(status['rode0day_id'])

if __name__ == "__main__":
    main()
