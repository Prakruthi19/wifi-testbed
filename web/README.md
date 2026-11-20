# Web control panel

A Vue 3 front end for the test bed: the lab's access points and networks, every test run, each
test's join steps up to the stage where it failed, and a form that starts a suite in the lab.

| Screen | What it shows |
|---|---|
| Lab | channel maps (where each AP sits in the 2.4/5 GHz spectrum, overlap warnings), access points, client radios, VLANs, latest pass/fail |
| Test runs | grid of every test in every run (flaky tests float to the top; click a square to open the run), or a table; filter by suite or runs with failures |
| Coverage | drag the router, mesh points and devices around a floor plan; modelled signal heatmap per band, switch an AP off, per-device signal. A textbook path-loss model, not measurements: the lab's radios are emulated |
| Run detail | each test with its join timeline (from the capture classifier), recorded facts, saved files |
| Start a run | pick a suite and run it; live log while it runs (live mode only) |

Stack: Vue 3 + TypeScript, Vite, Vue Router, Pinia; Python API in `testbed/api.py` (FastAPI);
Playwright tests at desktop and phone (Pixel 7) sizes.

## Two modes

**Live** (in the lab VM): the panel talks to the API, which reads `reports/` and `lab/inventory.yaml`.

```bash
pip install -r requirements.txt                       # adds fastapi + uvicorn
sudo -E .venv/bin/uvicorn testbed.api:app --port 8000 # root only needed to start runs
cd web && npm install && npm run dev                  # http://localhost:5173
```

**Demo** (GitHub Pages, read-only): the same screens read frozen JSON from `public/demo/`. The
committed files are placeholder data and the page says so. To publish real results instead:

```bash
.venv/bin/python -m testbed.api --export web/public/demo   # in the VM, after lab runs
git add web/public/demo && git commit -m "demo: real lab results" && git push
```

## Tests

```bash
cd web && npx playwright test     # builds the demo, then runs every check at desktop + phone size
```

Set `PW_CHROMIUM=/path/to/chromium` to use an installed Chromium instead of Playwright's download.
