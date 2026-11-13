# energy-profile-bench

Compare CPU power and frame timing across Linux desktop power profiles
(power-saver, balanced, performance).

The script switches the active power profile through tuned-ppd, the
power-profiles D-Bus API that KDE and GNOME use. For each profile it reports:

- **W**: CPU package power from RAPL (`intel-rapl:0`, works on AMD and Intel)
- **clock**: mean clock of the busiest cores
- **frame work**: wall time of each fixed-size chunk of CPU work (p50, p99, max)
- **Tctl**: CPU temperature from k10temp

## Requirements

- Linux with RAPL energy counters, plus tuned and tuned-ppd (`busctl` and `tuned-adm` on the PATH)
- An active desktop session. Profile switching is allowed for the active session, so no root is needed.
- Python 3.8 or newer

## Usage

```sh
python3 energy_profiles.py                        # power-saver, balanced, performance
python3 energy_profiles.py balanced --settle 45   # one profile, longer settle time
```

A full run takes about six minutes.

## Notes

- The script changes your power profile while it runs and restores the profile you started with, including after Ctrl-C.
- The workloads are synthetic. Each worker does a fixed amount of CPU work per 60 FPS frame and then sleeps. Use the results to compare profiles, not to predict FPS in a real game.
- Results depend on the CPU, kernel and firmware. Run it on your own machine.

## Example output

Illustrative output format (values are placeholders, not a benchmark):

```text
<CPU model>, kernel <kernel version>
starting profile: power-saver

[balanced] tuned profile: desktop
  idle     30.0 W   Tctl 40.0 C
  light    35.0 W   clock 4.00 GHz   frame work p50  2.00  p99  3.00  max  4.00 ms   Tctl 45.0 C

restored profile: power-saver
```

## Game watcher

`game-balanced-watch.py` switches to the balanced profile while selected games run, then returns to power-saver.

- It checks running processes every 5 seconds. Edit `GAMES` at the top of the script to list your games' lowercase executable names.
- While a game runs, it switches to balanced through the same D-Bus API the bench uses. If performance gets set during play, it switches back to balanced.
- After the games close, it waits 30 seconds and returns to power-saver. It restores only when it made the switch itself.
- Needs `busctl` and a power-profiles D-Bus service, the same as the bench.

```sh
python3 game-balanced-watch.py
```

To start it at login, copy `examples/autostart/game-balanced-watch.desktop` to `~/.config/autostart/` and replace `/PATH/TO` with the full path to the script.

## falcond examples

`examples/falcond/` has example profiles for falcond, for use only if you run falcond. It holds a generic Proton profile and an editable `example-game.exe` profile. The game profile sets `performance_mode = false`, so falcond does not switch that game to performance mode, and the watcher can keep them on balanced. Both profiles select the `lavd` sched_ext scheduler and set a few other options. They are examples; change them to fit your system.

Copy them to falcond's user profile directory for your installation (for example, `/usr/share/falcond/profiles/user/`).

## License

MIT. See [LICENSE](LICENSE).
