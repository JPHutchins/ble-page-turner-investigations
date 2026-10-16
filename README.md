# BLE page-turner investigations

Tools and evidence from making cheap BLE "page turner" ring remotes, starting with the FiKavi **F3**, turn pages on a Kindle through [kindle-hid-passthrough](https://github.com/zampierilucas/kindle-hid-passthrough) and [kindle-button-mapper-rs](https://github.com/zampierilucas/kindle-button-mapper-rs).

## Findings

- The F3 reports its buttons as a HID **Touch Screen**: every up or down press is a short swipe, not a key. The mapper names each press by the way it moved (`tap`, `swipe_left`, `swipe_right`, `swipe_up`, `swipe_down`) so it binds without recording anything: [JPHutchins/kindle-button-mapper-rs#1](https://github.com/JPHutchins/kindle-button-mapper-rs/pull/1).
- Kindle kernels from 4.18 on (a Paperwhite 6 runs 5.15) split the ring into two input nodes with one Bluetooth address, **F3 Touchscreen** and **F3 Consumer Control**. With the address saved, the mapper read the wrong one until [zampierilucas/kindle-button-mapper-rs#90](https://github.com/zampierilucas/kindle-button-mapper-rs/pull/90) (issue [#89](https://github.com/zampierilucas/kindle-button-mapper-rs/issues/89)).
- **Which device to pick in Button Mapper:** **F3 Touchscreen** for the up and down buttons. Add **F3 Consumer Control** as a second device only if you want the C-mode centre button, which is a plain volume key.

## Tools

`page-turner` is a uv project (`uv run page-turner --help`).

- `guided`, `soak`, `show`: probe a ring over a [Bumble](https://github.com/google/bumble) HCI controller, journaling every HID report it sends (see `captures/`).
- `kindle run`, `kindle push`, `kindle pull`: guarded SSH to a Kindle for hardware-in-the-loop tests. Each command is judged before it is sent and journaled to `hil/audit.jsonl`, run or refused. Reads come from an allowlist; anything that changes the device needs `--write` and has to stay inside the mapper's install and the test's scratch folders; remounts, raw storage, reboots and hidden shells are refused outright. Set `PAGE_TURNER_KINDLE` to the device's address, and for KOReader's passwordless SSH, `PAGE_TURNER_ASKPASS` to a program that prints an empty line.

`external/` holds the two projects as git submodules, the mapper pointing at the fork the PRs come from.

## Evidence

- `captures/`: journals of every HID report the ring sent to a Bumble host, step by step.
- `hil/run-2f31c26/`: logs, config and input nodes pulled from a Kindle Paperwhite 6 (firmware 5.19.5, kernel 5.15.41) running the mapper PRs, with the ring picked in MapperManager so its address is saved.
- `hil/audit.jsonl`: every command run on that Kindle during the test, and the one the guard refused.

## Development

`uv run camas` fixes, type-checks and tests; `uv run camas check` is what CI runs, one job per task, discovered from `tasks.py`.
