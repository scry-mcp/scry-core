**1. `start`**: OK start: lineup on MAME, rom_check OK, 306 symbols

<details><summary>call and reply</summary>

```json
{
  "shared": true,
  "background": true,
  "display": "<host>",
  "system": "lineup",
  "reference_rom": "./tmp/demos/lineup/lineup.ref",
  "reference_addr": "0x30000",
  "reference_base": "0x0",
  "symbols": "./tmp/demos/lineup/lineup.map",
  "bases": {"DATA": "0x400", "LUP_JUKEBOX": "rom"},
  "inipath": "./tmp/demos/lineup/lineup-ini",
  "state_dir": "./tmp/demos/lineup/lineup-states",
  "boot_seconds": 60,
  "rompath": "<host>"
}
```

```json
{
  "summary": "<volatile>",
  "status": "ok",
  "system": "lineup",
  "binary": "<volatile>",
  "binary_origin": "<volatile>",
  "version": "0.289 (unknown)",
  "pid": "<volatile>",
  "stub_port": "<volatile>",
  "scratch_dir": "<volatile>",
  "state_dir": "./tmp/demos/lineup/lineup-states",
  "cfg": {"available": false, "why": "no cfg was given, so MAME runs on its defaults"},
  "debugger": {
    "attached": "gdbstub",
    "note": "MAME runs with -debug under this stub. A capture taken at one of this session's stops can land a frame away from an autoboot golden taken by a frame notifier at the same count, in a scene that changes every frame: compare a live capture with a live golden"
  },
  "errorlog_path": "<volatile>",
  "stdout_path": "<volatile>",
  "rom_check": "OK",
  "symbols_total": 306,
  "symbols_format": "tsv",
  "symbols_by_class": {"DATA": 44, "CODE": 201, "LUP_JUKEBOX": 61},
  "symbols_by_cpu": {":maincpu": 306},
  "registers": ["EAX", "ECX", "EDX", "EBX", "ESP", "EBP", "ESI", "EDI", "EIP", "EFLAGS", "CS", "SS", "DS", "ES", "FS", "GS", "ST0", "ST1", "ST2", "ST3", "ST4", "ST5", "ST6", "ST7", "FCTRL", "FSTAT", "FTAG", "FISEG", "FIOFF", "FOSEG", "FOOFF", "FOP"],
  "pc": "0x000ffff0",
  "frame": 0,
  "frame_symbol": "frame",
  "view": "native",
  "views": ["Screen 0 Standard (4:3)", "Screen 0 Pixel Aspect (8:5)", "Cocktail"],
  "background": true,
  "flags": "<volatile>",
  "boot_lua_path": "<volatile>",
  "presence": true,
  "machine": {"cpus": 1, "spaces": 2, "address_map": 7, "regions": 2, "shares": 0, "screens": 1, "rom_files": 3},
  "declarations": {
    "persistent": true,
    "path": "./tmp/demos/lineup/lineup-states/declarations.json",
    "key": "lineup ./tmp/demos/lineup/lineup.map",
    "held": 0,
    "fingerprint": "8670fcf45164056f",
    "rearm": {"rearmed": [], "stale": [], "unresolved": [], "unarmable": [], "evaluated": []},
    "comments": {"rearmed": [], "stale": [], "unresolved": [], "unarmable": []}
  },
  "recommended_release": "0.289",
  "window": "<volatile>",
  "kept": "1 saved for `promote`; start/lineup: nothing this session read names its repository: promote(dry_run=true, root=<the repository>) lists what an approval would create",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "altering_writes": 0,
    "console": {"thread_errors": 0, "reruns": 0, "lost": 0}
  }
}
```

</details>

**3. `run_to`**: OK to the high scores: stopped at Draw_High_Scores_Screen

<details><summary>call and reply</summary>

```json
{
  "ref": "Draw_High_Scores_Screen",
  "control": "Check_Money25",
  "seconds": 120
}
```

