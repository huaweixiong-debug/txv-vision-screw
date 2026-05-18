# Claude Code Handoff

## Background

This project is the expansion valve HMI under:

- `S:\expansion_valve_hmi`

The user is editing the UI for the **Settings -> Production Settings -> Product Settings** area.

The user originally wanted:

1. Keep the left/right layout unchanged:
   - left = `产品设置`
   - right = `人员设置`
2. Make product rows more compact.
3. Narrow the `型号` and `规则` fields.
4. If fixed widths kept failing to show up, make the widths adjustable by the user.

## Important Context

There are **two environments** involved and they were easy to mix up:

1. **Local machine**
   - Browser checks here used `http://127.0.0.1:8011/`
2. **Remote target machine**
   - The user actually wants to test on the **target computer**
   - The user said they can start and test there themselves

At one point I mistakenly verified local behavior while the user meant remote behavior.

## Current Goal

Claude Code should continue from this state and make sure the target computer's page actually shows a visible width control for product columns.

The intended result is:

- In `设置 -> 生产设置 -> 产品设置`
- A visible static control bar appears **above the product rows**
- It contains:
  - `型号宽度`
  - `规则宽度`
  - `重置列宽`
- Adjusting those controls changes the product table widths

## Files Already Modified

### 1. `web/index.html`

Relevant lines:

- [index.html](/S:/expansion_valve_hmi/web/index.html:7)
- [index.html](/S:/expansion_valve_hmi/web/index.html:329)
- [index.html](/S:/expansion_valve_hmi/web/index.html:417)

What was changed:

- Asset URLs were version-bumped multiple times. Latest intended version is:
  - `/styles.css?v=20260515h`
  - `/app.js?v=20260515h`
- A **static** width control block was inserted above `#productRows`:
  - `型号宽度`
  - `规则宽度`
  - `重置列宽`

Important note:

- Earlier attempts injected controls dynamically from JS.
- Latest state moves the width controls into **static HTML** so they should appear even if `renderProductTable()` timing is weird.

### 2. `web/app.js`

Relevant lines:

- [app.js](/S:/expansion_valve_hmi/web/app.js:10)
- [app.js](/S:/expansion_valve_hmi/web/app.js:35)
- [app.js](/S:/expansion_valve_hmi/web/app.js:57)
- [app.js](/S:/expansion_valve_hmi/web/app.js:123)
- [app.js](/S:/expansion_valve_hmi/web/app.js:516)

What was changed:

- Added persistent width storage:
  - `PRODUCT_GRID_WIDTHS_KEY`
- Added:
  - `loadProductGridWidths()`
  - `applyProductGridWidths()`
  - `syncProductWidthControls()`
  - `bindProductWidthControls()`
  - resizer support for `model` and `rule`
- `renderProductTable()` was updated so:
  - the product grid uses adjustable widths
  - controls sync to current width state

Important note:

- `bindProductWidthControls()` was changed to target the **static HTML block**:
  - `#productWidthTools`

### 3. `web/styles.css`

Relevant lines:

- [styles.css](/S:/expansion_valve_hmi/web/styles.css:983)
- [styles.css](/S:/expansion_valve_hmi/web/styles.css:1061)

What was changed:

- Product grid now uses CSS variables:
  - `--product-model-col`
  - `--product-rule-col`
- Added styling for:
  - `.product-column-tools`
  - width sliders
  - output labels
  - small reset button
- Existing compact layout and product/person split remain in place

### 4. `app/storage.py`

Relevant line area:

- [storage.py](/S:/expansion_valve_hmi/app/storage.py:126)

What was changed:

- Fixed a syntax error by removing a stray `)` after schema migration logic.

This was necessary because fresh preview instances would not start while the syntax error existed.

## What Was Observed

### Local

At various points, local checks showed:

- `http://127.0.0.1:8011/api/health` returned `200`
- local HTML responses included the latest versioned assets
- local `app.js` responses included the width-control logic

However, the in-app browser kept showing an old-looking page state while the user was sitting on:

- `http://127.0.0.1:8011/api/health`

### Remote

Remote preview launching was inconsistent:

- Foreground run on remote machine could serve `127.0.0.1:8011`
- Background relaunch via automation was unreliable
- That made end-to-end remote verification incomplete from my side

Because of that, the user asked to stop there and just hand off the work so they can test directly on the target computer.

## Most Likely Next Step

Claude Code should verify on the **target machine itself** which page is really being served.

Recommended checklist:

1. Start the app on the target machine from the real working copy the user uses.
2. Open:
   - `http://127.0.0.1:8011/`
3. Go to:
   - `设置 -> 生产设置 -> 产品设置`
4. Confirm whether the static width bar appears above the product rows.
5. If it still does not appear:
   - inspect the live served `index.html`
   - confirm it contains `id="productWidthTools"`
   - confirm the running instance is serving the same `web/index.html` as this workspace

## If The Controls Still Do Not Show

Then the issue is very likely one of these:

1. The target machine is launching a **different copy** of the project.
2. The target machine is serving an older build directory or cached preview folder.
3. The actual runtime entrypoint is not using `S:\expansion_valve_hmi\web\index.html`.

In that case, the next person should compare:

- the file being served at runtime
- the workspace file:
  - [index.html](/S:/expansion_valve_hmi/web/index.html:329)

The simplest proof is whether the live HTML contains:

- `productWidthTools`
- `data-width-col="model"`
- `data-width-col="rule"`

## Suggested Verification Commands

These were useful during debugging:

```powershell
Invoke-WebRequest -Uri 'http://127.0.0.1:8011/' -UseBasicParsing
```

```powershell
Invoke-WebRequest -Uri 'http://127.0.0.1:8011/?v=20260515h' -UseBasicParsing
```

```powershell
Invoke-WebRequest -Uri 'http://127.0.0.1:8011/styles.css?v=20260515h' -UseBasicParsing
```

```powershell
Invoke-WebRequest -Uri 'http://127.0.0.1:8011/app.js?v=20260515h' -UseBasicParsing
```

## Summary

The codebase now contains the intended solution:

- static width controls in HTML
- JS binding for width persistence
- CSS variable-driven product column widths

What remains is runtime verification on the target machine and, if needed, identifying which actual project copy or preview directory that machine is launching.
