# Spike W2 — wyniki (maszyna docelowa i9-13900KF / RTX 4060 Ti)

Data: 2026-06-17

Pomiar uruchomiony na maszynie docelowej (DISPLAY=:0, xcb). Liczby = **sufit** (timer 0 ms,
render tak szybko jak się da — NIE operating-point).

| wariant | fps (sufit) | %CPU (1 rdzeń, sufit) | %CPU per-klatkę |
|---|---|---|---|
| bez OpenGL | **33.4** | 95% | ~2.84% |
| z OpenGL   | 24.9 | 91% | ~3.67% |

Próg: ≥10 fps / <25% rdzenia (w operating-point).

**Decyzja (POTWIERDZONA pomiarem): `USE_OPENGL = False`.** Downsampling `auto/peak` +
`clipToView` ON, `disableAutoRange()` w live.

Uzasadnienie:
- Bez OpenGL jest **szybciej** (33.4 vs 24.9 fps) i **taniej per-klatkę** (~2.84% vs ~3.67% rdzenia).
  Dla wielu małych wykresów 2D OpenGL dokłada narzut bez korzyści — włączenie go pogorszyłoby budżet.
- Próg ≥10 fps spełniony z dużym zapasem.
- 95% CPU dotyczy renderu max-fps (sufit). **Realna apka renderuje w tempie danych** (1 Hz —
  `setData` per snapshot live, redraw HistoryStrip per snapshot), więc operating-point CPU to ułamek:
  ~2.84% przy 1 Hz, ~28% dopiero przy ciągłych 10 fps. Wniosek: render jest data-driven (event-em
  ze snapshotu), nie free-running — nie wprowadzać własnej pętli renderującej z `timer(0)`.

## Addendum (styl 1 „Cyberpunk neon / NOC") — antialiasing

Neon-glow chce gładkich linii, więc włączono `antialias=True` (było `False`). Re-pomiar
sufitu na tej maszynie (`bench/spike_w2.py [--aa]`, 32 krzywe + 4-stos history):

| antialias | fps (sufit) |
|---|---|
| False | 99.1 |
| True  | **95.0** |

Koszt AA ≈ **4% przy suficie** (free-running) — przy realnym 1 Hz nieistotny, próg ≥10 fps
spełniony z ~10× zapasem. Glow-pen (`plot.glow_curve`, podwójny pen) trzymany TYLKO na
pojedynczych liniach agregatu (sparkline NET/DISK); stos HistoryStrip i siatki 32/24 bez
glow-penów (spec §4.6). Decyzja: **`antialias=True` OK w budżecie.**