```json
{
  "summary": "run_to Draw_High_Scores_Screen: TARGET, control counted 250",
  "status": "ok",
  "verdict": "TARGET",
  "control_hits": 250,
  "controls": [
    {"ref": "Check_Money25", "cpu": ":maincpu", "hits_in_run": 250}
  ],
  "cause": "target Draw_High_Scores_Screen",
  "stop_seq": 2,
  "pc": "0x000317ff",
  "cpu": ":maincpu",
  "frame": 251,
  "regs": {
    "EAX": "0x0500",
    "ECX": "0x0000",
    "EDX": "0x73ca",
    "EBX": "0x0000",
    "ESP": "0x99db",
    "EBP": "0xbe31",
    "ESI": "0x6992",
    "EDI": "0xfb28",
    "EIP": "0x000317ff",
    "EFLAGS": "0xf006",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {
    "address": "317FF",
    "bytes": "1E",
    "text": "push    ds0",
    "symbol": "Draw_High_Scores_Screen",
    "delta": 0
  },
  "following": ["31800: E8 21 FE call    31624h", "31803: B8 01 00 mov     aw,1h", "31806: E8 29 73 call    38B32h", "31809: E8 50 36 call    34E5Ch", "3180C: E8 8F FF call    3179Eh", "3180F: 1F       pop     ds0", "31810: C3       ret     ", "31811: 1E       push    ds0", "31812: E8 0F FE call    31624h", "31815: B8 00 00 mov     aw,0h", "31818: E8 17 73 call    38B32h", "3181B: E8 80 FF call    3179Eh", "3181E: 1F       pop     ds0"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**9. `input`**: OK press coin: COIN pressed

<details><summary>call and reply</summary>

```json
{
  "port": ":P1",
  "field": "Coin 1",
  "frames": 4
}
```

```json
{
  "summary": "input :P1 'Coin 1': held 4 frames, active True, released at frame 265",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 261,
  "frame_after": 266,
  "emulated_before_s": 5.233218,
  "emulated_after_s": 5.331457,
  "cycles": 785919,
  "polls": 5,
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "route": "ioport",
  "port": ":P1",
  "field": "Coin 1",
  "value": "0x00000001",
  "frames": 4,
  "name": "Coin 1",
  "player": 0,
  "mask": "0x00000001",
  "defvalue": "0x00000001",
  "port_before": "0x000000ff",
  "frame_set": 261,
  "released": true,
  "port_held": "0x000000fe",
  "frame_released": 265,
  "active": true,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 7,
  "pc": "0x000300a9",
  "cpu": ":maincpu",
  "frame": 266,
  "regs": {
    "EAX": "0x7000",
    "ECX": "0x0000",
    "EDX": "0x73ca",
    "EBX": "0x05ba",
    "ESP": "0x99d3",
    "EBP": "0xbe31",
    "ESI": "0x8db6",
    "EDI": "0x89db",
    "EIP": "0x000300a9",
    "EFLAGS": "0xf046",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {"address": "300A9", "bytes": "55", "text": "push    bp", "symbol": "New_IRQ_Video", "delta": 0},
  "following": ["300AA: 50             push    aw", "300AB: 53             push    bw", "300AC: 51             push    cw", "300AD: 52             push    dw", "300AE: 56             push    ix", "300AF: 57             push    iy", "300B0: 1E             push    ds0", "300B1: 06             push    ds1", "300B2: 9C             push    psw", "300B3: B8 40 00       mov     aw,40h", "300B6: 8E D8          mov     ds0,aw", "300B8: B8 00 10       mov     aw,1000h", "300BB: 8E C0          mov     ds1,aw", "300BD: FC             clr1    dir", "300BE: 83 3E C8 8D 01 cmp     word ptr [8DC8h],1h", "300C3: 75 0B          bne     300D0h", "300C5: 9D             pop     psw", "300C6: 07             pop     ds1", "300C7: 1F             pop     ds0", "300C8: 5F             pop     iy"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**11. `screen_wait`**: OK counted: the coin counted

<details><summary>call and reply</summary>

```json
{
  "screen": "insert",
  "on_breakpoint": "Check_Money100",
  "seconds": 120
}
```

```json
{
  "summary": "screen_wait screen 'insert': found after 1 firing of breakpoint 'Check_Money100'",
  "status": "ok",
  "verdict": "TARGET",
  "predicate": "screen",
  "already": false,
  "waited_s": "<volatile>",
  "waited_on": {"kind": "breakpoint", "ref": "Check_Money100"},
  "firings": 1,
  "frames_examined": 1,
  "fired_line": 226,
  "emulated_before_s": 5.331457,
  "emulated_after_s": 5.351426,
  "frame_before": 266,
  "frame_after": 267,
  "cycles": 159748,
  "screen": {"name": "insert", "layer": "file"},
  "cause": "stopped at no breakpoint this server armed",
  "stop_seq": 9,
  "pc": "0x000300aa",
  "cpu": ":maincpu",
  "frame": 267,
  "regs": {
    "EAX": "0x7000",
    "ECX": "0x0000",
    "EDX": "0x73ca",
    "EBX": "0x05ba",
    "ESP": "0x99d1",
    "EBP": "0xbe31",
    "ESI": "0x8db6",
    "EDI": "0x89db",
    "EIP": "0x000300aa",
    "EFLAGS": "0xf046",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {"address": "300AA", "bytes": "50", "text": "push    aw", "symbol": "New_IRQ_Video", "delta": 1},
  "following": ["300AB: 53             push    bw", "300AC: 51             push    cw", "300AD: 52             push    dw", "300AE: 56             push    ix", "300AF: 57             push    iy", "300B0: 1E             push    ds0", "300B1: 06             push    ds1", "300B2: 9C             push    psw", "300B3: B8 40 00       mov     aw,40h", "300B6: 8E D8          mov     ds0,aw", "300B8: B8 00 10       mov     aw,1000h", "300BB: 8E C0          mov     ds1,aw", "300BD: FC             clr1    dir", "300BE: 83 3E C8 8D 01 cmp     word ptr [8DC8h],1h", "300C3: 75 0B          bne     300D0h", "300C5: 9D             pop     psw", "300C6: 07             pop     ds1", "300C7: 1F             pop     ds0", "300C8: 5F             pop     iy", "300C9: 5E             pop     ix"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>
