#!/usr/bin/env python3
"""Compare CPU power and frame timing across Linux desktop power profiles.

Switches the active power profile through tuned-ppd (the power-profiles D-Bus API
that KDE and GNOME use), waits for it to settle, then runs frame-shaped CPU
workloads and prints one line per phase:

  W      CPU package power from RAPL (intel-rapl:0; also on AMD)
  clock  mean clock of the busiest cores (cpufreq scaling_cur_freq)
  work   wall time of each fixed-size work chunk, p50 / p99 / max
  Tctl   CPU temperature from k10temp at the end of the phase

Every worker does the same CPU work per frame and then sleeps until the next
frame boundary, so slow clock ramps and deep idle wake-ups show up as longer chunks.

The script changes the power profile while it runs and restores the starting
profile on exit. It needs RAPL, tuned-ppd, busctl, tuned-adm and an active desktop
session.

usage: energy_profiles.py [profile ...] [--settle SECONDS]
"""

import argparse
import glob
import multiprocessing as mp
import os
import statistics
import subprocess
import sys
import time

RAPL = "/sys/class/powercap/intel-rapl:0"
PPD_NAME = "org.freedesktop.UPower.PowerProfiles"
PPD_PATH = "/org/freedesktop/UPower/PowerProfiles"
TUNED_PROFILE = {
    "power-saver": "desktop-powersave",
    "balanced": "desktop",
    "performance": "accelerator-performance",
}
FRAME_S = 1 / 60

# name, workers, loop iterations of work per frame, seconds
PHASES = [
    ("idle", 0, 0, 20),
    ("light", 2, 40_000, 30),
    ("heavy", 6, 120_000, 30),
]


def read(path):
    with open(path) as f:
        return f.read().strip()


def energy_uj():
    return int(read(f"{RAPL}/energy_uj"))


def busy_clock_ghz(k):
    freqs = sorted(
        (int(read(p)) for p in glob.glob("/sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq")),
        reverse=True,
    )
    top = freqs[:k]
    return sum(top) / len(top) / 1e6


def cpu_temp_c():
    for hwmon in glob.glob("/sys/class/hwmon/hwmon*"):
        if read(f"{hwmon}/name") == "k10temp":
            return int(read(f"{hwmon}/temp1_input")) / 1000
    return None


def frame_worker(iterations, end_t, results):
    durations = []
    next_frame = time.perf_counter()
    while (start := time.perf_counter()) < end_t:
        x = 1
        for _ in range(iterations):
            x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        durations.append((time.perf_counter() - start) * 1000)
        next_frame += FRAME_S
        pause = next_frame - time.perf_counter()
        if pause > 0:
            time.sleep(pause)
        else:
            next_frame = time.perf_counter()
    results.put(durations)


def run_phase(workers, iterations, seconds):
    end_t = time.perf_counter() + seconds
    results = mp.Queue()
    procs = [mp.Process(target=frame_worker, args=(iterations, end_t, results)) for _ in range(workers)]
    max_uj = int(read(f"{RAPL}/max_energy_range_uj"))
    energy0, t0 = energy_uj(), time.perf_counter()
    for proc in procs:
        proc.start()
    time.sleep(seconds / 2)
    clock = busy_clock_ghz(workers) if workers else None
    time.sleep(max(0.0, end_t - time.perf_counter()))
    durations = [d for _ in procs for d in results.get(timeout=seconds + 10)]
    for proc in procs:
        proc.join()
    elapsed = time.perf_counter() - t0
    watts = ((energy_uj() - energy0) % max_uj) / 1e6 / elapsed
    return watts, clock, durations


def percentile(values, pct):
    ordered = sorted(values)
    return ordered[round(pct / 100 * (len(ordered) - 1))]


def report(name, watts, clock, durations, temp):
    line = f"  {name:<6} {watts:6.1f} W"
    if clock is not None:
        line += f"   clock {clock:4.2f} GHz"
    if durations:
        line += (
            f"   frame work p50 {statistics.median(durations):5.2f}"
            f"  p99 {percentile(durations, 99):5.2f}"
            f"  max {max(durations):5.2f} ms"
        )
    if temp is not None:
        line += f"   Tctl {temp:4.1f} C"
    print(line, flush=True)


def busctl(*args):
    result = subprocess.run(["busctl", "--system", *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def get_profile():
    return busctl("get-property", PPD_NAME, PPD_PATH, PPD_NAME, "ActiveProfile").split()[-1].strip('"')


def set_profile(profile):
    busctl("set-property", PPD_NAME, PPD_PATH, PPD_NAME, "ActiveProfile", "s", profile)


def tuned_profile():
    out = subprocess.run(["tuned-adm", "active"], capture_output=True, text=True, check=True).stdout
    return out.rsplit(":", 1)[-1].strip()


def switch_profile(profile):
    set_profile(profile)
    deadline = time.monotonic() + 20
    while tuned_profile() != TUNED_PROFILE[profile]:
        if time.monotonic() > deadline:
            raise RuntimeError(f"tuned did not switch to {TUNED_PROFILE[profile]}")
        time.sleep(0.5)


def machine_summary():
    cpu = next(
        line.split(":", 1)[1].strip()
        for line in read("/proc/cpuinfo").splitlines()
        if line.startswith("model name")
    )
    return f"{cpu}, kernel {os.uname().release}"


def main():
    parser = argparse.ArgumentParser(description="Compare CPU power and frame timing across power profiles.")
    parser.add_argument("profiles", nargs="*", choices=list(TUNED_PROFILE), default=list(TUNED_PROFILE))
    parser.add_argument("--settle", type=int, default=30, help="seconds to wait after each switch")
    args = parser.parse_args()

    if not os.path.exists(f"{RAPL}/energy_uj"):
        sys.exit(f"no RAPL energy counter at {RAPL}")

    start = get_profile()
    print(machine_summary())
    print(f"starting profile: {start}")
    try:
        for profile in args.profiles:
            switch_profile(profile)
            time.sleep(args.settle)
            print(f"\n[{profile}] tuned profile: {TUNED_PROFILE[profile]}", flush=True)
            for name, workers, iterations, seconds in PHASES:
                watts, clock, durations = run_phase(workers, iterations, seconds)
                report(name, watts, clock, durations, cpu_temp_c())
    finally:
        set_profile(start)
        print(f"\nrestored profile: {start}")


if __name__ == "__main__":
    main()
