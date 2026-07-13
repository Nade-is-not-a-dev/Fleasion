# Windows validation handoff: custom FastFlags through the Fleasion proxy

## Objective

Determine whether custom FastFlags injected into Roblox ClientSettings work on
the Windows Roblox Player. The unresolved Linux result is specific to Sober's
Android-based runtime and must not be treated as a Windows failure.

The primary validation is:

```json
{
  "DFIntTaskSchedulerTargetFps": "20",
  "FFlagDebugSkyGray": "True"
}
```

Launch AlexKaboom's Glitch Zone (`6484006319`) and capture the lower-right
counter. `FPS: 20` is the required positive result. The gray-sky flag is a
secondary, allowlisted visual control.

## What is implemented

- Custom FastFlag persistence in `src/fleasion/config/manager.py`.
- A Fishstrap-inspired FastFlag table editor in
  `src/fleasion/gui/modifications_tab.py`:
  - one-time, 15-second risk confirmation;
  - enable/disable toggle;
  - add, delete, import, export, search; and
  - disabling retains saved flags but stops modification.
- A ClientSettings response modifier in
  `src/fleasion/proxy/addons/custom_fflags.py`.
- Proxy routing and ClientSettings host selection in
  `src/fleasion/proxy/master.py` and `src/fleasion/proxy/server.py`.
- Linux/macOS helper allowlist updates for the ClientSettings hosts.

The proxy handles normal JSON/gzip/zstd ClientSettings responses. It also
handles Roblox's newer `dcz` dictionary-compressed response correctly: it
downloads the public dictionary identified by the response URL, decompresses
the settings, merges custom flags, recompresses with the same dictionary, and
keeps `Content-Encoding: dcz`.

## Current repository state

- Worktree is intentionally dirty; do not discard existing changes.
- Do not stage, commit, or reset changes unless the user explicitly asks.
- Existing tests passed at the handoff point:

  ```text
  292 passed, 1 skipped
  ```

- Run the full suite with:

  ```powershell
  uv run pytest -q
  ```

## Windows test procedure

1. Start Fleasion normally **before** Roblox so the Windows proxy and hosts
   interception are active from Roblox Player startup.
2. In **Modifications → Custom FastFlags**, accept the one-time warning after
   its 15-second countdown, enable the feature, and add the two test flags
   above. Values are intentionally stored/transmitted as Roblox-style strings.
3. Launch the normal Windows Roblox Player to the Home screen, wait for it to
   finish loading, then enter Glitch Zone. A direct `roblox://` launch is also
   useful as a second test, but Home-first is the primary comparison.
4. Capture:
   - Fleasion's log around ClientSettings traffic;
   - Roblox Player log(s) around ClientSettings/flag loading; and
   - an in-game screenshot of the lower-right FPS counter and sky.
5. Disable the feature, relaunch or wait for another ClientSettings refresh,
   and verify Fleasion no longer logs an injection. Re-enable it and confirm
   saved entries return.

## Expected proxy evidence

Look in Fleasion's log for either:

```text
[CustomFFlags] Injected 2 custom FastFlag(s) into Roblox ClientSettings response
```

or, for a dictionary-compressed request:

```text
[CustomFFlags] Re-encoded custom FastFlags with the Roblox dcz dictionary
```

The first line is logged by the modifier and the second confirms that the
compressed body sent to the client is valid for a `dcz` requester.

## Linux/Sober findings (do not generalize to Windows)

- Sober successfully accepted the proxy's modified/re-encoded `dcz` response:
  `DynamicFastVariableReloader finished flag fetch. Tombstone status: valid`.
- Neither the 20-FPS flag nor the gray-sky flag changed a running game, even
  when Roblox Home was opened first, the refresh completed, and Glitch Zone was
  subsequently entered through the Home UI.
- The same `FFlagDebugSkyGray` did turn the sky gray when set in Sober's own
  startup `fflags` configuration. Therefore, that Android runtime applies this
  flag at startup but not from its later dynamic refresh.
- `DFIntTaskSchedulerTargetFps=20` remained `FPS: 240` even in the local
  startup control. This is consistent with Roblox ignoring the non-allowlisted
  FPS override, but it does not prove the Windows Player behaves the same way.

## If Windows still does not apply an allowlisted flag

First distinguish transport from client behavior:

1. Confirm a modified ClientSettings response was actually delivered in the
   Fleasion log.
2. Check Roblox Player logs for a parse/decompression/integrity error.
3. Test only `FFlagDebugSkyGray=True` from a clean Player start. If that does
   not visibly gray the sky, inspect the exact URL/application name and
   response content type before changing the modifier logic.
4. Preserve `Content-Encoding: dcz` for `dcz` requests. Never fall back to
   plain JSON for a client that requested dictionary compression; Sober proved
   that this makes the client reject the response.

## Relevant files

- `src/fleasion/proxy/addons/custom_fflags.py`
- `src/fleasion/proxy/server.py`
- `src/fleasion/proxy/master.py`
- `src/fleasion/gui/modifications_tab.py`
- `src/fleasion/config/manager.py`
- `tests/test_custom_fflags.py`

