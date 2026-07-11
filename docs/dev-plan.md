# Python + DXcam TV Mirror — Code Analysis & Development Plan

## 1. Goal & Architecture

Capture the center 16:9 region of the 32:9 ultrawide and present it as a borderless fullscreen window on the TV (set to **Extend** mode). Latency target: relaxed (100–200ms acceptable). Priority: minimal resource footprint.

**Pipeline:**

```
Ultrawide desktop (32:9)
        │
        ▼
DXGI Desktop Duplication (via DXcam)  ── region crop at capture time
        │  numpy array (H × W × 3)
        ▼
pygame Surface (frombuffer)
        │  optional smoothscale → 1920×1080
        ▼
Borderless NOFRAME window on TV display ── blit + flip @ 30–60 fps
```

One process, one thread (DXcam runs its own capture thread internally with `camera.start()`). No encoding, no compositor, no IPC.

## 2. Crop math — correction to the research report

The earlier report contained an error for the 5120×1440 case: it suggested cropping to 1920×1440, which is 4:3 and would distort when scaled to 1080p. Correct math:

- A center 16:9 crop at full height means `crop_width = height × 16 / 9`.
- **5120×1440 source:** crop to **2560×1440** (remove 1280 px per side), then downscale to 1920×1080.
- **3840×1080 source:** crop to **1920×1080** (remove 960 px per side), no scaling needed — pure blit.

The script below computes this generically from the detected monitor resolution, so it works either way.

## 3. Stack analysis

| Component | Choice | Rationale |
|---|---|---|
| Capture | **DXcam** (`pip install dxcam`) — or **BetterCam** (`pip install bettercam`), an actively maintained API-compatible fork | Desktop Duplication API = zero-copy GPU capture until frame readback; `region=` crops at capture, so you never transfer the full 32:9 frame |
| Presentation | **pygame** (SDL2) | `set_mode(..., display=N)` targets the TV directly; NOFRAME borderless; hardware blit |
| Scaling | `pygame.transform.smoothscale` (only if source is 5120×1440) | SIMD-optimized bilinear; ~3–6 ms per 2560×1440→1920×1080 frame |
| Cursor overlay (optional) | `ctypes` `GetCursorPos` + sprite blit | Desktop Duplication does **not** composite the cursor — see §6 |

Why not alternatives: `mss` is pure-CPU GDI capture (slower, higher CPU); OpenCV `imshow` has poor multi-monitor fullscreen control; Electron pulls in a full Chromium (~300MB+ RAM), defeating the lightweight goal.

## 4. Reference implementation (MVP, ~70 lines)

```python
"""tv_mirror.py — center-crop the ultrawide to the TV, 16:9 @ 1080p."""
import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor DPI aware, before pygame

import dxcam
import pygame

ULTRAWIDE_OUTPUT_IDX = 0   # dxcam output index of the ultrawide (verify: dxcam.output_info())
TV_DISPLAY_IDX = 1         # pygame display index of the TV (separate enumeration!)
TV_RES = (1920, 1080)
FPS = 60                   # drop to 30 if you want an even lighter loop


def center_crop_region(width: int, height: int) -> tuple[int, int, int, int]:
    crop_w = int(height * 16 / 9)
    left = (width - crop_w) // 2
    return (left, 0, left + crop_w, height)


def make_camera():
    cam = dxcam.create(output_idx=ULTRAWIDE_OUTPUT_IDX, output_color="RGB")
    region = center_crop_region(cam.width, cam.height)
    cam.start(region=region, target_fps=FPS, video_mode=True)
    src_size = (region[2] - region[0], region[3] - region[1])
    return cam, src_size


def main():
    pygame.init()
    screen = pygame.display.set_mode(TV_RES, pygame.NOFRAME, display=TV_DISPLAY_IDX)
    pygame.display.set_caption("TV Mirror")
    pygame.mouse.set_visible(False)
    clock = pygame.time.Clock()

    cam, src_size = make_camera()
    needs_scale = src_size != TV_RES

    running = True
    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                running = False

        try:
            frame = cam.get_latest_frame()          # numpy (H, W, 3), blocks ≤1 frame
        except Exception:                           # device lost (res change, sleep, UAC)
            cam.stop()
            pygame.time.wait(1000)
            cam, src_size = make_camera()           # reinitialize and continue
            needs_scale = src_size != TV_RES
            continue

        surf = pygame.image.frombuffer(frame.tobytes(), src_size, "RGB")
        if needs_scale:
            surf = pygame.transform.smoothscale(surf, TV_RES)
        screen.blit(surf, (0, 0))
        pygame.display.flip()
        clock.tick(FPS)

    cam.stop()
    pygame.quit()


if __name__ == "__main__":
    main()
```

**Key design decisions in this code:**

