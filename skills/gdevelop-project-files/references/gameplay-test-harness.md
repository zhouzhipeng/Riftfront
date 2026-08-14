# Gameplay-test harness

Read this guide in full before creating or materially changing a gameplay test.
It describes the strict version 5 project layout and the harness shipped by
this branch. For exact, current signatures and result shapes, the generated
`.gdevelop/harness-api.d.ts` file is authoritative.

The
[official GDevelop gameplay-test guide](https://wiki.gdevelop.io/gdevelop5/interface/gameplay-tests/)
is useful background for the editor-facing feature. This local reference is
not a copy of that guide: it owns the branch-specific multi-file format,
generated declaration, deterministic authoring rules, and MCP workflow.

## Source shape and file identity

A `tests/*.js` source is the body of one async test. Write top-level `await`
directly. Do not wrap the body in `async function test() { ... }`,
`async () => { ... }`, or `(harness) => { ... }`; the runner supplies
`harness` and executes the stored body itself.

```js
await harness.goToScene('Level1');
await harness.stepFrames(1);
harness.assert(
  harness.getSceneName() === 'Level1',
  'Level1 remains the active scene after its first update'
);
```

All project and extension tests are declared in the root `tests.settings`.
Their JavaScript sources are flat files directly below `tests/`:

```toml
kind = "tests"
settingsFormatVersion = 5

[[tests]]
scope = "project"
order = 0
name = "Player can jump"
type = "gameplay"
description = "Space starts an upward movement."
file = "tests/Player%20can%20jump.js"

[[tests]]
scope = "extension"
extension = "Combat"
order = 0
name = "Enemy takes damage"
type = "gameplay"
description = "A projectile reduces enemy health."
file = "tests/Combat%20-%20Enemy%20takes%20damage.js"
```

A project test belongs to the project's test container. An extension test
belongs to the named extension, but its source is still in the root, flat
`tests/` directory. Project tests run in container order, followed by each
extension in project order and its tests in container order.

The `file` is a canonical identity, not a URI:

- It starts with `tests/`, ends in `.js`, and has no other slash.
- It has no `game://` prefix, drive letter, absolute prefix, query, fragment,
  traversal segment, or nested directory.
- The preferred basename is the test name for a project test and
  `<Extension> - <Test>` for an extension test. The version 5 writer applies
  managed-name percent encoding and deterministic suffixes for normalized
  filename collisions.
- Existing tests must use their exact recorded `file`; do not substitute the
  display name or guess a collision suffix.
- Every test owns exactly one source, every managed source belongs to exactly
  one test, and `source` is not an authored path-field alias.

The empty manifest uses `tests = [ ]`. Never store last-run state in
`tests.settings`; the editor owns the generated
`.gdevelop/gameplay-test-results.json` summary.

## Deterministic simulation

The game does not advance while ordinary test JavaScript runs. The harness
advances it only when the script requests an advancing operation. Normal
stepping simulates a fixed `1 / 60` second per frame, independent of monitor
refresh rate or how quickly the host executes the test.

Await every operation that can advance, launch, poll, or drive the game. This
includes `goToScene`, `stepFrames`, `stepUntil`, stability helpers, control
probes, aiming helpers, and other async control helpers declared in
`harness-api.d.ts`. Omitting `await` makes later reads race the intended game
state.

```js
// Wrong: the snapshot can be taken before the frame is simulated.
harness.stepFrames(1);
const raced = harness.getObjects('Player');

// Right: read state only after the requested frame has completed.
await harness.stepFrames(1);
const current = harness.getObjects('Player');
```

Use bounded advancement. Prefer a small fixed frame count when the mechanic
has a defined timing, or `stepUntil(condition, { maxFrames })` when it can
complete within a range. Always assert the boolean returned by a bounded poll;
reaching `maxFrames` returns `false` rather than proving the condition.

Snapshots returned by `getObjects`, `getSceneVariable`, `getGlobalVariable`,
and `getObjectVariable` are JSON-safe values at the moment they are read. They
do not update in place. Take a fresh snapshot after every frame-advancing
operation before asserting new state.

## Arrange, act, assert

Keep each test centered on one mechanic:

1. **Arrange:** enter a fresh scene and create the smallest relevant setup.
2. **Act:** use the player's real input or the mechanic's public trigger, then
   advance a bounded number of frames.
3. **Assert:** inspect fresh state and make a few focused claims with messages
   that explain the observed contract.

Scenario helpers such as `spawn`, `setObjectPosition`, `removeObject`, and the
variable setters may make a situation reachable and repeatable. They must not
fabricate the outcome under test. Spawning a coin in front of the player is a
valid arrangement for a pickup test; deleting the coin or increasing the score
before asserting collection is not. Likewise, setting an enemy's starting
health is setup, while reducing it directly is not a damage test.

Call `goToScene` even when the desired scene is normally first. It replaces
the running scene and steps its initialization frame, so each test starts from
a named, fresh state. Keep test-only setup near the beginning and explain why
it is not the outcome.

Use `harness.assert(condition, diagnosticMessage)` for expected behavior and
`harness.fail(message)` when the test cannot establish a required premise.
Prefer a few mechanic-level assertions over dozens of incidental field checks.
Include useful expected and observed values in failure messages when possible.

Always release simulated input. A `try`/`finally` keeps cleanup reliable when
stepping throws, the test times out, or an intermediate assertion fails:

```js
harness.setKeyPressed('Right', true);
try {
  await harness.stepFrames(20);
} finally {
  harness.releaseAllInputs();
}
```

The same cleanup rule applies to mouse buttons and touches. For a deliberate
press edge, press, await at least one frame, release, and await another frame
when the mechanic observes release state.

## Representative patterns

The names and thresholds below are examples, not hidden defaults. Replace them
with literals validated against the current project and use only methods and
shapes present in `.gdevelop/harness-api.d.ts`.

### Movement and jumping

This test uses the real keyboard path. It keeps the initial snapshot for a
before/after comparison, but obtains new snapshots after each advancement.

```js
await harness.goToScene('PlatformLevel');

const start = harness.getObjects('Player')[0];
harness.assert(!!start, 'PlatformLevel starts with one playable Player');

harness.setKeyPressed('Right', true);
try {
  await harness.stepFrames(18);
} finally {
  harness.releaseAllInputs();
}

const afterRun = harness.getObjects('Player')[0];
harness.assert(
  !!afterRun && afterRun.x >= start.x + 8,
  `Right moves Player forward: start=${start.x}, end=${
    afterRun ? afterRun.x : 'missing'
  }`
);

const jumpStartY = afterRun.y;
harness.setKeyPressed('Space', true);
try {
  await harness.stepFrames(1);
} finally {
  harness.releaseAllInputs();
}

const rose = await harness.stepUntil(
  () => {
    const player = harness.getObjects('Player')[0];
    return !!player && player.y <= jumpStartY - 6;
  },
  { maxFrames: 30 }
);
harness.assert(rose, 'Space makes Player rise within 30 simulated frames');
```

If controls are intentionally unknown, a reviewed control-probe helper can
measure them before arranging the real scenario. Await it, remember that it
restarts the scene, and never treat the probe itself as proof of the mechanic.

### Collection without fabricating the pickup

The harness creates the opportunity, but the game's collision and scoring
logic must remove the coin and award the point.

```js
await harness.goToScene('CollectibleRoom');

const player = harness.getObjects('Player')[0];
harness.assert(!!player, 'CollectibleRoom contains Player');

const oldScore = harness.getSceneVariable('Score');
const oldScoreValue = oldScore ? oldScore.value : 0;
harness.spawn('Coin', player.x + 40, player.y);

harness.setKeyPressed('Right', true);
let collected = false;
try {
  collected = await harness.stepUntil(
    () => harness.getObjects('Coin').length === 0,
    { maxFrames: 90 }
  );
} finally {
  harness.releaseAllInputs();
}

harness.assert(collected, 'Player collects the arranged Coin within 90 frames');
const newScore = harness.getSceneVariable('Score');
harness.assert(
  !!newScore &&
    typeof newScore.value === 'number' &&
    newScore.value === Number(oldScoreValue) + 1,
  `Coin collection increments Score once: before=${oldScoreValue}, after=${
    newScore ? newScore.value : 'missing'
  }`
);
```

The same discipline applies to damage: arrange positions and starting health,
fire through the game's input, then read a fresh object-variable snapshot. Do
not call `setObjectVariable` with the expected post-damage health.

### Layer-based menu

Mouse positions use scene coordinates for the named layer. This matters for a
UI layer whose camera differs from the base layer.

```js
await harness.goToScene('Title');

const menuLayer = harness.getRuntimeLayer('Menu');
harness.assert(
  !!menuLayer && menuLayer.isVisible(),
  'The Menu layer is visible when Title opens'
);

const playButton = harness.getObjects('PlayButton')[0];
harness.assert(
  !!playButton && playButton.layer === 'Menu',
  'PlayButton is available on the Menu layer'
);

harness.setMousePosition(
  playButton.centerX,
  playButton.centerY,
  playButton.layer
);
harness.setMouseButtonPressed(true, 'left');
try {
  await harness.stepFrames(1);
} finally {
  harness.releaseAllInputs();
}
await harness.stepFrames(1);

const openedLevel = await harness.stepUntil(
  () => harness.getSceneName() === 'Level1',
  { maxFrames: 60 }
);
harness.assert(openedLevel, 'Clicking Play opens Level1 within 60 frames');
```

### Scene-variable progression

Setting the initial countdown is arrangement. Letting the game's events update
it is the action.

```js
await harness.goToScene('TimedChallenge');
harness.setSceneVariable('SecondsRemaining', 2);

await harness.stepFrames(121);

const remaining = harness.getSceneVariable('SecondsRemaining');
harness.assert(
  !!remaining && typeof remaining.value === 'number' && remaining.value <= 0,
  `The two-second countdown expires after 121 frames; observed ${
    remaining ? remaining.value : 'missing'
  }`
);
```

Read `.gdevelop/harness-api.d.ts` for the exact recursive variable snapshot
shape before asserting structures, arrays, or child variables. Do not assume a
raw runtime `gdjs.Variable` is returned.

### Performance profiling

Profiling measures host work and is less reproducible than simulated game time.
Use a budget calibrated for the project's test environment, profile a bounded
window, and keep functional correctness in a separate test.

```js
await harness.goToScene('Battle');

harness.startProfiling();
await harness.stepFrames(180);
const profile = harness.stopProfiling();

harness.assert(!!profile, 'Battle returns a three-second profile');
harness.assert(
  !!profile && Number.isFinite(profile.avgStepTimeMs),
  'The average frame cost is a finite number'
);

// Replace 12 with a threshold established for the project's test host.
harness.assert(
  !!profile && profile.avgStepTimeMs < 12,
  `Battle average frame cost stays below 12 ms; observed ${
    profile ? profile.avgStepTimeMs : 'missing'
  } ms`
);
```

`stopProfiling` returns a bounded JSON-safe summary and also retains it in the
test result. Its declaration documents section timings, worst frames, compact
timeline, object counts, and optional renderer or memory counters. Do not reach
into profiler internals.

## Evidence and result statuses

The runner records assertions, bounded console and event logs, final state,
profiles, performance data, and—outside the initial MCP run surface—optional
screenshots. A test result status means:

- `passed`: the async body finished and no assertion failed.
- `failed`: `harness.assert` or `harness.fail` recorded an expected-behavior
  failure.
- `error`: the script, source resolution, preview boot, or another test-level
  execution path produced an unexpected error rather than an assertion
  verdict.
- `stopped`: the user or owning runner stopped the test before completion.
- `timeout`: the per-test wall-clock or frame guard was exhausted.

Do not convert errors or timeouts into passing assertions with broad
`try`/`catch`. Catch only a failure that is itself the behavior under test, and
make the expected error narrow and explicit.

Use `watch(objectName)` before the end when full object snapshots would make
the final-state evidence more diagnostic. Use `getEventLog` for notable scene,
spawn, removal, or stuck events and `getPlayedSounds` when sound playback is a
direct mechanic signal. Prefer assertions on game state over screenshots.

`takeScreenshot` is useful for editor or CLI runs when appearance is the thing
being checked or when a failure needs visual context. It must be awaited so the
current frame is rendered. The initial MCP `run_gameplay_tests` surface forces
screenshot capture off, so its result pages contain no JPEG bytes even if a
script calls `takeScreenshot`. If visual evidence is still needed, capture the
frozen final preview separately with `capture_preview_screenshot`.

## Generated API: read, do not guess

Run `generate-catalogs` before test authoring and read:

```text
.gdevelop/runtime-api.d.ts
.gdevelop/project-api.d.ts
.gdevelop/harness-api.d.ts
```

The harness declaration is the exhaustive reviewed test-authoring contract for
this checkout. It declares the global `harness`, supported methods, options,
snapshots, events, profiles, and result-supporting shapes. It can refer to
public `gdjs` and `GDevelopProject` types from the generated runtime and project
declarations, so load all three together. Never hand-edit generated files, copy
private underscore-prefixed members from runtime source, or infer a method from
an example written for another branch.

Prefer JSON-safe harness snapshots. Use the declared runtime escape hatches
only when no reviewed snapshot or helper expresses the necessary observation;
do not use them to mutate the outcome or reach DOM, debugger transport, stop
controllers, filesystem, shell, storage, or renderer internals.

## Direct edit and MCP verification workflow

The required sequence is:

```text
generate-catalogs
  -> read the three declarations and this reference
  -> edit tests.settings and the flat tests/*.js source directly
  -> validate_project_files
  -> reload_project
  -> run_gameplay_tests
  -> poll get_gameplay_test_results to a terminal status
```

Apply it as follows:

1. Call no-input `generate-catalogs`. Require
   `catalogsRegenerated: true` and a verified receipt for all three catalogs
   plus all three declarations, including the `harnessApi` path.
2. Read the exact `tests.settings` record, selected source, this reference, and
   the three generated declarations. Patch authored files directly; never
   edit `.gdevelop/harness-api.d.ts` or use MCP to author a test.
3. Call no-input `validate_project_files` after the final source edit. Fix all
   structural, generated-code, semantic, and JavaScript-authoring diagnostics
   until the complete pre-runtime receipt succeeds. Validation regenerates the
   six authoring artifacts, so re-read a changed declaration before another
   edit.
4. Complete the project-files skill's Git commit gate, then call
   `reload_project` and poll that reload operation to successful completion.
   The gameplay runner uses the current in-memory project; it never reads the
   selected `.js` path from disk. An un-reloaded disk edit therefore cannot be
   verified by the run.
5. To run one test, call `run_gameplay_tests` with its exact canonical identity:

   ```json
   {
     "file": "tests/Player%20can%20jump.js",
     "timeout_ms": 30000
   }
   ```

   Omit `file` to run all authored tests. An empty string is not omission.
   `timeout_ms` is the wall-clock budget for each selected test and must be
   between 1,000 and 300,000. Record the immediate response's `operation_id`;
   `queued` is a normal start state.

6. Poll `get_gameplay_test_results` with that `operation_id`. The non-terminal
   states are `queued`, `launching`, and `running`. Continue until `completed`
   or `failed`, paging completed results with `offset` and `limit` when needed;
   `limit` cannot exceed 100. If the start response was lost, omitting
   `operation_id` recovers the active or most recently retained operation but
   never starts or retries one.
7. Inspect `summary` and each requested result page. Test-level `failed`,
   `error`, `stopped`, and `timeout` verdicts are data: the operation may still
   be `completed` with `success: true`. Report a behavior as gameplay-test
   verified only when the terminal operation has `status: "completed"` and
   `summary.all_passed: true`.

Only one gameplay-test batch can be active. Do not open or reload a project,
launch another preview, call `verify_project_change`, or start another test run
while it is `queued`, `launching`, or `running`. MCP runs are unpaced and
screenshots are disabled, but assertions, logs, event data, final state,
profiles, and performance data remain available in the paginated results.

Any later authored source edit invalidates the prior validation, commit,
reload, and gameplay-test evidence. Repeat the gates before claiming the new
behavior is verified.
