# Custom FastFlags: Windows result and Linux status

## Outcome

Windows Roblox Player validation succeeded. Fleasion delivered modified
ClientSettings responses, the Player accepted dictionary-compressed (`dcz`)
responses, and the following effects were observed in Glitch Zone:

- `DFIntTaskSchedulerTargetFps` changed the visible counter from 20 to 37
  after the cache-preseed path was added.
- `FFlagDebugSkyGray=True` produced the expected gray sky.
- `DFFlagDebugDrawBroadPhaseAABBs=True` produced the expected colored AABB
  outlines, and was subsequently used to validate live updates.

Focused native Windows validation passed with `26 passed`:

```powershell
uv run --no-sync pytest -q tests/test_custom_fflags.py tests/test_app_single_instance.py
```

`--no-sync` was used only because the running Windows launcher keeps
`fleasion.exe` open; a normal closed-app run can use ordinary `uv run`.

## How it operates on Windows

1. The Custom FastFlags UI saves string-valued overrides in Fleasion settings.
2. Before Roblox Player starts, Fleasion routes the two ClientSettings hosts to
   its local TLS proxy. The Windows bootstrapper endpoint
   (`PCClientBootstrapper`) is passed through unchanged, preventing the
   installation failure seen when it was modified.
3. For `PCDesktopClient`, Fleasion fetches the upstream response, decodes it,
   merges custom flags, and returns it to Player. For modern `dcz` responses it
   downloads the advertised public dictionary, decompresses, merges, and
   recompresses using that same raw dictionary.
4. Fleasion adds the runtime-only companion flag
   `DFIntSecondsBetweenDynamicVariableReloading=1`. This produces Player log
   entries approximately once per second instead of every 120 seconds.
5. Roblox normally answers repeated refreshes with HTTP `304 Not Modified`.
   Fleasion detects a saved flag-set change, removes the conditional request
   headers once, obtains a fresh `200` body, injects the new values, then lets
   normal conditional refreshes resume. Fleasion also checks the settings file
   timestamp so a saved UI edit is visible to the running proxy without a
   proxy restart.
6. Some flags are consumed before the first network refresh. While Roblox is
   closed, Fleasion atomically pre-seeds Windows'
   `%LOCALAPPDATA%\Temp\Roblox\cache\flag_cache.dat` when it is in the known
   uncompressed layout. This is why a startup-only target-FPS change works at
   the next Player launch.

The relevant implementation is in:

- `src/fleasion/proxy/addons/custom_fflags.py`
- `src/fleasion/proxy/server.py`
- `src/fleasion/proxy/master.py`
- `src/fleasion/gui/modifications_tab.py`

## Performance observation

A 20-second steady-state Windows sample on a 16-logical-core system measured:

| Mode | Proxy worker | Roblox Player | Average total CPU |
| --- | ---: | ---: | ---: |
| Custom FastFlags enabled | 0.68% of total capacity | 8.67% | 24.24% |
| Proxy active, Custom FastFlags disabled | 0.89% | 7.79% | 24.57% |

The proxy worker was not measurably more expensive with the one-second refresh
enabled. The small difference is normal live-game/proxy variation, so no
performance optimization is currently justified.

## Linux/Sober status

Linux is not yet feature-equivalent to Windows.

Verified from the earlier Sober work:

- Sober accepted Fleasion's modified and re-encoded `dcz` response; its logs
  reported a completed dynamic flag fetch with a valid tombstone.
- The previous dynamic refresh did **not** visibly apply the FPS or gray-sky
  test flags in the running Sober game.
- The gray-sky flag did work when placed in Sober's startup configuration,
  showing that this Android-based runtime distinguishes startup flags from
  later dynamic settings.

The generic ClientSettings proxy and `dcz` handling can run on Linux, but the
Windows cache preseed is deliberately Windows-only: Sober's equivalent cache
path, format, and startup precedence have not been established. Therefore the
current code should not be expected to apply startup-only flags on Linux.

Further Linux work is needed before claiming parity:

1. Revalidate the current one-time-fresh-response behavior against Sober's
   active ClientSettings endpoint and determine which flags it actually treats
   as dynamic.
2. Identify Sober's flag-cache format and location, then add a separate,
   guarded preseed implementation if it is safe to modify.
3. Validate a full clean startup and a live `False -> True -> False` dynamic
   flag update on Sober. Do not assume the Windows Player result transfers to
   the Android runtime.

## Notes

- The original Windows handoff test used `DFIntTaskSchedulerTargetFps=20` and
  `FFlagDebugSkyGray=True`; later values were intentionally changed during
  validation to prove that newly injected settings, rather than stale cache,
  were being observed.
- The worktree was already dirty before this work and remains intentionally
  uncommitted.