- `video_mode=True` is essential for a mirror. Desktop Duplication only delivers frames when pixels *change*; without this flag, a static desktop would stall `get_latest_frame()`. Video mode re-emits the last frame at `target_fps`, keeping the TV alive.
- Region crop happens inside DXcam, so the readback from GPU to numpy only moves the cropped pixels (~10.5 MB/frame at 2560×1440, ~6 MB at 1920×1080), not the full 32:9 frame.
- The try/except around `get_latest_frame()` is the recovery path for the three realistic failure modes: display topology change, monitor sleep, and exclusive-fullscreen mode switches by games. Recreating the camera is cheap (~100 ms).
- DPI awareness must be set **before** pygame initializes, or window coordinates on mixed-DPI setups will be wrong.

## 5. Development plan (staged)

**Stage 0 — Environment & monitor mapping (30 min)**
1. Windows Display Settings → Extend; ultrawide 144Hz primary, TV 120Hz secondary at 1920×1080.
2. `pip install dxcam pygame` (Python 3.10+). If DXcam misbehaves, swap to `bettercam` — same API, actively maintained.
3. Run `python -c "import dxcam; print(dxcam.output_info())"` to identify the ultrawide's `output_idx`.
4. Determine the TV's pygame display index (quick loop over `pygame.display.get_num_displays()` printing `pygame.display.get_desktop_sizes()`). These two indices are **independent enumerations** — never assume they match.

**Stage 1 — MVP (1–2 hours)**
Implement the script above. Acceptance criteria: TV shows the center crop fullscreen, ESC exits cleanly, dragging windows on the ultrawide appears on the TV within ~2 frames, static desktop keeps rendering (video_mode check).

**Stage 2 — Polish (2–3 hours, pick what you need)**
- **Cursor overlay:** Desktop Duplication omits the cursor, so the TV won't show your mouse. If that matters for your content-creation shots: `ctypes.windll.user32.GetCursorPos()` each frame, translate into crop coordinates, scale, and blit a small cursor PNG. ~15 lines.
- **Focus behavior:** the pygame window steals focus at launch. Optional fix via `pywin32`: `SetWindowPos` with `HWND_TOPMOST | SWP_NOACTIVATE` after creation, so it stays on top of the TV without grabbing input.
- **Pause hotkey:** a global hotkey (e.g., via the `keyboard` package) to freeze/blank the TV when you want privacy.
- **GPU-side scaling (only if CPU use bothers you):** replace `smoothscale` with a `pygame._sdl2.video` Renderer + streaming Texture so the 1440→1080 scale runs on the 4070's copy engine. Cuts CPU by roughly half in the 5120×1440 case. Skip entirely if your panel is 3840×1080 (no scaling happens anyway).

**Stage 3 — Autostart & daemonization (30 min)**
- Run with `pythonw.exe` (no console window).
- Task Scheduler task, trigger "At log on", with a 15–30 s delay so display enumeration settles before the script queries monitor indices — same enumeration race the OBS projector suffers from.
- Set "Restart on failure" in the task settings as a supervisor.

## 6. Known limitations & gotchas

| Issue | Impact | Mitigation |
|---|---|---|
| No cursor in capture | Mouse invisible on TV | Stage 2 cursor overlay |
| DRM-protected content (Netflix, some players) | Black region on TV | Inherent to Desktop Duplication; use non-DRM sources for those shots |
| UAC secure desktop prompts | Brief frozen/blank frame | Harmless; recovery path handles it |
| HDR desktop | Washed-out colors on TV | Run the desktop in SDR (same caveat as OBS) |
| Exclusive-fullscreen games | Capture device reset | try/except reinit already handles it; borderless-windowed games avoid it entirely |
| G-Sync on ultrawide | The TV window runs on a different display, minimal interference | Keep G-Sync scoped to the ultrawide only; cap script at 30 fps if you ever notice stutter while gaming |
| dxcam maintenance | Original repo is semi-dormant | BetterCam fork is drop-in |

## 7. Expected resource footprint (RTX 4070 Super)

| Metric | 3840×1080 panel (no scaling) | 5120×1440 panel (smoothscale) | OBS equivalent |
|---|---|---|---|
| CPU | ~2–4% of one core @ 60 fps | ~8–12% of one core @ 60 fps (halve at 30 fps) | ~1–3% total but heavier process |
| GPU | <1–2% (duplication + blit) | <2% | ~2–4% (compositor always running) |
| RAM | ~120–160 MB | ~140–180 MB | ~350–450 MB |

So the honest comparison: the win over OBS is mostly **RAM and process weight**, not GPU. Both are light; this is just lighter, with no UI you don't need.

## 8. Testing checklist

- [ ] Static desktop for 60 s → TV keeps displaying (video_mode works)
- [ ] Resolution change on ultrawide → script recovers within ~2 s
- [ ] Monitor sleep/wake → recovers
- [ ] Launch a fullscreen game → recovers on entry and exit
- [ ] Reboot with TV powered on → autostart lands on the correct display
- [ ] Reboot with TV powered **off** → verify behavior (may need TV-on-at-boot, same as OBS)
- [ ] 10-minute run: Task Manager confirms CPU/RAM within the budget above
