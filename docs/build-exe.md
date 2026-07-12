# Building the standalone `uwmirror.exe`

The release workflow builds a single-file, no-console `uwmirror.exe` with
[PyInstaller](https://pyinstaller.org) and attaches it to each GitHub Release,
so end users don't need Python installed. This page documents building it
locally and the collection choices baked into [`uwmirror.spec`](../uwmirror.spec).

## Build it

```powershell
py -3.12 -m venv .venv ; .venv\Scripts\activate
pip install -e . --group build-exe          # pyinstaller + pystray + pillow
pyinstaller uwmirror.spec --noconfirm        # -> dist\uwmirror.exe
```

Build **on Windows with Python 3.12** — PyInstaller bundles the interpreter it
runs under and can't cross-compile, and 3.12 is the project's dev/CI baseline.
The build regenerates `build\uwmirror.ico` from the tray glyph
([packaging/make_icon.py](../packaging/make_icon.py)), so there is no icon
committed as a binary asset.

The result is a ~35 MB self-contained exe. Double-click it (or point Task
Scheduler at it — see [autostart.md](autostart.md)) and it runs with no
console window, controlled from the tray icon and global hotkeys.

## Why the spec collects what it does

`--windowed` alone is not enough for this dependency stack:

- **`dxcam.processor._numpy_kernels`** — dxcam loads its compiled numpy kernel
  via `importlib.import_module()`, which PyInstaller's static analysis can't
  see. If the `.pyd` isn't bundled, dxcam silently falls back to an OpenCV code
  path uwmirror deliberately doesn't ship, and the exe **crashes on the first
  captured frame** with `ModuleNotFoundError: No module named 'cv2'`.
  `collect_all("dxcam")` plus an explicit hidden-import force it in.
- **`pystray._win32`** — pystray selects its OS backend dynamically; the
  Windows one must be named as a hidden import.
- **`comtypes`** — dxcam's COM layer; over-collected as cheap insurance
  (`comtypes.stream` is a known frozen-app gotcha).
- **pygame-ce** ships its own PyInstaller hook, so it needs nothing here.
- **UPX is disabled** (`upx=False`): UPX-compressed single-file exes are a
  classic antivirus/SmartScreen false-positive trigger.

## No console → logging goes to a file

With `console=False`, `sys.stdout`/`sys.stderr` are `None`. `uwmirror.cli`
detects this and routes all logging — and any fatal startup error — to
`%APPDATA%\uwmirror\uwmirror.log`. Check that file first when diagnosing the
frozen build.

## Verifying a build

Real DXGI capture needs a real desktop, so a fresh build is worth a manual
smoke test on a dev machine: run `dist\uwmirror.exe`, confirm no console
window appears, the tray icon shows up, and the log records
`capturing WxH region ... fps` with **no** `cv2` error.

## Antivirus / SmartScreen and code signing

The released `uwmirror.exe` is currently **unsigned**, so on first download
Windows SmartScreen shows an "unknown publisher" prompt, and AV engines
occasionally false-positive — both are inherent to unsigned bundled-interpreter
executables, not specific to uwmirror. UPX is already disabled (`upx=False` in
the spec) to reduce the AV risk. Users who prefer to skip the exe entirely can
`pip install "uwmirror[tray]"` instead.

### What code signing does and doesn't do (2026)

Authenticode signing is worth doing, but set expectations correctly:

- **It does *not* make the SmartScreen prompt disappear on day one.** Microsoft
  removed the "EV certificate ⇒ instant reputation" bypass in 2024; as of 2026
  OV, EV, Azure, and SignPath certificates all still show the first-download
  prompt until the exe accumulates real download reputation (weeks of clean
  installs from a range of users).
- **It does** replace "Unknown publisher" with your *verified* publisher name,
  let reputation **persist and accumulate across releases** (an unsigned exe
  resets to zero reputation every version), and stop **Smart App Control**
  (Windows 11) from blocking the exe outright.

So signing is a long game (build reputation over releases), not a switch.

### Options

| Option | Cost | CI fit | Notes |
|---|---|---|---|
| **Azure Artifact Signing** (was "Trusted Signing", renamed Jan 2026) | ~$9.99/mo | Best — official `azure/artifact-signing-action@v2`, OIDC (no long-lived secrets) | Cert issued in *your* name. Individual devs eligible in **US/Canada** only for public-trust certs; one-time ID verification (photo + liveness). Does **not** issue EV. |
| **SignPath Foundation** | Free (OSS) | Good — `signpath/github-action-submit-signing-request@v2` | OV cert on a real HSM. Requires an application/approval, a **manual approve step per release**, and the publisher shows as "SignPath Foundation", not you. |
| **Buy an OV/EV cert** | ~$180–580/yr | Harder | Since June 2023 the private key must live on FIPS hardware, so **you cannot put a `.pfx` in a GitHub secret**. Route it through Azure Key Vault (Premium) + `AzureSignTool`/`jsign`. No SmartScreen advantage over the two above. |
| **Self-signed** | Free | n/a | Signs the binary but chains to no trusted root — SmartScreen treats it like an unsigned file. Only useful for internal machines where you install the cert. **Does not help public distribution.** |

For a solo maintainer the realistic picks are **Azure Artifact Signing**
(cheapest fully-automated path, your own identity) or **SignPath Foundation**
(free, at the cost of a manual approval per release).

### Wiring it into CI when you're ready

`release.yml` intentionally does **not** sign today. To add it, drop a
secrets-gated step into the `build-exe` job after `pyinstaller` — gate on a
computed output (not `secrets.*` directly, which can't be used in `if:`) so
forks without secrets still build unsigned:

```yaml
      - name: Check for signing secrets
        id: signcheck
        shell: bash
        run: echo "ready=${{ secrets.AZURE_CLIENT_ID != '' }}" >> "$GITHUB_OUTPUT"

      - name: Sign uwmirror.exe (Azure Artifact Signing)
        if: steps.signcheck.outputs.ready == 'true'
        uses: azure/artifact-signing-action@v2
        with:
          azure-tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          azure-client-id: ${{ secrets.AZURE_CLIENT_ID }}   # OIDC federated; add id-token: write
          endpoint: https://eus.codesigning.azure.net/
          signing-account-name: <your-account>
          certificate-profile-name: <your-profile>
          files: dist/uwmirror.exe
          file-digest: SHA256
          timestamp-rfc3161: http://timestamp.acs.microsoft.com
          timestamp-digest: SHA256
```

An always-mandatory detail whatever the provider: **RFC 3161 timestamping**
(`signtool ... /tr <TSA-URL> /td sha256 /fd sha256`, or the action inputs
above). Without a trusted timestamp the signature becomes invalid the moment
the certificate expires; with one it stays valid indefinitely. `signtool.exe`
ships on the `windows-latest` runner (in the Windows SDK) if you prefer to call
it directly instead of a vendor action.
