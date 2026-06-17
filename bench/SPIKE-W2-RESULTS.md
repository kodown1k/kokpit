# Spike W2 — wyniki (maszyna docelowa i9-13900KF / RTX 4060 Ti)

Data: 2026-06-17

| wariant | fps | %CPU (1 rdzeń) |
|---|---|---|
| bez OpenGL | pending (run on target machine) | pending (run on target machine) |
| z OpenGL   | pending (run on target machine) | pending (run on target machine) |

Próg: ≥10 fps / <25% rdzenia.

**Decyzja (PROWIZORYCZNA — do potwierdzenia pomiarem na maszynie docelowej):** `USE_OPENGL = False`.
Downsampling `auto/peak` + `clipToView` ON, `disableAutoRange()` w live. Uzasadnienie: bezpieczny default — benchmark nie został jeszcze uruchomiony (brak realnej sesji graficznej w worktree). Po uruchomieniu `bench/spike_w2.py` uzupełnić tabelę i potwierdzić/zmienić decyzję: przełączyć na `True` tylko jeśli bez OpenGL pomiar nie trafia w próg ≥10 fps / <25% rdzenia.
