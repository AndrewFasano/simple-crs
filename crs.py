#!/usr/bin/env python3

import requests
import shutil
import yaml
import pickle
import os
import tarfile
import logging
from datetime import datetime

API_TOKEN   = open("api_token.txt").read().strip()
DL_DIR      = "dl"
COMP_DIR    = "competitions"
CACHE_DIR   = "cache"

API_BASE    = "https://rode0day.mit.edu/api/{}/".format(API_TOKEN)

logging.basicConfig(format='%(levelname)s:\t%(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.WARNING)


for x in [DL_DIR, COMP_DIR, CACHE_DIR]:
    if not os.path.exists(x):
        os.makedirs(x)

def get_status(force_reload=False):
    """
    Get status from /latest.yaml, save to .latest.yaml locally
    Only reload when we're past the end date of the local file
    """

    latest_path = os.path.join(DL_DIR, "latest.yaml")
    if os.path.isfile(latest_path) and not force_reload:
        try:
            data = pickle.load(open(latest_path, "rb"))
            if datetime.now() < data['end']:
                logger.debug("Using cached status becaue {} < {}".format(datetime.now(), data['end']))
                return data
        except:
            logger.warning("Cached latest.yaml was corrupted")

    r = requests.get(API_BASE+"latest.yaml")
    r.raise_for_status()

    try:
        data = yaml.load(r.text)
    except:
        raise RuntimeException("Could not load status, got message: {}".format(r.text))

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
    dl_path = os.path.join(DL_DIR, (os.path.basename(dl_gz)))
    extract_dir = os.path.join(COMP_DIR, str(status["rode0day_id"]))
    info_yaml = os.path.join(extract_dir, "info.yaml")

    if os.path.isfile(info_yaml): # already downloaded and extracted
        logger.debug("Already have info.yaml")
        return

    if not os.path.isfile(dl_path):
        logger.debug("Download %s into %s", dl_gz, dl_path)
        dl_tar = requests.get(dl_gz, stream=True)
        dl_tar.raise_for_status()
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
    if not (os.path.isfile(yaml_file)):
        raise RuntimeError("Missing info.yaml file: {}".format(yaml_file))

    info = yaml.load(open(yaml_file))
    if not (info["rode0day_id"] == status["rode0day_id"]):
        raise RuntimeError("Comeptition and latest disagree about the rode0day_id: {} {}".format(info["rode0day_id"], status["rode0day_id"]))

    return info

def test_run(challenge, status=None):
    """
    Run the program on the sample input - Just useful to make sure everything is working (note programs may have no output with sample inputs)
    """
    if not status:
        status = get_status()

    local_dir   = os.path.join('', *[COMP_DIR, str(status["rode0day_id"]), challenge["install_dir"]])
    library_dir = os.path.join(local_dir, challenge["library_dir"])
    binary      = os.path.join(local_dir, challenge["binary_path"])
    input_file  = os.path.join(local_dir, challenge["sample_inputs"][0])
    args        = challenge["binary_arguments"].format(input_file=input_file, install_dir=local_dir)
    command     = "LD_PRELOAD_DIR={library_dir} {binary} {args}".format(library_dir=library_dir, binary=binary, input_file=input_file, args=args)
    logger.info("Running with sample input: {}".format(command))
    os.system(command)


def submit_solution(file_path, challenge_id, status=None):
    """
    Submit a solution 
        Abort if competition has ended
        Save bug_ids in cache and only print when we find new bugs
    """

    if not status:
        status = get_status()

    if challenge_id not in status["challenge_ids"]:
        raise ValueError("Can't submit for challenge with id {} since it's not a part of the current competition ({})".format(challenge_id, status["challenge_ids"]))

    with open(file_path) as f:
        input_file = f.read()
    r = requests.post(API_BASE+"submit", data={"challenge_id": challenge_id}, files={"input": input_file})
    r.raise_for_status()
    result = yaml.load(r.text)


    cache_pickle = os.path.join(CACHE_DIR, str(challenge_id)+".pickle")
    if os.path.isfile(cache_pickle):
        cache = pickle.load(open(cache_pickle, "rb"))
    else:
        cache = {}

    new_bugs = []
    firsts = []
    if result["status"] == 0:
        for bug in result["bug_ids"]:
            first = False
            if bug in result["first_ids"]:
                first = True
            if bug not in cache.keys():
                cache[bug] = {"first": first, "found_at": datetime.now()}
                new_bugs.append(bug)
                firsts.append(bug)

        if len(new_bugs):
            firsts_str = "(firsts: {})".format(', '.join(map(str,firsts)) if len(firsts) else "")
            logger.info("Found new bug(s): {} {}".format(', '.join(map(str,new_bugs)), first_str))
            logger.info("Score is now {}".format(result["score"]))

            # Update cache
            with open(cache_pickle, "wb") as f:
                pickle.dump(cache, f)

    elif result["status"]==1:
        logger.warning("No crash with input %s", file_path)
    if result["status"] > 1:
        logger.warning("Error: %s", result['status_s'])


    logger.debug("%d API requests remaining", result["requests_remaining"])

def main():
    status = get_status()
    get_competition(status)
    info = parse_info(status)
    for challenge_name, challenge in info['challenges'].items():
        #print(challenge, challenge_name)
        test_run(challenge, status)

        # TODO: find bugs

        submit_solution("crs.py", challenge["challenge_id"])
            
if __name__ == "__main__":
    main()
