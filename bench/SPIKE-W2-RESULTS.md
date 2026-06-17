# Spike W2 — wyniki (maszyna docelowa i9-13900KF / RTX 4060 Ti)

Data: 2026-06-17

| wariant | fps | %CPU (1 rdzeń) |
|---|---|---|
| bez OpenGL | pending (run on target machine) | pending (run on target machine) |
| z OpenGL   | pending (run on target machine) | pending (run on target machine) |

Próg: ≥10 fps / <25% rdzenia.

**Decyzja:** `USE_OPENGL = False`. Downsampling `auto/peak` + `clipToView` ON,
`disableAutoRange()` w live. Uzasadnienie: Safe default; benchmark run deferred to a real graphical session on the target machine. Flip to True only if that run misses the >=10fps/<25%-core threshold without it.
