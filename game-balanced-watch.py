#!/usr/bin/env python3
"""Keep selected games on the balanced power profile while they run.

falcond can only turn performance mode on or off. The matching falcond user
profiles set performance_mode = false, and this watcher switches to balanced
through the same power-profiles D-Bus API the desktop uses. While a game runs,
it moves the profile back to balanced if performance gets set (for example by
falcond's generic Proton profile for a helper process). When the games close,
it returns to the usual profile.
"""

import glob
import subprocess
import time

# Replace with the lowercase executable names you want to watch.
GAMES = {"example-game.exe"}
GAME_PROFILE = "balanced"
RESTORE_PROFILE = "power-saver"
POLL_S = 5
GRACE_S = 30

PPD_NAME = "org.freedesktop.UPower.PowerProfiles"
PPD_PATH = "/org/freedesktop/UPower/PowerProfiles"


def read_names(proc):
    names = set()
    try:
        with open(f"{proc}/comm") as f:
            names.add(f.read().strip().lower())
        with open(f"{proc}/cmdline", "rb") as f:
            for arg in f.read().split(b"\0"):
                if arg:
                    names.add(arg.decode(errors="replace").replace("\\", "/").rsplit("/", 1)[-1].lower())
    except OSError:
        pass
    return names


def running_games():
    found = set()
    for proc in glob.glob("/proc/[0-9]*"):
        found |= read_names(proc) & GAMES
    return found


def busctl(*args):
    result = subprocess.run(["busctl", "--system", *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def get_profile():
    return busctl("get-property", PPD_NAME, PPD_PATH, PPD_NAME, "ActiveProfile").split()[-1].strip('"')


def set_profile(profile):
    busctl("set-property", PPD_NAME, PPD_PATH, PPD_NAME, "ActiveProfile", "s", profile)


def main():
    switched = False
    last_seen = 0.0
    while True:
        try:
            games = running_games()
            if games:
                last_seen = time.monotonic()
                current = get_profile()
                if not switched and current != GAME_PROFILE:
                    set_profile(GAME_PROFILE)
                    switched = True
                    print(f"{', '.join(sorted(games))}: {current} -> {GAME_PROFILE}", flush=True)
                elif switched and current == "performance":
                    set_profile(GAME_PROFILE)
                    print(f"performance set during play: -> {GAME_PROFILE}", flush=True)
            elif switched and time.monotonic() - last_seen > GRACE_S:
                if get_profile() == GAME_PROFILE:
                    set_profile(RESTORE_PROFILE)
                    print(f"games closed: {GAME_PROFILE} -> {RESTORE_PROFILE}", flush=True)
                switched = False
        except RuntimeError as error:
            print(f"D-Bus call failed: {error}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
